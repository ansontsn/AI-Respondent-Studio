from __future__ import annotations

import hashlib
import random

from .models import Background, Persona, Question, QuestionType
from .personas import mock_background, mock_persona, clamp
from .providers import Completion

KEYWORDS = {"price_sensitivity": ["價格", "折扣", "預算", "便宜"], "quality_focus": ["品質", "保護", "耐用"],
            "aesthetics": ["外觀", "美觀", "設計"], "personalization": ["個人特色", "客製", "個人化"],
            "brand_focus": ["品牌"], "rationality": ["比較", "分析", "理性"], "social_influence": ["朋友", "社群"],
            "openness": ["新事物", "嘗試"], "risk_tolerance": ["風險"], "impulsiveness": ["衝動"]}


def field_value(persona: Persona, path: str):
    value = persona.model_dump()
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def answer_question(persona: Persona, q: Question, seed: int, mode: str, variability: float):
    digest = hashlib.sha256(f"{seed}:{persona.id}:{q.id}".encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    traits = persona.traits.model_dump()
    interest = float(persona.topic_attributes.get("topic_interest", .5))
    trait = q.trait
    if not trait:
        trait = next((k for k, words in KEYWORDS.items() if any(w in q.title for w in words)), "")
    if trait in {"purchase_intention", "willingness_to_pay"} or (not q.trait and any(x in q.title for x in ["購買意願", "願意支付", "願意購買"])):
        affordability = min(1, persona.behavior.spending_budget / 2500)
        signal = .48 * interest + .17 * traits["quality_focus"] + .2 * affordability + .15 * traits["personalization"] - .18 * traits["price_sensitivity"]
    else:
        signal = traits.get(trait, .6 * interest + .25 * traits["openness"] + .15 * traits["rationality"])
    noise = .02 if mode == "consistent" else .13 if mode == "natural" else variability
    signal = clamp(signal + rng.gauss(0, noise))
    if q.reverse:
        signal = 1 - signal
    direct = field_value(persona, q.persona_field) if q.persona_field else None
    reason = f"依人物的{q.concept or trait or '主題興趣'}、{persona.behavior.decision_style}及可用預算評估。"
    if q.type in {QuestionType.LINEAR, QuestionType.LIKERT}:
        value = round(q.scale_min + signal * (q.scale_max - q.scale_min))
    elif q.type in {QuestionType.SHORT, QuestionType.PARAGRAPH}:
        value = str(direct) if direct is not None else f"以我的{persona.background.occupation}生活情境，{persona.behavior.price_attitude}。{persona.behavior.barriers[0] if persona.behavior.barriers else '會先確認需求'}。"
        value = value[:q.max_length]
    elif q.type in {QuestionType.SINGLE, QuestionType.DROPDOWN, QuestionType.MULTIPLE, QuestionType.GRID, QuestionType.CHECK_GRID}:
        def choose(row_seed=0, multi=False):
            ranked = []
            for i, option in enumerate(q.options):
                if option.trait_weights:
                    utility = sum(weight * (interest if name == "topic_interest" else traits.get(name, .5)) for name, weight in option.trait_weights.items())
                else:
                    utility = -abs((i / max(1, len(q.options) - 1)) - signal) * 1.5
                # Option semantics supplement utility in generic imported test questions.
                utility += .1 * sum(traits[k] for k, words in KEYWORDS.items() if any(w in option.label for w in words))
                if direct is not None and (str(direct) == option.label or str(direct) == option.id):
                    utility += 10
                if direct is not None and isinstance(direct, (int, float)):
                    import re
                    nums = [int(x) for x in re.findall(r"\d+", option.label)]
                    if len(nums) == 2 and nums[0] <= direct <= nums[1]:
                        utility += 10
                    elif len(nums) == 1 and (("以上" in option.label and direct >= nums[0]) or ("以下" in option.label and direct <= nums[0])):
                        utility += 10
                utility += rng.gauss(0, max(.01, noise)) + row_seed * rng.uniform(-.08, .08)
                ranked.append((utility, option.id))
            ranked.sort(reverse=True)
            if not multi:
                return ranked[0][1]
            minimum = max(q.min_choices, 1 if q.required else 0)
            maximum = min(q.max_choices or len(ranked), len(ranked))
            size = max(minimum, min(maximum, round(1 + signal * (maximum - 1))))
            return [x[1] for x in ranked[:size]]
        if q.type in {QuestionType.GRID, QuestionType.CHECK_GRID}:
            value = {row.id: choose(i, q.type == QuestionType.CHECK_GRID) for i, row in enumerate(q.rows)}
        else:
            value = choose(multi=q.type == QuestionType.MULTIPLE)
    else:
        value = None
    if trait in {"purchase_intention", "willingness_to_pay"}:
        reason = f"主題興趣約 {interest:.0%}，預算 {persona.behavior.spending_budget:.0f} 元；喜歡個人化與願意支付高價是不同考量。"
    return {"question_id": q.id, "value": value, "rationale": reason}


class MockProvider:
    """Deterministic correlated rules for functional tests, not LLM quality claims."""
    def __init__(self, config):
        self.config = config

    def generate(self, operation, payload, system):
        if operation == "connection":
            return Completion({"ok": True})
        if operation == "background":
            return Completion(mock_background(payload["seed"]).model_dump())
        if operation == "persona":
            return Completion(mock_persona(Background.model_validate(payload["background"]), payload["seed"], payload["archetype"], payload["topic"], payload.get("custom", "")).model_dump())
        if operation in {"answer_page", "repair_page"}:
            persona = Persona.model_validate(payload["persona"])
            return Completion({"answers": [answer_question(persona, Question.model_validate(q), payload["seed"], payload["mode"], payload["variability"]) for q in payload["page"]["questions"]]})
        if operation == "analyze":
            return Completion({"topic": payload["questionnaire"]["topic"], "audience": payload["questionnaire"]["audience"],
                "summary": "Mock 依題目註記整理；請自行確認測量概念與反向題。", "questions": [{"id": q["id"], "concept": q.get("concept", ""), "reverse": q.get("reverse", False), "trait": q.get("trait", "")} for p in payload["questionnaire"]["pages"] for q in p["questions"]]})
        raise ValueError(f"Unsupported mock operation: {operation}")
