"""Persist preparation; reuse the existing answer worker and form submission guard."""
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import NAMESPACE_URL, uuid5

from .batch import PAUSED
from .errors import AppError, ProviderError
from .models import Persona, Response, TaskSpec, now, uid
from .storage import dump
from .v2_models import WorkbenchSpec


class WorkbenchService:
    def __init__(self, db, secrets):
        self.db, self.secrets = db, secrets

    def job(self, job_id):
        rows = self.db.rows("SELECT * FROM workbench_jobs WHERE id=?", (job_id,))
        if not rows:
            raise AppError("找不到工作台任務")
        return rows[0]

    def create(self, spec):
        from .automation import check_policy
        spec = WorkbenchSpec.model_validate(spec)
        sources = self._sources(spec)
        if spec.questionnaire and spec.mode != "personas":
            if any(q.type.value == "unsupported" for q in spec.questionnaire.questions) or spec.questionnaire.import_diagnostics.get("unresolved_routes"):
                raise AppError("問卷有不支援題型或未處理的跳題，請先修正")
        if spec.form_target:
            candidates = sources or [Response(task_id="preflight", persona_id="preflight", questionnaire_id=spec.questionnaire.id,
                questionnaire_snapshot=spec.questionnaire, persona_snapshot=(spec.personas or [self._prototype()])[0],
                provider_snapshot=spec.provider, answers=[])]
            for response in candidates:
                check_policy(spec.form_target, response, spec.form_allowlist, spec.mode != "submit")
            if spec.form_target.kind == "local":
                self._check_local_versions(spec, sources)
        job_id = uid()
        self.db.execute("INSERT INTO workbench_jobs(id,spec,status,phase,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (job_id, dump(spec), "pending", "prepare", now(), now()))
        return job_id

    def _check_local_versions(self, spec, sources):
        """The local form serves the saved questionnaire; stop before any AI call if it differs."""
        snapshots = [r.questionnaire_snapshot for r in sources] or [spec.questionnaire]
        for snapshot in snapshots:
            current = self.db.get("questionnaire", snapshot.id)
            if current is None and not sources:
                continue  # saved by the job before answering
            if current is None or current.model_dump() != snapshot.model_dump():
                raise AppError("本機測試表單使用「問卷管理」中保存的版本，與本次問卷不同（例如尚未保存確認或已修改）。"
                               "請在問卷管理確認目前版本後再開始；尚未呼叫 AI。")

    def _prototype(self):
        from .personas import mock_background, mock_persona
        return mock_persona(mock_background(0), 0, "AI 自動混合")

    def _sources(self, spec):
        if not spec.response_ids:
            return []
        rows = []
        for response_id in dict.fromkeys(spec.response_ids):
            found = self.db.rows("SELECT body FROM responses WHERE id=?", (response_id,))
            if not found:
                raise AppError("選取的回答不存在")
            response = Response.model_validate_json(found[0]["body"])
            from .validator import AnswerValidator
            _, _, pages, status = AnswerValidator().validate(response.questionnaire_snapshot, response.persona_snapshot, response.answers)
            if status == "error" or pages != response.visited_pages:
                raise AppError("選取的回答未通過格式或跳題驗證，不能批次填表")
            rows.append(response)
        return rows

    def start(self, job_id, runner):
        with runner.lock:
            if runner.thread and runner.thread.is_alive():
                raise AppError("已有批次執行中，請先暫停或取消")
            with self.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                job = conn.execute("SELECT status FROM workbench_jobs WHERE id=?", (job_id,)).fetchone()
                if not job or job["status"] not in {"pending", "paused", "failed", "completed_with_errors"}:
                    raise AppError("此任務不能重新開始；已完成工作不會重跑")
                conn.execute("UPDATE workbench_jobs SET status='running',error='',updated_at=? WHERE id=?", (now(), job_id))
            runner.active_job = job_id
            runner.thread = threading.Thread(target=self.run, args=(job_id, runner), daemon=True, name="survey-workbench")
            runner.thread.start()

    def _pause_for_provider(self, job_id, reason):
        message = f"AI 服務錯誤，已暫停整批：{reason}。修正金鑰、額度或模型設定後按「繼續本批次」；已完成結果保留。"
        self.db.execute("UPDATE workbench_jobs SET status='paused',error=?,updated_at=? WHERE id=?", (message, now(), job_id))
        self.db.event(job_id, message, "error")

    def _checkpoint(self, job_id, checkpoint, phase):
        self.db.execute("UPDATE workbench_jobs SET checkpoint=?,phase=?,updated_at=? WHERE id=?", (dump(checkpoint), phase, now(), job_id))

    def control(self, job_id, action):
        if action not in {"paused", "cancelled"}:
            raise AppError("不支援的控制動作")
        status = self.job(job_id)["status"]
        # A finished job cannot be "paused"; only running / queued work can be.
        if status in {"completed", "cancelled"} or (action == "paused" and status not in {"running", "pending"}):
            return
        self.db.execute("UPDATE workbench_jobs SET status=?,updated_at=? WHERE id=?", (action, now(), job_id))
        for task_id in json.loads(self.job(job_id)["checkpoint"]).get("task_ids", []):
            if self.db.task(task_id)["status"] not in {"completed", "completed_with_errors"}:
                self.db.task_status(task_id, action)
                if action == "cancelled":
                    self.db.execute("UPDATE task_items SET status='cancelled' WHERE task_id=? AND status='pending'", (task_id,))

    def retry(self, job_id):
        job = self.job(job_id)
        if job["status"] not in {"failed", "completed_with_errors", "paused"}:
            raise AppError("請先暫停，或選取有失敗項目的任務")
        cp = json.loads(job["checkpoint"])
        for item in cp.get("generation", []):
            if item["status"] == "running":
                item["status"] = "pending"
        for item in cp.get("generation", []):
            if item["status"] == "failed":
                item.update(status="pending", error="")
        for task_id in cp.get("task_ids", []):
            self.db.retry_failed(task_id)
        self._checkpoint(job_id, cp, job["phase"])
        self.db.execute("UPDATE workbench_jobs SET status='pending',updated_at=? WHERE id=?", (now(), job_id))

    def run(self, job_id, runner):
        from .conditional_personas import allocate, condition_plan
        from .personas import PersonaGenerator
        from .providers import make_provider
        from .security import redact
        job = self.job(job_id)
        spec = WorkbenchSpec.model_validate_json(job["spec"])
        cp = json.loads(job["checkpoint"])
        for item in cp.get("generation", []):
            if item["status"] == "running":
                item["status"] = "pending"
        active = lambda: self.job(job_id)["status"] == "running"
        try:
            cp.setdefault("task_ids", [])
            if spec.questionnaire and not self.db.get("questionnaire", spec.questionnaire.id):
                self.db.save("questionnaire", spec.questionnaire)
            if spec.generate_count:
                cp.setdefault("generation", [{"index": i, "status": "pending", "error": "", "attempts": 0} for i in range(spec.generate_count)])
                self._checkpoint(job_id, cp, "personas")
                plan = condition_plan(spec.conditions, spec.generate_count, spec.seed)
                kinds = allocate(spec.ratios, spec.generate_count, spec.seed)
                generator = PersonaGenerator(make_provider(spec.provider, self.secrets.get(spec.provider.id, spec.provider.provider), self.db, job_id)) if any(i["status"] == "pending" for i in cp["generation"]) else None
                completed = [self.db.get("persona", i["persona_id"]) for i in cp["generation"] if i["status"] == "completed"]
                if not self._generate_people(job_id, spec, cp, active, generator, plan, kinds, completed):
                    return
            if not active():
                return
            if spec.mode != "personas":
                self._prepare(job_id, spec, cp)
                self._checkpoint(job_id, cp, "answers" if spec.mode == "answers" else "forms")
                for task_id in cp["task_ids"]:
                    if not active():
                        return
                    status = self.db.task(task_id)["status"]
                    if status in {"completed", "completed_with_errors", "cancelled"}:
                        continue
                    runner.active_id = task_id
                    self.db.task_status(task_id, "running")
                    runner._run(task_id)
                    task_status = self.db.task(task_id)["status"]
                    if task_status in PAUSED | {"cancelled"}:
                        if active():
                            if task_status == "provider_paused":
                                reason = next((r["error"] for r in self.db.rows(
                                    "SELECT error FROM task_items WHERE task_id=? AND status='pending' AND error!=''", (task_id,))), "AI 服務錯誤")
                                self._pause_for_provider(job_id, reason)
                            self.control(job_id, "paused")
                        return
            failures = sum(i["status"] == "failed" for i in cp.get("generation", []))
            failures += sum(self.db.task(t)["status"] in {"failed", "completed_with_errors"} for t in cp["task_ids"])
            status = "completed_with_errors" if failures else "completed"
            if not active():
                return
            self.db.execute("UPDATE workbench_jobs SET status=?,phase='finished',updated_at=? WHERE id=?", (status, now(), job_id))
            self.export(job_id)
            self.db.execute("UPDATE workbench_jobs SET phase='finished',updated_at=? WHERE id=?", (now(), job_id))
        except Exception as exc:
            logging.getLogger("survey_sim.workbench").exception("Workbench failed job=%s", job_id)
            message = redact(str(exc)) if isinstance(exc, AppError) else "工作台處理失敗，請查看除錯日誌"
            self.db.event(job_id, message, "error")
            self.db.execute("UPDATE workbench_jobs SET status='failed',error=?,updated_at=? WHERE id=?", (message, now(), job_id))
            try:
                self.export(job_id)
            except Exception:
                self.db.event(job_id, "失敗報告未能匯出，已保存資料仍在資料庫，可稍後重試匯出", "error")
        finally:
            cp = json.loads(self.job(job_id)["checkpoint"])
            for item in cp.get("generation", []):
                if item["status"] == "running":
                    item["status"] = "pending"
                if self.job(job_id)["status"] == "cancelled" and item["status"] == "pending":
                    item["status"] = "cancelled"
            self._checkpoint(job_id, cp, self.job(job_id)["phase"])
            runner.active_job = None

    def _generate_people(self, job_id, spec, cp, active, generator, plan, kinds, completed):
        """Generate pending personas, up to spec.concurrency at a time. Each finished
        persona is saved together with the checkpoint. Returns False when the job was
        paused, cancelled or stopped by a service-wide AI error."""
        from .conditional_personas import conditional_person
        from .persona_names import ensure_name
        from .security import redact
        lock = threading.RLock()
        stop = threading.Event()
        keep_going = lambda: active() and not stop.is_set()

        def save():
            with lock:
                self._checkpoint(job_id, cp, "personas")

        def one(item):
            if not keep_going():
                return
            with lock:
                item.update(status="running", attempts=item["attempts"] + 1)
                cp["current_person"] = f"生成人物 {item['index'] + 1}"
                self._checkpoint(job_id, cp, "personas")
                previous = list(completed)
            try:
                i = item["index"]
                person = conditional_person(generator, spec.conditions, plan[i], kinds[i], spec.seed, i, spec.topic,
                    spec.conditions.custom_background + "\n情境條件：" + dump(spec.conditions), previous, should_continue=keep_going)
                if person is None:
                    with lock:
                        item["status"] = "pending"
                    save()
                    return
                person.id = str(uuid5(NAMESPACE_URL, f"workbench:{job_id}:persona:{i}"))
                person.topic_attributes["dataset_kind"] = "simulation"
                with lock:
                    ensure_name(person, [p.name for p in completed if p])
                    item.update(status="completed", persona_id=person.id, error="")
                    # Persist the persona and its checkpoint together before advancing.
                    with self.db.connect() as conn:
                        conn.execute("INSERT INTO entities VALUES('persona',?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at", (person.id, dump(person), now()))
                        conn.execute("UPDATE workbench_jobs SET checkpoint=?,updated_at=? WHERE id=?", (dump(cp), now(), job_id))
                    completed.append(person)
            except ProviderError as exc:
                with lock:
                    if exc.kind == "api":
                        # A key / quota / model error would fail every remaining persona.
                        item.update(status="pending", error=redact(str(exc)))
                        first = not stop.is_set()
                        stop.set()
                    else:
                        item.update(status="failed", error=redact(str(exc)))
                        self.db.event(job_id, item["error"], "error")
                save()
                if exc.kind == "api" and first:
                    self._pause_for_provider(job_id, item["error"])
            except Exception as exc:
                with lock:
                    item.update(status="failed", error=redact(str(exc)) if isinstance(exc, AppError) else "人物生成失敗，請查看日誌")
                    self.db.event(job_id, item["error"], "error")
                save()

        pending = [item for item in cp["generation"] if item["status"] == "pending"]
        workers = max(1, min(spec.concurrency, 5))
        if workers == 1:
            for item in pending:
                if not keep_going():
                    break
                one(item)
        else:
            with ThreadPoolExecutor(workers, thread_name_prefix="survey-persona") as pool:
                list(pool.map(one, pending))
        return keep_going()

    def _prepare(self, job_id, spec, cp):
        sources = self._sources(spec)
        buckets = []
        for response in sources:
            bucket = next((b for b in buckets if b[0].questionnaire_snapshot == response.questionnaire_snapshot and
                b[0].provider_snapshot == response.provider_snapshot and response.persona_id not in {r.persona_id for r in b}), None)
            if bucket is None:
                bucket = []
                buckets.append(bucket)
            bucket.append(response)
        if not sources:
            assigned = {p.id for t in cp["task_ids"] for p in TaskSpec.model_validate_json(self.db.task(t)["spec"]).personas}
            people = spec.personas + [self.db.get("persona", i["persona_id"]) for i in cp.get("generation", []) if i["status"] == "completed"]
            people = [p for p in people if p.id not in assigned]
            if not people and not cp["task_ids"]:
                raise AppError("沒有成功取得的人物，可重新執行失敗的人物生成工作")
            if people:
                buckets.append(people)
        for bucket in buckets:
            first = bucket[0]
            reused = isinstance(first, Response)
            people = [r.persona_snapshot for r in bucket] if reused else bucket
            signature = ":".join(r.id for r in bucket) if reused else ":".join(sorted(p.id for p in people))
            task_id = str(uuid5(NAMESPACE_URL, f"workbench:{job_id}:task:{signature}"))
            if task_id not in cp["task_ids"]:
                task = TaskSpec(questionnaire=first.questionnaire_snapshot if reused else spec.questionnaire, personas=people,
                    provider=first.provider_snapshot if reused else spec.provider, seed=spec.seed,
                    mode=spec.answer_mode, variability=spec.variability, interval_seconds=spec.interval_seconds,
                    form_target=spec.form_target if spec.mode in {"dry_run", "submit"} else None,
                    form_allowlist=spec.form_allowlist, form_dry_run=spec.mode != "submit", concurrency=spec.concurrency,
                    source_response_ids={r.persona_id: r.id for r in bucket} if reused else {})
                if not self.db.rows("SELECT id FROM tasks WHERE id=?", (task_id,)):
                    self.db.create_task(task, task_id)
                cp["task_ids"].append(task_id)
                self._checkpoint(job_id, cp, "prepare")

    def report(self, job_id):
        from .analysis import display_answer
        job = self.job(job_id)
        spec = WorkbenchSpec.model_validate_json(job["spec"])
        cp = json.loads(job["checkpoint"])
        ids = cp.get("task_ids", [])
        responses = {r.id: r for t in ids for r in self.db.responses(t)}
        responses.update({r.id: r for r in self._sources(spec)})
        people = {p.id: p for p in spec.personas}
        people.update({i["persona_id"]: self.db.get("persona", i["persona_id"]) for i in cp.get("generation", []) if i["status"] == "completed"})
        people.update({r.persona_id: r.persona_snapshot for r in responses.values()})
        details = []
        for r in responses.values():
            questions = {q.id: q for q in r.questionnaire_snapshot.questions}
            details.extend({"response_id": r.id, "persona_id": r.persona_id, "人物": r.persona_snapshot.name,
                "question_id": a.question_id, "題目": questions[a.question_id].title, "答案文字": display_answer(questions[a.question_id], a.value, a.other_text),
                **a.model_dump(mode="json")} for a in r.answers)
        items = [dict(i, task_id=t) for t in ids for i in self.db.rows("SELECT * FROM task_items WHERE task_id=?", (t,))]
        submissions = [s for r in responses.values() for s in self.db.rows(
            "SELECT * FROM submissions WHERE response_id=? AND created_at>=?", (r.id, job["created_at"]))]
        usage = [u for t in [job_id] + ids for u in self.db.rows("SELECT * FROM usage WHERE task_id=?", (t,))]
        return {"dataset": self.db.metadata(), "job_id": job_id, "status": job["status"], "phase": job["phase"], "error": job["error"],
            "method": "AI 模擬資料；不是實際受訪者。只對明確授權的測試表單進行提交。", "settings": spec.model_dump(mode="json"),
            "人物": [p.model_dump(mode="json") for p in people.values() if p], "人物生成紀錄": cp.get("generation", []),
            "問卷": [q.model_dump(mode="json") for q in {r.questionnaire_id: r.questionnaire_snapshot for r in responses.values()}.values()] or ([spec.questionnaire.model_dump(mode="json")] if spec.questionnaire else []),
            "回答紀錄": [r.model_dump(mode="json") for r in responses.values()], "回答明細": details,
            "任務明細": items, "提交紀錄": submissions, "API用量": usage,
            "摘要": {"人物數": len(people), "回答數": len(responses), "已驗證": sum(r.status != "error" for r in responses.values()),
                "已略過": sum(i["status"] == "skipped" for i in items),
                "需人工檢查": sum(r.status == "review" for r in responses.values()), "成功畫面或本地收件": sum(s["status"] == "success" for s in submissions),
                "提交待查": sum(s["status"] == "unknown" for s in submissions),
                "失敗": sum(i["status"] in {"failed", "invalid"} for i in items) + sum(i["status"] == "failed" for i in cp.get("generation", []))}}

    def export(self, job_id):
        from .reports import report_exports
        folder = self.db.path.parent / "job-results" / job_id
        folder.mkdir(parents=True, exist_ok=True)
        exports = report_exports(self.report(job_id))
        for name, extension in (("JSON", "json"), ("CSV ZIP", "zip"), ("Excel", "xlsx")):
            (folder / ("simulation." + extension)).write_bytes(exports[name])
        return folder
