from __future__ import annotations

from pydantic import ValidationError

from .errors import AppError, ProviderError
from .models import Answer, Response
from .validator import AnswerValidator, visible, value_errors


class Interrupted(AppError):
    pass


class AnswerEngine:
    def __init__(self, provider):
        self.provider = provider
        self.validator = AnswerValidator()

    def run(self, task_id, spec, persona, checkpoint=None, on_checkpoint=None, should_continue=None):
        checkpoint = checkpoint or {}
        answers = [Answer.model_validate(x) for x in checkpoint.get("answers", [])]
        current = checkpoint.get("next_page", spec.questionnaire.pages[0].id)
        repairs = checkpoint.get("repairs", [])
        visited = checkpoint.get("visited", [])
        values = {a.question_id: a.value for a in answers if a.value is not None}
        questionnaire = spec.questionnaire
        while current != "END":
            if should_continue and not should_continue():
                raise Interrupted("任務已暫停或停止，已保存完成頁面。")
            page = next(p for p in questionnaire.pages if p.id == current)
            payload = {"persona": persona.model_dump(mode="json"), "questionnaire": questionnaire.model_dump(mode="json"),
                       "page": page.model_dump(mode="json"), "previous_answers": [a.model_dump() for a in answers],
                       "mode": spec.mode, "variability": spec.variability, "seed": spec.seed,
                       "output_example": {"answers": [{"question_id": "穩定題目ID", "value": "選項ID / 整數 / 文字 / 多選陣列 / 方格列ID物件", "rationale": "一句模擬決策依據"}]}}
            instruction = "以同一人物的完整背景及先前回答回答當前頁。先理解整份問卷的主題、測量概念、反向題及條件。人格保持穩定，允許合理的中立與不確定態度。喜歡客製化不等於願意付高價。只使用選項ID；量表用整數；方格用列ID映射。根據 display_if 判斷是否適用；非適用題省略。輸出 output_example 格式，不得新增題目ID。每題一句決策依據，不需內部推理步驟。"
            last_error = ""
            for attempt in range(3):
                try:
                    result = self.provider.generate("answer_page" if attempt == 0 else "repair_page", payload, instruction)
                    raw = result.data.get("answers")
                    if not isinstance(raw, list):
                        raise ProviderError("AI 回傳缺少 answers 陣列。")
                    incoming = [Answer.model_validate(x) for x in raw]
                    ids = [a.question_id for a in incoming]
                    if len(set(ids)) != len(ids) or set(ids) - {q.id for q in page.questions}:
                        raise ProviderError("AI 回傳未知或重複題目 ID。")
                    amap = {a.question_id: a for a in incoming}
                    page_answers, local_values, errors = [], dict(values), []
                    for q in page.questions:
                        if not visible(q, local_values):
                            continue
                        a = amap.get(q.id, Answer(question_id=q.id))
                        errors.extend(f"{q.id}: {e}" for e in value_errors(q, a.value))
                        if q.persona_field:
                            from .mock_ai import field_value
                            from .models import QuestionType
                            field = field_value(persona, q.persona_field)
                            if q.type in {QuestionType.SHORT, QuestionType.PARAGRAPH} and field is not None and a.value != str(field):
                                errors.append(f"{q.id}: 答案與人物欄位 {q.persona_field} 不一致")
                        if a.value is not None:
                            local_values[q.id] = a.value
                        page_answers.append(a)
                    if errors:
                        raise ProviderError("；".join(errors))
                    values = local_values
                    answers.extend(page_answers)
                    break
                except (ValidationError, ProviderError) as exc:
                    last_error = str(exc) if isinstance(exc, ProviderError) else "AI 回答結構不符合資料模型"
                    repairs.append({"page_id": page.id, "attempt": attempt + 1, "issue": last_error,
                                    "resolution": "重新生成當前頁" if attempt < 2 else "失敗，保留之前頁面"})
                    payload["validation_feedback"] = last_error
                    if attempt == 2:
                        raise AppError(f"頁面 {page.title} 回答未通過驗證：{last_error}") from exc
            visited.append(current)
            current = questionnaire.next_page(current, values)
            if on_checkpoint:
                on_checkpoint({"answers": [a.model_dump() for a in answers], "next_page": current,
                               "repairs": repairs, "visited": visited})
        checked, issues, actual_pages, status = self.validator.validate(questionnaire, persona, answers)
        return Response(task_id=task_id, persona_id=persona.id, questionnaire_id=questionnaire.id,
                        persona_snapshot=persona, questionnaire_snapshot=questionnaire, provider_snapshot=spec.provider,
                        answers=checked, issues=issues, visited_pages=actual_pages, mode=spec.mode,
                        seed=spec.seed, status=status, repair_history=repairs)
