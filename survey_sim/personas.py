from __future__ import annotations

import math
import logging
import random
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from .errors import AppError, ProviderError
from .models import Background, Behavior, Persona, Traits
from .persona_names import ensure_name, name_for_id

ARCHETYPES = ["完全隨機", "AI 自動混合", "價格敏感型", "品質導向型", "外觀導向型", "理性消費型", "衝動消費型", "高度興趣型", "低度興趣型", "自訂人物類型"]
TRAIT_LABELS = dict(zip(Traits.model_fields, ["價格敏感", "品質重視", "美觀重視", "品牌重視", "風險接受", "衝動消費", "理性分析", "社群影響", "個人化需求", "新事物接受"]))
logger = logging.getLogger(__name__)


def validation_details(exc: ValidationError) -> str:
    """Describe field failures without echoing model output or input values."""
    reasons = {"missing": "缺少必填欄位", "extra_forbidden": "多出未允許欄位",
               "greater_than_equal": "低於允許下限", "less_than_equal": "超過允許上限",
               "greater_than": "未大於允許下限", "less_than": "未小於允許上限",
               "string_type": "需為文字", "list_type": "需為陣列", "dict_type": "需為物件",
               "int_parsing": "需為整數", "int_type": "需為整數", "int_from_float": "需為整數",
               "float_parsing": "需為數值", "float_type": "需為數值", "model_type": "需為人物資料物件"}
    errors = exc.errors(include_input=False, include_url=False)
    def reason(error):
        # Our own validators raise readable Chinese messages; keep them.
        if error["type"] == "value_error":
            return str(error.get("msg", "")).removeprefix("Value error, ") or "格式不符合要求"
        return reasons.get(error["type"], "格式不符合要求")
    descriptions = [f"{'.'.join(str(part) for part in error['loc']) or '資料根節點'}：{reason(error)}" for error in errors[:6]]
    if len(errors) > 6:
        descriptions.append(f"另有 {len(errors) - 6} 個欄位錯誤")
    return "；".join(descriptions)


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


def mock_persona(background: Background, seed: int, archetype: str, topic: str = "一般", custom: str = "", trait_overrides=None) -> Persona:
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
    for name, value in (trait_overrides or {}).items():
        setattr(traits, name, value)
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
    person_id = str(uuid5(NAMESPACE_URL, f"survey-persona:{seed}:{archetype}:{topic}:{custom}"))
    return Persona(id=person_id,
        name=name_for_id(person_id), archetype=archetype, background=background, traits=traits, behavior=behavior,
        topic_attributes=attributes, core_values=["符合生活情境", "保留預算彈性", "興趣與實用取得平衡"],
        narrative=f"{background.situation} {behavior.price_attitude}；{behavior.decision_style}。{custom}", seed=seed)


def persona_id(seed, archetype, topic, custom, namespace=""):
    """Same settings give the same ID; a namespace (one per generation click) keeps
    a second batch from overwriting the first."""
    key = f"survey-persona:{seed}:{archetype}:{topic}:{custom}" + (f":{namespace}" if namespace else "")
    return str(uuid5(NAMESPACE_URL, key))


def similarity(a: Persona, b: Persona) -> float:
    """Engineering check (0-1): personality, age, occupation, interests and lifestyle."""
    av, bv = list(a.traits.model_dump().values()), list(b.traits.model_dump().values())
    distance = math.sqrt(sum((x - y) ** 2 for x, y in zip(av, bv)) / len(av))
    background = abs(a.background.age - b.background.age) / 82
    job = 0 if a.background.occupation == b.background.occupation else 1
    ai, bi = set(a.background.interests), set(b.background.interests)
    interests = 1 - len(ai & bi) / len(ai | bi) if ai | bi else 0
    lifestyle = 0 if a.background.lifestyle == b.background.lifestyle else 1
    return round(1 - (.6 * distance + .1 * background + .1 * job + .1 * interests + .1 * lifestyle), 4)


def profile_summary(p: Persona) -> str:
    """Short description of an existing persona, sent so the model can avoid repeats."""
    b = p.background
    return f"{b.age}歲·{b.gender}·{b.occupation}·{'、'.join(b.interests[:3])}·{b.lifestyle[:30]}"


class PersonaGenerator:
    def __init__(self, provider):
        self.provider = provider

    def _generate_validated(self, operation, payload, instruction, model, constraints=None, prefill=None):
        stage = {"background": "基本背景", "choose_website_tier": "ONLYFRAME 方案"}.get(operation, "完整人物")
        request = dict(payload)
        instruction += "只輸出 schema 所定義的資料欄位。不要把 response_format、type=json_object 或 schema 定義放進結果。若提供 validation_feedback，請依指出的欄位問題修正後重新輸出完整資料；保留原 seed、情境與已確定背景。"
        last_error = ""
        for attempt in range(3):
            try:
                result = self.provider.generate(operation, request, instruction)
                data = result.data
                # This exact API formatting marker is not a persona attribute.
                # Keep every other unknown field subject to schema validation.
                if isinstance(data, dict) and data.get("type") == "json_object" and "type" not in model.model_fields:
                    data = {key: value for key, value in data.items() if key != "type"}
                    logger.info("Removed echoed JSON format marker operation=%s", operation)
                if prefill and isinstance(data, dict):
                    data = prefill(data)
                person = model.model_validate(data)
                violations = constraints(person) if constraints else []
                if not violations:
                    return person
                last_error = "；".join(violations)
            except ValidationError as exc:
                last_error = validation_details(exc)
            except ProviderError as exc:
                # Auth, transport and actual truncation retain their own messages.
                if exc.kind != "format":
                    raise
                last_error = "回傳資料不是可解析的 JSON 物件，請依 schema 輸出完整資料"
            logger.warning("Persona data validation failed operation=%s attempt=%s details=%s", operation, attempt + 1, last_error)
            request["validation_feedback"] = last_error
        raise AppError(f"AI {stage}資料經 3 次生成 / 修復仍未通過驗證：{last_error}。請調整人物描述或模型設定後重試；已保存的人物仍保留。")

    def generate_one(self, seed: int, archetype: str, topic: str, custom: str = "", background_overrides=None, trait_overrides=None,
                     choose_website_tier=False, id_namespace="", avoid=None) -> Persona:
        request = {"seed": seed, "archetype": archetype, "topic": topic, "custom": custom, "schema": Background.model_json_schema()}
        instruction = "建立一位虛擬成年人物的基本背景與生活情境。差異來自情境，避免職業、年齡刻板印象。依 schema 輸出背景 JSON。"
        if avoid:
            # The model ignores the seed number; recent profiles are what keeps a batch varied.
            request["avoid_profiles"] = list(avoid)[-20:]
            instruction += "avoid_profiles 是本批已建立的人物；新人物的年齡、職業、興趣與生活型態組合要明顯不同，但仍需合理。"
        background = self._generate_validated("background", request, instruction, Background)
        if background_overrides:
            data = {**background.model_dump(), **background_overrides}
            if "age" in background_overrides and "occupation" not in background_overrides and data["occupation"] == "退休人士" and data["age"] < 40 and "提早退休" not in custom:
                data.update(occupation="自由工作者", status="就業")
            if data["disposable_budget"] > data["monthly_income"]:
                raise AppError("指定可支配預算超過此背景所得，請調整所得或預算條件。")
            data["situation"] = f"{data['age']} 歲的{data['occupation']}，每月所得 {data['monthly_income']:.0f} 元、可支配預算 {data['disposable_budget']:.0f} 元；{data['lifestyle']}。"
            try:
                background = Background.model_validate(data)
            except ValidationError as exc:
                raise AppError("指定背景條件不合法：" + validation_details(exc)) from None
        def prefill(data):
            # The application owns the confirmed background and the requested traits.
            # Restoring them avoids rejecting (and paying for) a whole persona over a
            # reworded background sentence or a rounded trait.
            if data.get("background") not in (None, background.model_dump()):
                logger.info("Restored confirmed background in persona output seed=%s", seed)
            data = {**data, "background": background.model_dump()}
            if trait_overrides and isinstance(data.get("traits"), dict):
                data["traits"] = {**data["traits"], **trait_overrides}
            return data
        p = self._generate_validated("persona", {"seed": seed, "archetype": archetype, "topic": topic, "custom": custom,
            "background": background.model_dump(), "trait_overrides": trait_overrides or {}, "schema": Persona.model_json_schema()},
            "第二階段：根據已確定背景推導人格、價值觀及行為。background 由系統保存，可省略不輸出。traits 必須符合 trait_overrides。name 使用虛構的中文姓名，不要用人物編號。心理特徵 0–1，允許合理例外及猶豫；不代表人口分布。主題屬性放 topic_attributes。依 schema 輸出一位完整人物。", Persona, prefill=prefill)
        # Application owns identities and seed, not the model.
        p.id = persona_id(seed, archetype, topic, custom, id_namespace)
        p.seed, p.archetype = seed, archetype
        # Older generic personas have no assigned scheme; the model cannot invent one implicitly.
        p.onlyframe_tier, p.onlyframe_tier_reason = None, ""
        if choose_website_tier:
            from .models import WebsiteTierChoice
            choice = self._generate_validated("choose_website_tier", {
                "persona": p.model_dump(mode="json"), "schema": WebsiteTierChoice.model_json_schema(),
                "schemes": {"BASIC": "選擇框色，不加入文字、背景或貼飾",
                            "CUSTOM": "選擇框色及加入客製文字",
                            "PREMIUM": "選擇框色、客製文字、背景及貼飾"}},
                "依這位虛擬人物已確定的背景、興趣、偏好及使用需求，選擇一種 ONLYFRAME 方案。"
                "這是操作前的方案選擇，不得宣稱已體驗或提交。不得杜撰方案價格；不要為平均分配而選擇。"
                "依 schema 輸出 tier 和一句簡短 reason，方案之後固定沿用。", WebsiteTierChoice)
            p.onlyframe_tier, p.onlyframe_tier_reason = choice.tier, choice.reason
            p.id = persona_id(seed, archetype, topic, custom + ":onlyframe-tier-v1", id_namespace)
        return ensure_name(p)

    def generate_batch(self, count: int, seed: int, topic: str, ratios: dict[str, float], custom: str = "", on_persona=None,
                       choose_website_tier=False, id_namespace=""):
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
            p = self.generate_one(seed + i, archetype, topic, custom, choose_website_tier=choose_website_tier, id_namespace=id_namespace,
                                  avoid=[profile_summary(x) for x in result[-20:]])
            # Check nearby characters; UI analysis provides full pair inspection.
            for attempt in range(2):
                if not any(similarity(p, previous) > .97 for previous in result[-100:]):
                    break
                p = self.generate_one(seed + i + (attempt + 1) * 100003, archetype, topic, custom,
                                      choose_website_tier=choose_website_tier, id_namespace=id_namespace,
                                      avoid=[profile_summary(x) for x in result[-20:]])
            ensure_name(p, [previous.name for previous in result])
            result.append(p)
            if on_persona:
                on_persona(p, i + 1, count)
        return result
