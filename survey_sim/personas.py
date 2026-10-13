from __future__ import annotations

import math
import random
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from .errors import AppError
from .models import Background, Behavior, Persona, Traits

ARCHETYPES = ["完全隨機", "AI 自動混合", "價格敏感型", "品質導向型", "外觀導向型", "理性消費型", "衝動消費型", "高度興趣型", "低度興趣型", "自訂人物類型"]
TRAIT_LABELS = dict(zip(Traits.model_fields, ["價格敏感", "品質重視", "美觀重視", "品牌重視", "風險接受", "衝動消費", "理性分析", "社群影響", "個人化需求", "新事物接受"]))


def clamp(x):
    return round(min(.98, max(.02, x)), 4)


def mock_background(seed: int) -> Background:
    rng = random.Random(seed)
    age = rng.randint(18, 68)
    student = age < 25 and rng.random() < .65
    if student:
        occupation, status, education = "大學生", "學生", "大學在學"
        income = rng.randint(6, 20) * 1000
    else:
        occupation = rng.choice(["行政職員", "工程師", "零售服務人員", "設計師", "自由工作者", "教師", "退休人士", "求職者"])
        status = "退休" if occupation == "退休人士" else "待業" if occupation == "求職者" else "就業"
        if status == "退休" and age < 50:
            occupation, status = "自由工作者", "就業"
        income = rng.randint(25, 95) * 1000 if status == "就業" else rng.randint(8, 32) * 1000
        education = rng.choice(["高中職", "專科", "大學", "研究所"])
    budget = round(income * rng.uniform(.08, .4), -2)
    hobbies = rng.sample(["音樂", "運動", "閱讀", "科技", "攝影", "旅行", "收藏", "烹飪", "遊戲", "投資學習"], rng.randint(2, 4))
    lifestyle = rng.choice(["重視規劃且偶爾犒賞自己", "日常忙碌，偏好省時選擇", "喜歡探索但會比較價格", "重視生活品質及長期使用", "以興趣為生活重心，控制其他支出"])
    return Background(age=age, gender=rng.choice(["女性", "男性", "不指定"]), occupation=occupation,
        status=status, education=education, monthly_income=income, disposable_budget=budget,
        lifestyle=lifestyle, interests=hobbies,
        situation=f"{age} 歲的{occupation}，每月可支配預算約 {budget:.0f} 元；{lifestyle}，主要興趣為{'、'.join(hobbies)}。")


def mock_persona(background: Background, seed: int, archetype: str, topic: str = "一般", custom: str = "") -> Persona:
    rng = random.Random(seed + 91)
    # Background -> correlated latent priorities -> traits -> behavior; exceptions remain possible.
    resources = min(1, background.disposable_budget / 18000)
    planning, identity, exploration = rng.random(), rng.random(), rng.random()
    traits = Traits(price_sensitivity=clamp(.78 - .42 * resources + rng.gauss(0, .17)),
        quality_focus=clamp(.35 + .35 * planning + .15 * resources + rng.gauss(0, .12)),
        aesthetics=clamp(.2 + .6 * identity + rng.gauss(0, .12)),
        brand_focus=clamp(.18 + .35 * identity + .2 * rng.random()),
        risk_tolerance=clamp(.15 + .65 * exploration + rng.gauss(0, .13)),
        impulsiveness=clamp(.75 - .45 * planning + rng.gauss(0, .17)),
        rationality=clamp(.2 + .65 * planning + rng.gauss(0, .12)),
        social_influence=clamp(.2 + .4 * identity + rng.gauss(0, .2)),
        personalization=clamp(.15 + .68 * identity + rng.gauss(0, .15)),
        openness=clamp(.2 + .65 * exploration + rng.gauss(0, .12)))
    shifts = {"價格敏感型": ("price_sensitivity", .85), "品質導向型": ("quality_focus", .85),
              "外觀導向型": ("aesthetics", .85), "理性消費型": ("rationality", .88), "衝動消費型": ("impulsiveness", .85)}
    if archetype in shifts:
        name, center = shifts[archetype]
        setattr(traits, name, clamp(center + rng.gauss(0, .08)))
    interest = clamp(rng.betavariate(2, 2))
    if archetype == "高度興趣型":
        interest = clamp(.85 + rng.gauss(0, .06))
    if archetype == "低度興趣型":
        interest = clamp(.12 + rng.gauss(0, .06))
    attributes = {"topic": topic, "topic_interest": interest, "uncertainty": round(rng.uniform(.05, .35), 3)}
    if "ONLYFRAME" in topic.upper() or "小卡" in topic or "收藏" in topic:
        attributes["collection_experience"] = "持續收藏" if interest > .6 else "偶爾接觸" if interest > .3 else "沒有收藏習慣"
    if "金融" in topic or "投資" in topic:
        attributes["investment_experience_years"] = rng.randint(0, max(0, min(15, background.age - 18)))
    motivations = ["符合實際需求", "使用品質"] if traits.rationality > .6 else ["興趣與新鮮感", "個人風格"]
    barriers = ["需要比較價格"] if traits.price_sensitivity > .6 else ["尚未形成明確需求"]
    budget = round(background.disposable_budget * (.08 + interest * .3), -1)
    behavior = Behavior(purchase_frequency="每月" if interest > .65 else "每季" if interest > .3 else "很少",
        spending_budget=budget, platforms=rng.sample(["實體門市", "品牌官網", "網路商城", "社群商店"], 2),
        usage_habits="先評估日常使用情境，再決定是否購買", motivations=motivations, barriers=barriers,
        price_attitude="重視價格，喜歡的商品仍可能等待折扣" if traits.price_sensitivity > .6 else "願依使用價值評估價格",
        quality_expectation="重視耐用及可靠性" if traits.quality_focus > .6 else "品質達到基本需求即可",
        decision_style="比較資訊後決策" if traits.rationality > .6 else "受當下興趣影響，但仍受預算限制")
    return Persona(id=str(uuid5(NAMESPACE_URL, f"survey-persona:{seed}:{archetype}:{topic}:{custom}")),
        name=f"虛擬人物 {seed}", archetype=archetype, background=background, traits=traits, behavior=behavior,
        topic_attributes=attributes, core_values=["符合生活情境", "保留預算彈性", "興趣與實用取得平衡"],
        narrative=f"{background.situation} {behavior.price_attitude}；{behavior.decision_style}。{custom}", seed=seed)


def similarity(a: Persona, b: Persona) -> float:
    av, bv = list(a.traits.model_dump().values()), list(b.traits.model_dump().values())
    distance = math.sqrt(sum((x - y) ** 2 for x, y in zip(av, bv)) / len(av))
    background = abs(a.background.age - b.background.age) / 82
    job = 0 if a.background.occupation == b.background.occupation else 1
    return round(1 - (.75 * distance + .15 * background + .1 * job), 4)


class PersonaGenerator:
    def __init__(self, provider):
        self.provider = provider

    def generate_one(self, seed: int, archetype: str, topic: str, custom: str = "") -> Persona:
        background_result = self.provider.generate("background", {"seed": seed, "archetype": archetype, "topic": topic,
            "custom": custom, "schema": Background.model_json_schema()},
            "建立一位虛擬成年人物的基本背景與生活情境。差異來自情境，避免職業、年齡刻板印象。依 schema 輸出背景 JSON。")
        try:
            background = Background.model_validate(background_result.data)
            persona_result = self.provider.generate("persona", {"seed": seed, "archetype": archetype, "topic": topic, "custom": custom,
                "background": background.model_dump(), "schema": Persona.model_json_schema()},
                "第二階段：根據已確定背景推導人格、價值觀及行為。背景必須原樣保留。心理特徵 0–1，允許合理例外及猶豫；不代表人口分布。主題屬性放 topic_attributes。依 schema 輸出一位完整人物。")
            p = Persona.model_validate(persona_result.data)
            if p.background != background:
                raise AppError("AI 第二階段修改了基本背景，請重新生成人物。")
            # Application owns identities and seed, not the model.
            p.id = str(uuid5(NAMESPACE_URL, f"survey-persona:{seed}:{archetype}:{topic}:{custom}"))
            p.seed, p.archetype = seed, archetype
            return p
        except ValidationError as exc:
            raise AppError("AI 人物資料缺少欄位或數值不合法；請增加輸出 Token 後重試。") from exc

    def generate_batch(self, count: int, seed: int, topic: str, ratios: dict[str, float], custom: str = "", on_persona=None):
        if not 1 <= count <= 10000 or not ratios or any(v < 0 for v in ratios.values()) or sum(ratios.values()) <= 0:
            raise AppError("人物數量需 1–10,000，比例不可負數且總和需大於零。")
        weights = {k: count * v / sum(ratios.values()) for k, v in ratios.items()}
        amounts = {k: int(v) for k, v in weights.items()}
        for k in sorted(weights, key=lambda x: weights[x] - amounts[x], reverse=True)[:count - sum(amounts.values())]:
            amounts[k] += 1
        types = [k for k, v in amounts.items() for _ in range(v)]
        random.Random(seed).shuffle(types)
        result = []
        for i, archetype in enumerate(types):
            p = self.generate_one(seed + i, archetype, topic, custom)
            # Check nearby characters; UI analysis provides full pair inspection.
            for attempt in range(2):
                if not any(similarity(p, previous) > .97 for previous in result[-100:]):
                    break
                p = self.generate_one(seed + i + (attempt + 1) * 100003, archetype, topic, custom)
            result.append(p)
            if on_persona:
                on_persona(p, i + 1, count)
        return result
