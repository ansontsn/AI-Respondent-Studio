import json
import math
from collections import defaultdict

from .errors import AppError
from .models import TaskSpec, uid, now
from .analysis import canonical
from .validator import AnswerValidator


def quality_report(db, task_id=None):
    responses = db.responses(task_id)
    findings, rows, patterns = [], [], defaultdict(list)
    for r in responses:
        checked, issues, pages, status = AnswerValidator().validate(r.questionnaire_snapshot, r.persona_snapshot, r.answers)
        if pages != r.visited_pages:
            issues = list(issues)
            from .models import Issue
            issues.append(Issue(question_id="PATH", level="error", code="branch", message="保存的頁面路徑與答案計算結果不符"))
        for issue in issues:
            findings.append({"response_id": r.id, "persona_id": r.persona_id, "人物": r.persona_snapshot.name,
                             "題目ID": issue.question_id, "等級": issue.level, "問題": issue.message, "代碼": issue.code})
        qmap = {q.id: q for q in r.questionnaire_snapshot.questions}
        pattern = [(a.question_id, canonical(a.value)) for a in r.answers if a.question_id in qmap and not qmap[a.question_id].persona_field
                   and qmap[a.question_id].type.value not in {"short_text", "paragraph"} and a.validation != "skipped"]
        if len(pattern) >= 3:
            patterns[(r.task_id, json.dumps(pattern, sort_keys=True, ensure_ascii=False))].append(r)
        rows.append({"response_id": r.id, "人物": r.persona_snapshot.name, "原始狀態": r.status,
                     "明確錯誤": sum(i.level == "error" for i in issues), "人工檢查": sum(i.level == "review" for i in issues),
                     "格式修復次數": sum(x.get("kind") == "format" for x in r.repair_history),
                     "操作事實校正次數": sum(x.get("kind") == "observed_fact" for x in r.repair_history),
                     "有效回答": sum(a.valid for a in checked), "跳題略過": sum(a.validation == "skipped" for a in checked)})
    task_population = defaultdict(int)
    for r in responses:
        task_population[r.task_id] += 1
    for (pattern_task, _), people in patterns.items():
        if len(people) >= max(3, math.ceil(task_population[pattern_task] * .3)):
            for r in people:
                findings.append({"response_id": r.id, "persona_id": r.persona_id, "人物": r.persona_snapshot.name,
                    "題目ID": "PATTERN", "等級": "review", "問題": f"{len(people)} 位人物的非人口資料選項組合相同，請核對是否符合情境；不必刻意改成不同答案。", "代碼": "repetition"})
    flagged = {f["response_id"] for f in findings}
    for row in rows:
        row["需檢查"] = row["response_id"] in flagged
    items = db.rows("SELECT task_id,persona_id,status,error FROM task_items" + (" WHERE task_id=?" if task_id else ""), (task_id,) if task_id else ())
    return {"dataset": db.metadata(), "method": "格式 / 分流 / 已設定跨題與人設規則；重複模式為人工檢查，不是測量準確率。",
            "summary": {"回答數": len(responses), "需檢查回答": len(flagged), "明確錯誤紀錄": sum(f["等級"] == "error" for f in findings),
                        "重複模式紀錄": sum(f["代碼"] == "repetition" for f in findings), "失敗人物": sum(i["status"] in {"failed", "invalid"} for i in items)},
            "responses": rows, "findings": findings, "execution_failures": [i for i in items if i["status"] in {"failed", "invalid"}]}


def regenerate(db, response_ids, seed=None, reason="使用者選擇重新檢查回答"):
    selected = [r for r in db.responses() if r.id in response_ids]
    if len(selected) != len(set(response_ids)) or not selected:
        raise AppError("請選擇可找到的回答紀錄。")
    origin = selected[0]
    signatures = {(r.questionnaire_snapshot.model_dump_json(), r.provider_snapshot.model_dump_json(),
                   r.scenario.model_dump_json() if r.scenario else None, r.mode) for r in selected}
    if len(signatures) != 1 or len({r.task_id for r in selected}) != 1 or len({r.persona_id for r in selected}) != len(selected):
        raise AppError("一次重新生成需來自同一任務，使用同問卷、同模型、同情境，且人物不能重複。")
    original_spec = TaskSpec.model_validate_json(db.task(origin.task_id)["spec"])
    spec = TaskSpec(questionnaire=origin.questionnaire_snapshot, personas=[r.persona_snapshot for r in selected],
        provider=origin.provider_snapshot, scenario=origin.scenario, mode=origin.mode, seed=seed if seed is not None else origin.seed,
        variability=original_spec.variability, interval_seconds=original_spec.interval_seconds,
        budget_limit=original_spec.budget_limit, budget_warning_fraction=original_spec.budget_warning_fraction,
        supersedes={r.persona_id: r.id for r in selected},
        website_workflow=original_spec.website_workflow, compact_context=original_spec.compact_context,
        website_fact_bindings=original_spec.website_fact_bindings,
        website_survey=original_spec.website_survey.model_copy(update={"dry_run": True}) if original_spec.website_survey else None,
        website_tier_assignments={p.id: original_spec.website_tier_assignments[p.id] for p in [r.persona_snapshot for r in selected] if p.id in original_spec.website_tier_assignments})
    id = db.create_task(spec)
    if spec.website_workflow:
        # Answer repair reuses the saved experience instead of submitting again.
        for response in selected:
            checkpoint = {}
            if spec.website_survey:
                boundary = next(i for i,p in enumerate(spec.questionnaire.pages) if p.id == spec.website_survey.after_page_id)
                pages = spec.questionnaire.pages[:boundary + 1]
                ids_before = {q.id for p in pages for q in p.questions}
                answers_before = [a for a in response.answers if a.question_id in ids_before and a.validation != "skipped"]
                visited_before = [p for p in response.visited_pages if p in {page.id for page in pages}]
                values = {a.question_id: a.value for a in answers_before if a.value is not None}
                checkpoint.update(answers=[a.model_dump(mode="json") for a in answers_before], visited=visited_before,
                    next_page=spec.questionnaire.next_page(visited_before[-1], values) if visited_before else spec.questionnaire.pages[0].id)
            if response.website_run:
                checkpoint["website_run"] = response.website_run.model_dump(mode="json")
            if checkpoint:
                db.checkpoint(id, response.persona_id, checkpoint)
    with db.connect() as conn:
        conn.executemany("INSERT INTO quality_actions VALUES(?,?,?,?,?)", [(uid(), r.id, id, reason, now()) for r in selected])
    db.event(id, f"重新生成 {len(selected)} 份回答；保留原紀錄與人物快照")
    return id
