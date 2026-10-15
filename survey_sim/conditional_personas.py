import hashlib
import json
import random
from collections import Counter

from .errors import AppError
from .personas import PersonaGenerator, profile_summary, similarity
from .v2_models import PersonaConditions


def allocate(weights, count, seed):
    if not weights or any(v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
        raise AppError("比例需非負數，且總和大於零。")
    fractions = {k: count * v / sum(weights.values()) for k, v in weights.items()}
    n = {k: int(v) for k, v in fractions.items()}
    for key in sorted(n, key=lambda k: fractions[k] - n[k], reverse=True)[:count - sum(n.values())]:
        n[key] += 1
    labels = [key for key in n for _ in range(n[key])]
    random.Random(seed).shuffle(labels)
    return labels


def condition_plan(conditions, count, seed):
    c = conditions
    rng = random.Random(seed)
    plan = [{} for _ in range(count)]
    if c.age_bands:
        bands = allocate({str(i): band.weight for i, band in enumerate(c.age_bands)}, count, seed + 11)
        for row, band_id in zip(plan, bands):
            band = c.age_bands[int(band_id)]
            row["age"] = rng.randint(band.minimum, band.maximum)
    for field, weights in [("gender", c.genders), ("education", c.educations), ("occupation", c.occupations)]:
        if weights:
            for row, label in zip(plan, allocate(weights, count, seed + len(field))):
                row[field] = label
    # Preserve marginals while resolving a known age/retirement inconsistency.
    if "提早退休" not in c.custom_background and "提前退休" not in c.custom_background:
        for i, row in enumerate(plan):
            if row.get("occupation") == "退休人士" and row.get("age", 60) < 40:
                replacement = next((j for j, candidate in enumerate(plan) if candidate.get("age", 0) >= 40 and candidate.get("occupation") != "退休人士"), None)
                if replacement is None:
                    raise AppError("年齡與退休職業比例無法同時滿足；請調整條件或明確描述提早退休情境。")
                row["age"], plan[replacement]["age"] = plan[replacement]["age"], row["age"]
    for row in plan:
        if "occupation" in row:
            row["status"] = "退休" if row["occupation"] == "退休人士" else "學生" if "學生" in row["occupation"] else "待業" if row["occupation"] == "求職者" else "就業"
            if row["occupation"] == "退休人士" and "age" not in row:
                row["age"] = rng.randint(50, 85)
        if c.income_range:
            minimum = max(c.income_range[0], c.budget_range[0] if c.budget_range else 0)
            row["monthly_income"] = round(rng.uniform(minimum, c.income_range[1]), 2)
        if c.budget_range:
            upper = min(c.budget_range[1], row.get("monthly_income", c.budget_range[1]))
            row["disposable_budget"] = round(rng.uniform(c.budget_range[0], upper), 2)
        elif c.income_range:
            row["disposable_budget"] = round(row["monthly_income"] * rng.uniform(.1, .4), 2)
        if c.interests:
            row["interests"] = list(c.interests)
    return plan


def conditional_person(generator, conditions, assigned, archetype, seed, index, topic, custom, previous,
                       choose_website_tier=False, id_namespace="", should_continue=None):
    """One persona under controlled background / trait conditions, regenerated at most
    twice when it is nearly identical to a recent one. Shared by the People page and
    the workbench. Returns None when should_continue() turns false."""
    previous = [p for p in previous if p is not None]
    rng = random.Random(seed + index + 803)
    traits = {key: round(rng.uniform(*bounds), 4) for key, bounds in conditions.trait_ranges.items()}
    for attempt in range(3):
        if should_continue and not should_continue():
            return None
        person = generator.generate_one(seed + index + attempt * 100003, archetype, topic, custom=custom,
            background_overrides=assigned, trait_overrides=traits, choose_website_tier=choose_website_tier,
            id_namespace=id_namespace, avoid=[profile_summary(x) for x in previous[-20:]])
        if not any(similarity(person, prev) > .985 for prev in previous[-100:]):
            break
    if conditions.core_values:
        person.core_values = list(conditions.core_values)
    person.topic_attributes["product_familiarity"] = round(rng.uniform(*conditions.familiarity_range), 4)
    person.topic_attributes["generation_conditions"] = conditions.model_dump(mode="json")
    return person


class ConditionalPersonaGenerator:
    def __init__(self, provider):
        self.generator = PersonaGenerator(provider)

    def generate_batch(self, count, seed, topic, ratios, conditions, on_persona=None, choose_website_tier=False, id_namespace=""):
        c = PersonaConditions.model_validate(conditions)
        if not 1 <= count <= 10000:
            raise AppError("人物數量需為 1–10,000。")
        plan = condition_plan(c, count, seed)
        types = allocate(ratios, count, seed)
        context = json.dumps(c.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        result = []
        for index, (assigned, archetype) in enumerate(zip(plan, types)):
            p = conditional_person(self.generator, c, assigned, archetype, seed, index, topic,
                c.custom_background + "\n情境條件：" + context, result,
                choose_website_tier=choose_website_tier, id_namespace=id_namespace)
            p.topic_attributes["condition_plan_index"] = index
            # Decision narrative is generated after controlled background and traits.
            from .persona_names import ensure_name
            ensure_name(p, [previous.name for previous in result])
            result.append(p)
            if on_persona:
                on_persona(p, index + 1, count)
        return result


def distribution_check(personas):
    return {field: dict(Counter(getattr(p.background, field) for p in personas)) for field in ["gender", "education", "occupation"]} | {
        "age": [p.background.age for p in personas], "income": [p.background.monthly_income for p in personas],
        "budget": [p.background.disposable_budget for p in personas]}
