from __future__ import annotations

from collections import Counter
from typing import Any

from .models import Answer, Issue, Persona, Question, Questionnaire, QuestionType
from .mock_ai import field_value


def visible(q: Question, values: dict) -> bool:
    return all(condition.matches(values) for condition in q.display_if)


def value_errors(q: Question, value: Any) -> list[str]:
    if value is None or value == "" or value == [] or value == {}:
        return ["必填題沒有答案"] if q.required else []
    opts = {x.id for x in q.options}
    def check_multiple(v):
        if not isinstance(v, list) or any(not isinstance(x, str) or x not in opts for x in v):
            return ["多選答案需為有效選項 ID 的陣列"]
        if len(set(v)) != len(v):
            return ["多選答案出現重複選項"]
        if len(v) < max(q.min_choices, 1 if q.required else 0) or (q.max_choices is not None and len(v) > q.max_choices):
            return ["多選答案未符合最小 / 最大選取數"]
        return []
    if q.type in {QuestionType.SINGLE, QuestionType.DROPDOWN}:
        return [] if isinstance(value, str) and value in opts else ["答案不是有效選項 ID"]
    if q.type == QuestionType.MULTIPLE:
        return check_multiple(value)
    if q.type in {QuestionType.LINEAR, QuestionType.LIKERT}:
        return [] if type(value) is int and q.scale_min <= value <= q.scale_max else ["量表答案需為範圍內的整數"]
    if q.type in {QuestionType.SHORT, QuestionType.PARAGRAPH}:
        return [] if isinstance(value, str) and len(value) <= q.max_length else ["文字答案格式或長度不合法"]
    if q.type in {QuestionType.GRID, QuestionType.CHECK_GRID}:
        if not isinstance(value, dict) or set(value) - {r.id for r in q.rows}:
            return ["方格答案需使用有效列 ID 的物件"]
        result = []
        for row in q.rows:
            v = value.get(row.id)
            if v is None or v == [] or v == "":
                if q.required:
                    result.append(f"方格列 {row.label} 未填")
                continue
            if q.type == QuestionType.GRID:
                if not isinstance(v, str) or v not in opts:
                    result.append(f"方格列 {row.label} 選項無效")
            else:
                result.extend(f"{row.label}: {x}" for x in check_multiple(v))
        return result
    return ["此特殊題型尚未支援，請人工修正問卷"]


class AnswerValidator:
    def validate(self, questionnaire: Questionnaire, persona: Persona, answers: list[Answer]):
        issues: list[Issue] = []
        counts = Counter(a.question_id for a in answers)
        ids = {q.id for q in questionnaire.questions}
        for id, count in counts.items():
            if id not in ids or count > 1:
                issues.append(Issue(question_id=id, level="error", code="id", message="未知或重複的題目 ID"))
        answer_map = {a.question_id: a for a in answers}
        values, expected, visited = {}, [], []
        current = questionnaire.pages[0].id
        while current != "END":
            page = next(p for p in questionnaire.pages if p.id == current)
            visited.append(current)
            for q in page.questions:
                if not visible(q, values):
                    continue
                expected.append(q.id)
                a = answer_map.get(q.id)
                if a is None:
                    if q.required:
                        issues.append(Issue(question_id=q.id, level="error", code="missing", message="缺少必填題"))
                    continue
                for error in value_errors(q, a.value):
                    issues.append(Issue(question_id=q.id, level="error", code="format", message=error))
                if a.value is not None:
                    values[q.id] = a.value
                if a.value is not None and not a.rationale.strip():
                    issues.append(Issue(question_id=q.id, level="review", code="reason", message="缺少簡短決策依據"))
                if q.persona_field and a.value is not None:
                    actual = field_value(persona, q.persona_field)
                    if actual is not None and q.type in {QuestionType.SHORT, QuestionType.PARAGRAPH} and str(actual) != a.value:
                        issues.append(Issue(question_id=q.id, level="error", code="persona", message="答案與已註記的人物欄位不一致"))
                if q.trait in type(persona.traits).model_fields and q.type in {QuestionType.LINEAR, QuestionType.LIKERT} and type(a.value) is int:
                    expected_score = getattr(persona.traits, q.trait)
                    observed = (a.value - q.scale_min) / (q.scale_max - q.scale_min)
                    if q.reverse:
                        observed = 1 - observed
                    if abs(observed - expected_score) > .6:
                        issues.append(Issue(question_id=q.id, level="review", code="preference", message="核心偏好出現較大差異，請檢查理由與情境"))
            current = questionnaire.next_page(current, values)
        for a in answers:
            if a.question_id in ids and a.question_id not in expected and a.value is not None:
                issues.append(Issue(question_id=a.question_id, level="error", code="branch", message="回答了目前分流不應出現的題目"))
        for rule in questionnaire.consistency_rules:
            l, r = values.get(rule.left), values.get(rule.right)
            if type(l) not in {int, float} or type(r) not in {int, float}:
                continue
            rq = next(q for q in questionnaire.questions if q.id == rule.right)
            adjusted = rq.scale_min + rq.scale_max - r if rule.relation == "reverse" else r
            if abs(l - adjusted) > rule.tolerance:
                issues.append(Issue(question_id=rule.right, level="review", code="relationship", message=rule.explanation))
        if persona.behavior.spending_budget > persona.background.disposable_budget:
            issues.append(Issue(question_id="PERSONA", level="review", code="budget", message="單次消費預算超過每月可支配金額；可能使用儲蓄，請人工確認"))
        checked = []
        for q in questionnaire.questions:
            original = answer_map.get(q.id, Answer(question_id=q.id))
            a = original.model_copy(deep=True)
            own = [i for i in issues if i.question_id == q.id]
            a.validation = "error" if any(i.level == "error" for i in own) else "review" if own else "passed" if q.id in expected else "skipped"
            a.valid = a.validation in {"passed", "review"}
            checked.append(a)
        status = "error" if any(i.level == "error" for i in issues) else "review" if issues else "passed"
        return checked, issues, visited, status
