import json
from itertools import combinations

from .analysis import canonical, display_answer
from .errors import AppError
from .models import TaskSpec, now, uid
from .storage import dump
from .v2_models import Experiment
from .workflow import validated_plan


class ExperimentService:
    def __init__(self, db):
        self.db = db

    def create(self, experiment, interval_seconds=1., budget_limit=None, variability=.15):
        exp = Experiment.model_validate(experiment).model_copy(deep=True)
        if len(exp.cells) < 2 or len({c.label for c in exp.cells}) != len(exp.cells):
            raise AppError("實驗至少需要兩個不重複名稱的模型 / 情境。")
        if exp.kind == "scenario" and any(c.scenario is None for c in exp.cells):
            raise AppError("情境實驗的每一組都需完整情境設定。")
        if any(q.type.value == "unsupported" for q in exp.questionnaire.questions):
            raise AppError("問卷仍有不支援題型，請先完成確認。")
        specs = []
        for cell in exp.cells:
            spec = validated_plan(exp.questionnaire, exp.personas, cell.provider, scenario=cell.scenario,
                experiment_id=exp.id, mode=exp.mode, seed=exp.seed, interval_seconds=interval_seconds,
                variability=variability, budget_limit=budget_limit)
            if len({p.id for p in spec.personas}) != len(spec.personas):
                raise AppError("同一實驗的人物 ID 不可重複。")
            cell.task_id = uid()
            specs.append((cell.task_id, spec))
        # Persist all cells and the experiment atomically; no half-created experiment.
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for task_id, spec in specs:
                conn.execute("INSERT INTO tasks VALUES(?,?,?,?,?)", (task_id, dump(spec), "ready", now(), now()))
                conn.executemany("INSERT INTO task_items(task_id,persona_id) VALUES(?,?)", [(task_id, p.id) for p in spec.personas])
            conn.execute("INSERT INTO entities VALUES('experiment',?,?,?)", (exp.id, dump(exp), now()))
        return exp

    def summary(self, exp):
        records = []
        for cell in exp.cells:
            task = self.db.task(cell.task_id)
            items = self.db.rows("SELECT * FROM task_items WHERE task_id=?", (cell.task_id,))
            responses = self.db.responses(cell.task_id)
            history = [entry for r in responses for entry in r.repair_history]
            histories = [json.loads(i["checkpoint"]) for i in items if i["status"] == "failed"]
            history += [entry for cp in histories for entry in cp.get("repairs", [])]
            rejected = sum(x.get("kind") == "format" for x in history)
            successful_pages = sum(len(r.visited_pages) for r in responses) + sum(len(cp.get("visited", [])) for cp in histories)
            generated = successful_pages + rejected
            durations = [r.elapsed_seconds for r in responses if r.elapsed_seconds is not None]
            usage = self.db.rows("SELECT * FROM usage WHERE task_id=?", (cell.task_id,))
            known = [u for u in usage if u["cost"] is not None]
            records.append({"組別": cell.label, "服務商": cell.provider.provider, "模型": cell.provider.model,
                "狀態": task["status"], "預定人物": len(items), "保存回答": len(responses),
                "完成率": len(responses) / len(items) if items else 0,
                "需邏輯人工檢查比例": sum(r.status == "review" for r in responses) / len(responses) if responses else None,
                "明確錯誤回答": sum(r.status == "error" for r in responses), "失敗人物": sum(i["status"] == "failed" for i in items),
                "格式拒絕次數": rejected, "格式錯誤率": rejected / generated if generated else None,
                "平均人物耗時秒": sum(durations) / len(durations) if durations else None,
                "耗時有紀錄的人物": len(durations), "API請求": len(usage),
                "輸入Token": sum(u["input_tokens"] or 0 for u in usage) if usage else None,
                "輸出Token": sum(u["output_tokens"] or 0 for u in usage) if usage else None,
                "未知Token請求": sum(u["input_tokens"] is None or u["output_tokens"] is None for u in usage),
                "已知估算費用": sum(u["cost"] for u in known) if known else 0. if cell.provider.provider == "mock" else None,
                "未知費用請求": len(usage) - len(known), "幣別": cell.provider.rate_currency,
                "task_id": cell.task_id})
        return records

    def answer_rows(self, exp):
        rows = []
        for cell in exp.cells:
            for r in self.db.responses(cell.task_id):
                questions = {q.id: q for q in r.questionnaire_snapshot.questions}
                for a in r.answers:
                    rows.append({"組別": cell.label, "persona_id": r.persona_id, "人物": r.persona_snapshot.name,
                        "question_id": a.question_id, "題目": questions[a.question_id].title, "答案": a.value,
                        "答案文字": display_answer(questions[a.question_id], a.value, a.other_text), "其他補充文字": a.other_text, "決策依據": a.rationale,
                        "驗證": a.validation, "response_id": r.id, "情境": cell.scenario.name if cell.scenario else ""})
        return rows

    def differences(self, exp):
        rows = self.answer_rows(exp)
        lookup = {(r["組別"], r["persona_id"], r["question_id"]): r for r in rows}
        output = []
        for left, right in combinations(exp.cells, 2):
            for person in exp.personas:
                for q in exp.questionnaire.questions:
                    a = lookup.get((left.label, person.id, q.id))
                    b = lookup.get((right.label, person.id, q.id))
                    if not a or not b:
                        continue
                    applicable = a["驗證"] not in {"skipped", "error"} and b["驗證"] not in {"skipped", "error"}
                    output.append({"組別A": left.label, "組別B": right.label, "persona_id": person.id, "人物": person.name,
                        "question_id": q.id, "題目": q.title, "答案A": a["答案文字"], "答案B": b["答案文字"],
                        "可配對比較": applicable, "不同": canonical(a["答案"]) != canonical(b["答案"]),
                        "數值差B減A": b["答案"] - a["答案"] if applicable and type(a["答案"]) in {int,float} and type(b["答案"]) in {int,float} else None})
        return output

    def report(self, exp):
        return {"dataset": self.db.metadata(), "experiment": exp.model_dump(mode="json"), "summary": self.summary(exp),
                "task_settings": {cell.task_id: TaskSpec.model_validate_json(self.db.task(cell.task_id)["spec"]).model_dump(mode="json") for cell in exp.cells},
                "answers": self.answer_rows(exp), "paired_differences": self.differences(exp),
                "interpretation": "配對差異、完成率與一致性描述 AI 情境；不是對真人的預測準確率，也不是市場需求或因果效果。",
                "format_rate_definition": "格式被拒絕的頁面輸出 / （成功頁面輸出 + 格式拒絕輸出），包括可修復及最終失敗；API 認證 / 額度錯誤不計格式錯誤。"}
