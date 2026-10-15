from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def uid() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, validate_default=True)


class Traits(Model):
    price_sensitivity: float = Field(default=.5, ge=0, le=1)
    quality_focus: float = Field(default=.5, ge=0, le=1)
    aesthetics: float = Field(default=.5, ge=0, le=1)
    brand_focus: float = Field(default=.5, ge=0, le=1)
    risk_tolerance: float = Field(default=.5, ge=0, le=1)
    impulsiveness: float = Field(default=.5, ge=0, le=1)
    rationality: float = Field(default=.5, ge=0, le=1)
    social_influence: float = Field(default=.5, ge=0, le=1)
    personalization: float = Field(default=.5, ge=0, le=1)
    openness: float = Field(default=.5, ge=0, le=1)


class Background(Model):
    age: int = Field(ge=18, le=100)
    gender: str = "不指定"
    occupation: str
    status: str
    education: str
    monthly_income: float = Field(ge=0)
    disposable_budget: float = Field(ge=0)
    lifestyle: str
    interests: list[str]
    situation: str


class Behavior(Model):
    purchase_frequency: str
    spending_budget: float = Field(ge=0)
    platforms: list[str]
    usage_habits: str
    motivations: list[str]
    barriers: list[str]
    price_attitude: str
    quality_expectation: str
    decision_style: str


class Persona(Model):
    id: str = Field(default_factory=uid)
    name: str
    archetype: str = "AI 自動混合"
    background: Background
    traits: Traits
    behavior: Behavior
    topic_attributes: dict[str, Any] = Field(default_factory=dict)
    core_values: list[str]
    narrative: str
    seed: int = 42
    revision: int = Field(default=1, ge=1)
    onlyframe_tier: Literal["BASIC", "CUSTOM", "PREMIUM"] | None = None
    onlyframe_tier_reason: str = ""


class WebsiteTierChoice(Model):
    tier: Literal["BASIC", "CUSTOM", "PREMIUM"]
    reason: str = Field(min_length=1, max_length=500)


class QuestionType(StrEnum):
    SINGLE = "single"
    MULTIPLE = "multiple"
    DROPDOWN = "dropdown"
    SHORT = "short_text"
    PARAGRAPH = "paragraph"
    LINEAR = "linear_scale"
    LIKERT = "likert"
    GRID = "single_grid"
    CHECK_GRID = "checkbox_grid"
    UNSUPPORTED = "unsupported"


class Option(Model):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    label: str
    is_other: bool = False
    # Test-only utility coefficients; not population estimates.
    trait_weights: dict[str, float] = Field(default_factory=dict)


class Condition(Model):
    question_id: str
    operator: Literal["eq", "ne", "includes", "gt", "gte", "lt", "lte"] = "eq"
    value: Any

    def matches(self, answers: dict[str, Any]) -> bool:
        if self.question_id not in answers:
            return False
        actual = answers[self.question_id]
        if self.operator == "eq":
            return actual == self.value
        if self.operator == "ne":
            return actual != self.value
        if self.operator == "includes":
            return isinstance(actual, (list, str)) and self.value in actual
        try:
            if isinstance(actual, bool) or isinstance(self.value, bool):
                return False
            a, b = float(actual), float(self.value)
            return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[self.operator]
        except (ValueError, TypeError, KeyError):
            return False


class Binding(Model):
    container_selector: str = ""
    title: str = ""
    option_labels: dict[str, str] = Field(default_factory=dict)
    row_selectors: dict[str, str] = Field(default_factory=dict)


class Question(Model):
    id: str
    title: str
    type: QuestionType
    required: bool = True
    options: list[Option] = Field(default_factory=list)
    rows: list[Option] = Field(default_factory=list)
    scale_min: int = 1
    scale_max: int = 5
    min_choices: int = Field(default=0, ge=0)
    max_choices: int | None = Field(default=None, ge=1)
    max_length: int = Field(default=2000, ge=1)
    concept: str = ""
    trait: str = ""
    reverse: bool = False
    persona_field: str = ""
    display_if: list[Condition] = Field(default_factory=list)
    binding: Binding = Field(default_factory=Binding)
    notes: str = ""

    @field_validator("id")
    @classmethod
    def stable_id(cls, value: str) -> str:
        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
            raise ValueError("ID 限英數字、底線及連字號，長度 1–100")
        return value

    @model_validator(mode="after")
    def structure(self):
        other_options = [o for o in self.options if o.is_other]
        if other_options and (len(other_options) != 1 or self.type not in {QuestionType.SINGLE, QuestionType.MULTIPLE, QuestionType.UNSUPPORTED}):
            raise ValueError("其他文字選項僅支援單選 / 多選題，且每題最多一個")
        for seq in [self.options, self.rows]:
            if len({x.id for x in seq}) != len(seq):
                raise ValueError(f"{self.id} 選項或列 ID 重複")
            if len({x.label for x in seq}) != len(seq):
                raise ValueError(f"{self.id} 選項或列文字重複，無法可靠對應網頁")
        if self.type in {QuestionType.SINGLE, QuestionType.MULTIPLE, QuestionType.DROPDOWN,
                         QuestionType.GRID, QuestionType.CHECK_GRID} and not self.options:
            raise ValueError(f"{self.id} 必須提供選項")
        if self.type in {QuestionType.GRID, QuestionType.CHECK_GRID} and not self.rows:
            raise ValueError(f"{self.id} 方格必須提供列")
        if self.scale_max <= self.scale_min:
            raise ValueError("量表上界須大於下界")
        if self.max_choices is not None and self.max_choices < self.min_choices:
            raise ValueError("最大選取數不可小於最小選取數")
        if self.min_choices > len(self.options) and self.type in {QuestionType.MULTIPLE, QuestionType.CHECK_GRID}:
            raise ValueError("最小選取數大於可用選項")
        return self


class Route(Model):
    when: Condition
    target: str  # page id, or END


class Page(Model):
    id: str
    title: str
    questions: list[Question]
    routes: list[Route] = Field(default_factory=list)
    default_next: str | None = None


class ConsistencyRule(Model):
    left: str
    right: str
    relation: Literal["same", "reverse"] = "same"
    tolerance: float = Field(default=2, ge=0)
    explanation: str = "態度差異需要人工確認，未必矛盾"


class Questionnaire(Model):
    id: str = Field(default_factory=uid)
    title: str
    description: str = ""
    topic: str = "一般問卷"
    audience: str = "由使用者定義"
    purpose: Literal["test", "reference"] = "test"
    pages: list[Page]
    source_url: str = ""
    import_warnings: list[str] = Field(default_factory=list)
    confirmed: bool = False
    semantic_analysis: dict[str, Any] = Field(default_factory=dict)
    import_diagnostics: dict[str, Any] = Field(default_factory=dict)
    consistency_rules: list[ConsistencyRule] = Field(default_factory=list)
    revision: int = Field(default=1, ge=1)

    @property
    def questions(self) -> list[Question]:
        return [q for p in self.pages for q in p.questions]

    @model_validator(mode="after")
    def integrity(self):
        if not self.pages or not self.questions:
            raise ValueError("問卷至少需要一頁及一道題目")
        pages = [p.id for p in self.pages]
        if len(set(pages)) != len(pages) or "END" in pages:
            raise ValueError("頁面 ID 重複或使用保留字 END")
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("題目 ID 不可重複")
        seen: set[str] = set()
        for index, p in enumerate(self.pages):
            for q in p.questions:
                for c in q.display_if:
                    if c.question_id not in seen:
                        raise ValueError(f"{q.id} 顯示條件只能參照較早題目")
                seen.add(q.id)
            for r in p.routes:
                if r.when.question_id not in seen:
                    raise ValueError("分流條件參照未回答題目")
            for target in [r.target for r in p.routes] + ([p.default_next] if p.default_next else []):
                if target != "END" and (target not in pages or pages.index(target) <= index):
                    raise ValueError("分流僅允許向後頁面或 END，避免循環")
        for r in self.consistency_rules:
            if r.left not in ids or r.right not in ids:
                raise ValueError("一致性規則參照不存在的題目")
        return self

    def next_page(self, current: str, answers: dict[str, Any]) -> str:
        index = next(i for i, p in enumerate(self.pages) if p.id == current)
        p = self.pages[index]
        for r in p.routes:
            if r.when.matches(answers):
                return r.target
        return p.default_next or (self.pages[index + 1].id if index + 1 < len(self.pages) else "END")


class ProviderConfig(Model):
    id: str = Field(default_factory=uid)
    name: str = "Mock 測試"
    provider: Literal["mock", "openai", "deepseek", "gemini", "anthropic", "ollama", "compatible"] = "mock"
    base_url: str = ""
    model: str = "mock-v1"
    temperature: float | None = Field(default=.6, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=128, le=131072)
    timeout: float = Field(default=60, ge=1, le=600)
    retries: int = Field(default=2, ge=0, le=8)
    request_interval: float = Field(default=.5, ge=0, le=60)
    json_mode: bool = True
    token_parameter: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)
    rate_source: str = ""
    rate_currency: str = "USD"


class Answer(Model):
    question_id: str
    value: Any = None
    other_text: str = ""
    uncertain: bool = False
    rationale: str = ""
    valid: bool = False
    validation: Literal["passed", "review", "error", "skipped"] = "passed"


class Issue(Model):
    question_id: str
    level: Literal["review", "error"]
    code: str
    message: str
    resolution: str = "待處理"


class Scenario(Model):
    id: str = Field(default_factory=uid)
    name: str
    description: str
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self):
        import math
        if not self.name.strip():
            raise ValueError("情境名稱不可空白")
        for key in ["price", "customization"]:
            if key not in self.attributes:
                continue
            value = self.attributes[key]
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                raise ValueError("情境價格與客製化程度必須為有限非負數")
            if key == "customization" and value > 1:
                raise ValueError("客製化程度需在 0–1 之間")
        return self


class WebsiteWorkflow(Model):
    id: str = Field(default_factory=uid)
    name: str = "ONLYFRAME CUSTOM 操作流程"
    adapter: Literal["onlyframe_custom_v1", "onlyframe_tiers_v2"] = "onlyframe_tiers_v2"
    tier: Literal["BASIC", "CUSTOM", "PREMIUM"] = "CUSTOM"
    url: str = "https://www.onlyframe.online/"
    mode: Literal["preview", "submit"] = "preview"
    authorized_test: bool = False
    allowlist: list[str] = Field(default_factory=lambda: ["https://www.onlyframe.online/"])
    plan_mode: Literal["recorded", "persona_rules"] = "persona_rules"
    design_text: str = Field(default="", max_length=40)
    contact_name: str = Field(default="AI 測試", min_length=1, max_length=60)
    use_persona_name: bool = True
    contact_email: str = "ai-test@example.invalid"
    # Exact REST endpoint; never a wildcard host or a provider API key.
    submission_endpoint: str = ""
    timeout_seconds: int = Field(default=30, ge=3, le=180)
    require_server_receipt: bool = False


class WebsitePlan(Model):
    tier: Literal["BASIC", "CUSTOM", "PREMIUM"] = "CUSTOM"
    frame_color: str = "冰川冷藍"
    font: str = "韓系潮流"
    text: str = Field(default="MUSIC 2026", max_length=40)
    text_color: Literal["曜石黑"] = "曜石黑"
    y_mm: float = Field(default=106, ge=100, le=110)
    background: str = ""
    sticker: str = ""


class WebsiteRun(Model):
    id: str = Field(default_factory=uid)
    workflow_id: str
    persona_id: str
    persona_name: str = ""
    contact_name: str = ""
    url: str
    plan: WebsitePlan
    mode: Literal["preview", "submit"]
    status: Literal["running", "preview_completed", "local_saved", "server_confirmed", "failed", "blocked", "unknown", "interrupted"] = "running"
    created_at: str = Field(default_factory=now)
    elapsed_seconds: float = 0
    message: str = ""
    steps: list[str] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)
    receipt_code: str = ""
    receipt_id: str = ""
    receipt_file: str = ""
    blocked_writes: int = 0
    submission_started: bool = False
    insert_sent: bool | None = None
    network_events: list[dict[str, Any]] = Field(default_factory=list)
    receipt_source: str = ""
    dataset_source: Literal["ai_website_test"] = "ai_website_test"


class Response(Model):
    id: str = Field(default_factory=uid)
    task_id: str
    persona_id: str
    questionnaire_id: str
    persona_snapshot: Persona
    questionnaire_snapshot: Questionnaire
    provider_snapshot: ProviderConfig
    answers: list[Answer]
    issues: list[Issue] = Field(default_factory=list)
    visited_pages: list[str] = Field(default_factory=list)
    mode: str = "natural"
    seed: int = 42
    status: Literal["passed", "review", "error"] = "passed"
    created_at: str = Field(default_factory=now)
    repair_history: list[dict[str, Any]] = Field(default_factory=list)
    scenario: Scenario | None = None
    elapsed_seconds: float | None = Field(default=None, ge=0)
    supersedes_id: str | None = None
    website_run: WebsiteRun | None = None
    form_result: dict[str, Any] | None = None
    dataset_kind: Literal["simulation"] = "simulation"


class FormTarget(Model):
    id: str = Field(default_factory=uid)
    name: str
    url: str
    questionnaire_id: str
    kind: Literal["local", "google", "custom"] = "local"
    purpose: Literal["test", "research"] = "test"
    authorized: bool = False
    success_selector: str = ""
    success_text: str = ""
    next_text: str = "下一頁"
    submit_text: str = "提交"


class WebsiteSurveyFlow(Model):
    after_page_id: str
    tier_question_id: str
    tier_options: dict[str, Literal["BASIC", "CUSTOM", "PREMIUM"]]
    name_question_id: str = ""
    form_target: FormTarget
    form_allowlist: list[str] = Field(default_factory=list)
    dry_run: bool = True
    fact_option_maps: dict[str, dict[str, str]] = Field(default_factory=dict)


class TaskSpec(Model):
    questionnaire: Questionnaire
    personas: list[Persona]
    provider: ProviderConfig
    mode: Literal["consistent", "natural", "custom"] = "natural"
    variability: float = Field(default=.15, ge=0, le=.5)
    seed: int = 42
    interval_seconds: float = Field(default=1, ge=0, le=300)
    scenario: Scenario | None = None
    experiment_id: str | None = None
    budget_limit: float | None = Field(default=None, ge=0)
    budget_warning_fraction: float = Field(default=.8, gt=0, le=1)
    supersedes: dict[str, str] = Field(default_factory=dict)
    website_workflow: WebsiteWorkflow | None = None
    compact_context: bool = False
    website_fact_bindings: dict[str, Literal["tier", "frame_color", "features", "storage", "receipt_code", "submitted"]] = Field(default_factory=dict)
    website_tier_assignments: dict[str, Literal["BASIC", "CUSTOM", "PREMIUM"]] = Field(default_factory=dict)
    website_survey: WebsiteSurveyFlow | None = None
    form_target: FormTarget | None = None
    form_allowlist: list[str] = Field(default_factory=list)
    form_dry_run: bool = True
    source_response_ids: dict[str, str] = Field(default_factory=dict)
    # Personas answered at the same time (website flows and budget limits stay at 1).
    concurrency: int = Field(default=1, ge=1, le=5)

    @field_validator("questionnaire", "personas", "provider", "scenario", "website_workflow", "website_survey", "form_target", mode="before")
    @classmethod
    def reload_safe_snapshots(cls, value):
        # Streamlit may keep cached objects from a previous module load.
        # Revalidate plain snapshots instead of relying on Python class identity.
        if isinstance(value, list):
            return [item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value]
        return value.model_dump(mode="json") if isinstance(value, BaseModel) else value
