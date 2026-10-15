from typing import Literal
import math

from pydantic import Field, model_validator

from .models import Model, Persona, Questionnaire, ProviderConfig, Scenario, FormTarget, uid, now, Traits


class AgeBand(Model):
    minimum: int = Field(ge=18, le=100)
    maximum: int = Field(ge=18, le=100)
    weight: float = Field(default=1, ge=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.maximum < self.minimum:
            raise ValueError("年齡區間上界不可小於下界")
        if not math.isfinite(self.weight):
            raise ValueError("年齡比例必須是有限數值")
        return self


class PersonaConditions(Model):
    age_bands: list[AgeBand] = Field(default_factory=list)
    genders: dict[str, float] = Field(default_factory=dict)
    educations: dict[str, float] = Field(default_factory=dict)
    occupations: dict[str, float] = Field(default_factory=dict)
    income_range: tuple[float, float] | None = None
    budget_range: tuple[float, float] | None = None
    interests: list[str] = Field(default_factory=list)
    core_values: list[str] = Field(default_factory=list)
    trait_ranges: dict[str, tuple[float, float]] = Field(default_factory=dict)
    familiarity_range: tuple[float, float] = (0, 1)
    custom_background: str = ""

    @model_validator(mode="after")
    def coherent(self):
        for distribution in [self.genders, self.educations, self.occupations]:
            if distribution and (any(not math.isfinite(v) or v < 0 for v in distribution.values()) or sum(distribution.values()) <= 0):
                raise ValueError("條件比例需為有限非負數，且至少一項大於零")
        if self.age_bands and not any(x.weight > 0 for x in self.age_bands):
            raise ValueError("年齡分布需有正比例")
        for bounds in [self.income_range, self.budget_range]:
            if bounds and (not all(math.isfinite(v) for v in bounds) or not 0 <= bounds[0] <= bounds[1]):
                raise ValueError("所得 / 預算區間需 0 ≤ 下界 ≤ 上界")
        if self.income_range and self.budget_range and self.budget_range[0] > self.income_range[1]:
            raise ValueError("可支配預算的下界超過所有可能所得，請調整條件")
        for key, bounds in self.trait_ranges.items():
            if key not in Traits.model_fields or not 0 <= bounds[0] <= bounds[1] <= 1:
                raise ValueError("人格條件需為有效屬性及 0–1 區間")
        if not 0 <= self.familiarity_range[0] <= self.familiarity_range[1] <= 1:
            raise ValueError("產品熟悉程度需為 0–1 區間")
        return self


class ExperimentCell(Model):
    label: str
    provider: ProviderConfig
    scenario: Scenario | None = None
    task_id: str = ""


class Experiment(Model):
    id: str = Field(default_factory=uid)
    name: str
    kind: Literal["model", "scenario"]
    questionnaire: Questionnaire
    personas: list[Persona]
    cells: list[ExperimentCell]
    seed: int = 42
    mode: Literal["consistent", "natural", "custom"] = "natural"
    created_at: str = Field(default_factory=now)
    source: str = "AI 虛擬人物與問卷情境模擬"


class PersonaGroup(Model):
    id: str = Field(default_factory=uid)
    name: str = Field(min_length=1, max_length=100)
    persona_ids: list[str]


class WorkbenchSpec(Model):
    questionnaire: Questionnaire | None = None
    provider: ProviderConfig
    personas: list[Persona] = Field(default_factory=list)
    generate_count: int = Field(default=0, ge=0, le=10000)
    conditions: PersonaConditions = Field(default_factory=PersonaConditions)
    ratios: dict[str, float] = Field(default_factory=lambda: {"AI 自動混合": 1.})
    topic: str = "一般問卷"
    seed: int = Field(default=42, ge=0, le=2000000000)
    mode: Literal["personas", "answers", "dry_run", "submit"] = "answers"
    answer_mode: Literal["natural", "consistent", "custom"] = "natural"
    variability: float = Field(default=.15, ge=0, le=.5)
    interval_seconds: float = Field(default=1, ge=0, le=300)
    form_target: FormTarget | None = None
    form_allowlist: list[str] = Field(default_factory=list)
    response_ids: list[str] = Field(default_factory=list)
    submission_confirmed: bool = False
    # Personas generated / answered / filled at the same time.
    concurrency: int = Field(default=1, ge=1, le=5)

    @model_validator(mode="after")
    def executable(self):
        if self.generate_count and (not self.ratios or any(not math.isfinite(v) or v < 0 for v in self.ratios.values()) or sum(self.ratios.values()) <= 0):
            raise ValueError("人物比例需為有限非負數且總和大於零")
        if not self.generate_count and not self.personas and not self.response_ids:
            raise ValueError("請選取人物、設定生成人數或選取既有回答")
        if len({p.id for p in self.personas}) != len(self.personas):
            raise ValueError("人物不可重複選取")
        if self.response_ids and (self.generate_count or self.personas or self.mode not in {"dry_run", "submit"}):
            raise ValueError("既有回答填表不能同時建立人物或生成答案")
        if self.mode != "personas" and not self.response_ids and (not self.questionnaire or not self.questionnaire.confirmed):
            raise ValueError("請先核對並確認問卷題目及跳題")
        if self.mode in {"dry_run", "submit"} and not self.form_target:
            raise ValueError("請指定測試表單")
        if self.mode == "submit" and (not self.submission_confirmed or not self.form_target.authorized or self.form_target.purpose != "test"):
            raise ValueError("真正提交需要已授權測試表單及本次明確確認")
        return self
