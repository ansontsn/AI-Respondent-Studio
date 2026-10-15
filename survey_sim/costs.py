import json
import math

from .errors import AppError


class BudgetExceeded(AppError):
    pass


def has_rates(c):
    return c.input_price_per_million is not None and c.output_price_per_million is not None and bool(c.rate_source.strip())


def request_estimate(config, payload, system=""):
    if config.provider == "mock":
        return {"low": 0., "high": 0., "currency": config.rate_currency, "method": "Mock 無 API 費用"}
    if not has_rates(config):
        return {"low": None, "high": None, "currency": config.rate_currency, "method": "缺少可查證費率，無法估價"}
    text = json.dumps(payload, ensure_ascii=False) + system
    # A deliberately conservative planning bound; never called an account hard cap.
    lo_input = max(1, len(text) // 4)
    hi_input = len(text.encode("utf-8")) + 256
    inp, out = config.input_price_per_million, config.output_price_per_million
    return {"low": (lo_input * inp + min(512, config.max_tokens) * out) / 1e6,
            "high": (hi_input * inp + config.max_tokens * out) / 1e6, "currency": config.rate_currency,
            "method": "文字長度與最大輸出 Token 規劃區間；不是帳單或絕對費用保證"}


def task_estimate(spec):
    c = spec.provider
    low = high = 0.
    from .engine import answer_context
    for persona in spec.personas:
        # Worst-path pages, built like the real request; prior answers get an allowance.
        for page in spec.questionnaire.pages:
            payload = {**answer_context(persona, spec.questionnaire, page, []),
                       "scenario": spec.scenario.model_dump() if spec.scenario else None,
                       "prior_answer_allowance": "x" * (len(spec.questionnaire.questions) * 60)}
            estimate = request_estimate(c, payload, "問卷作答與 JSON 格式說明" * 30)
            if estimate["high"] is None:
                return estimate
            low += estimate["low"]
            high += estimate["high"] * 3 * (c.retries + 1)
    return {"low": low, "high": high, "currency": c.rate_currency,
            "method": "所有頁面；上界額外保留 2 次格式修復及有限網路重試。實際費用依服務回報。"}


def usage_summary(db, task_id):
    records = db.rows("SELECT * FROM usage WHERE task_id=?", (task_id,))
    return {"input_tokens": sum(x["input_tokens"] or 0 for x in records),
            "output_tokens": sum(x["output_tokens"] or 0 for x in records),
            "known_cost": sum(x["cost"] or 0 for x in records), "requests": len(records),
            "unknown_cost_requests": sum(x["cost"] is None and x["status"] in {"success", "invalid_response", "transport_error"} for x in records),
            "unknown_token_requests": sum(x["input_tokens"] is None or x["output_tokens"] is None for x in records)}


class BudgetedProvider:
    def __init__(self, provider, db, task_id):
        self.provider, self.db, self.task_id = provider, db, task_id
        self.config = provider.config
        self.warned = False
        self.native_hook = hasattr(provider, "before_request")
        if self.native_hook:
            provider.before_request = self.guard

    def guard(self, operation, payload, system):
        from .models import TaskSpec
        spec = TaskSpec.model_validate_json(self.db.task(self.task_id)["spec"])
        limit = spec.budget_limit
        if limit is None or self.config.provider == "mock":
            return
        if not has_rates(self.config):
            raise BudgetExceeded("任務有預算上限，但模型缺少可靠費率；已暫停，請設定費率或移除預算上限。")
        usage = usage_summary(self.db, self.task_id)
        if usage["unknown_cost_requests"]:
            raise BudgetExceeded("已有無法估算費用的請求，無法保證剩餘預算；已暫停，請查核服務端用量。")
        projected = request_estimate(self.config, payload, system)["high"]
        if usage["known_cost"] + projected > limit:
            raise BudgetExceeded(f"剩餘預算不足以容納下一次請求（已知費用 {usage['known_cost']:.6f}，本次保留 {projected:.6f} {self.config.rate_currency}）；已暫停，完成結果與頁面已保存。")
        if not self.warned and usage["known_cost"] >= limit * spec.budget_warning_fraction:
            self.db.event(self.task_id, "已達設定的預算警戒比例", "warning")
            self.warned = True

    def generate(self, operation, payload, system):
        if not self.native_hook:
            self.guard(operation, payload, system)
        return self.provider.generate(operation, payload, system)
