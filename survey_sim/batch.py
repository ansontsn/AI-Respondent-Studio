from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager

from .engine import AnswerEngine, Interrupted
from .errors import AppError, ProviderError
from .models import TaskSpec, Response
from .providers import make_provider
from .security import redact
from .costs import BudgetedProvider, BudgetExceeded

logger = logging.getLogger(__name__)
# Task states that stop the worker but can be resumed.
PAUSED = {"paused", "stopped", "budget_paused", "provider_paused"}
MAX_CONCURRENCY = 5


def concurrency(spec):
    """Personas processed at the same time. Website flows and budget-limited tasks stay
    sequential: their duplicate-submission and budget checks assume one request at a time."""
    if spec.website_workflow or spec.website_survey or spec.budget_limit is not None:
        return 1
    return max(1, min(spec.concurrency, MAX_CONCURRENCY))

class BatchRunner:
    """One bounded worker, persisted queue/checkpoints; UI controls never run in worker."""
    def __init__(self, db, secrets):
        self.db, self.secrets = db, secrets
        self.thread = None
        self.lock = threading.Lock()
        self.active_id = None

    def start(self, task_id: str):
        with self.lock:
            if self.thread and self.thread.is_alive():
                if self.active_id != task_id:
                    raise AppError("目前已有任務執行中；請先暫停或停止它。")
                self.db.task_status(task_id, "running")
                return
            items = self.db.rows("SELECT status FROM task_items WHERE task_id=?", (task_id,))
            if not any(x["status"] == "pending" for x in items):
                raise AppError("沒有待執行項目；可重新排入失敗項目或建立新任務。")
            self.active_id = task_id
            self.db.task_status(task_id, "running")
            self.thread = threading.Thread(target=self._run, args=(task_id,), daemon=True, name="survey-batch")
            self.thread.start()

    def pause(self, id):
        self.db.task_status(id, "paused")

    def stop(self, id):
        self.db.task_status(id, "stopped")

    def start_group(self, task_ids):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise AppError("目前已有執行任務，請先暫停或停止後再執行實驗。")
            self.thread = threading.Thread(target=self._run_group, args=(list(task_ids),), daemon=True, name="survey-experiment")
            self.thread.start()

    def _run_group(self, ids):
        for task_id in ids:
            status = self.db.task(task_id)["status"]
            if status in {"completed", "completed_with_errors", "cancelled"}:
                continue
            self.active_id = task_id
            self.db.task_status(task_id, "running")
            self._run(task_id)
            if self.db.task(task_id)["status"] in PAUSED:
                break

    def cancel_group(self, ids):
        for id in ids:
            if self.db.task(id)["status"] not in {"completed", "completed_with_errors"}:
                self.db.task_status(id, "cancelled")

    def _run(self, task_id):
        try:
            spec = TaskSpec.model_validate_json(self.db.task(task_id)["spec"])
            shared = {"engine": None, "lock": threading.Lock()}
            workers = concurrency(spec)
            with self._local_form(spec):
                if workers == 1:
                    self._work(task_id, spec, shared)
                else:
                    self.db.event(task_id, f"同時處理 {workers} 位人物")
                    threads = [threading.Thread(target=self._work, args=(task_id, spec, shared), daemon=True,
                                                name=f"survey-worker-{n + 1}") for n in range(workers)]
                    for thread in threads:
                        thread.start()
                    for thread in threads:
                        thread.join()
            # Finish only when nothing is left; a pause / stop keeps the remaining queue.
            if self.db.task(task_id)["status"] == "running" and not self.db.rows(
                    "SELECT 1 FROM task_items WHERE task_id=? AND status IN ('pending','running')", (task_id,)):
                failed = self.db.rows("SELECT 1 FROM task_items WHERE task_id=? AND status IN ('failed','invalid','unknown')", (task_id,))
                self.db.task_status(task_id, "completed_with_errors" if failed else "completed")
        except Exception as exc:
            logger.exception("Batch task failed %s", task_id)
            self.db.event(task_id, redact(str(exc)) if isinstance(exc, AppError) else "批次服務失敗，請查看日誌", "error")
            self.db.task_status(task_id, "failed")

    @contextmanager
    def _local_form(self, spec):
        """Keep one local test-form server up for the whole run, so parallel workers
        never stop a server another worker is still using."""
        if spec.form_target and spec.form_target.kind == "local":
            from .staged_survey import local_form_available
            with local_form_available(self.db, spec.form_target):
                yield
        else:
            yield

    def _engine(self, task_id, spec, shared):
        with shared["lock"]:
            if shared["engine"] is None:
                provider = make_provider(spec.provider, self.secrets.get(spec.provider.id, spec.provider.provider), self.db, task_id)
                shared["engine"] = AnswerEngine(BudgetedProvider(provider, self.db, task_id))
            return shared["engine"]

    def _work(self, task_id, spec, shared):
        """One worker: claim the next pending persona until the queue is empty or the task stops."""
        try:
            while self.db.task(task_id)["status"] == "running":
                item = self.db.claim_item(task_id)
                if not item:
                    return
                self._process(task_id, spec, item, shared)
                deadline = time.monotonic() + spec.interval_seconds
                while time.monotonic() < deadline and self.db.task(task_id)["status"] == "running":
                    time.sleep(min(.2, max(0, deadline - time.monotonic())))
        except Exception as exc:
            logger.exception("Batch worker failed %s", task_id)
            self.db.event(task_id, redact(str(exc)) if isinstance(exc, AppError) else "批次服務失敗，請查看日誌", "error")
            self.db.task_status(task_id, "failed")

    def _process(self, task_id, spec, item, shared):
        persona = next(p for p in spec.personas if p.id == item["persona_id"])
        response = None
        try:
            checkpoint = json.loads(item["checkpoint"])
            keep_running = lambda: self.db.task(task_id)["status"] == "running"
            source_id = spec.source_response_ids.get(persona.id)
            saved = self.db.rows("SELECT body FROM responses WHERE id=?", (source_id,)) if source_id else self.db.rows(
                "SELECT body FROM responses WHERE task_id=? AND persona_id=?", (task_id, persona.id))
            engine = self._engine(task_id, spec, shared) if not saved and not source_id else None
            if saved:
                response = Response.model_validate_json(saved[0]["body"])
            elif source_id:
                raise AppError("選取的既有回答已不存在；不會重新生成或提交")
            elif spec.website_survey:
                from .staged_survey import StagedSurveyRunner
                response = StagedSurveyRunner(self.db, engine).run(task_id, spec, persona, checkpoint, keep_running)
            else:
                if spec.website_workflow:
                    from .website_experience import WebsiteExperience, require_usable, DONE, workflow_for_person
                    from .models import WebsiteRun
                    previous = checkpoint.get("website_run")
                    run = WebsiteRun.model_validate(previous) if previous else None
                    workflow = workflow_for_person(spec, persona.id)
                    if run and run.plan.tier != workflow.tier:
                        raise AppError("保存的網站紀錄與人物分配方案不同，請建立新的任務。")
                    if run and (run.submission_started or run.status in DONE):
                        require_usable(run, workflow)
                    else:
                        def save_website(run):
                            checkpoint["website_run"] = run.model_dump(mode="json")
                            self.db.checkpoint(task_id, persona.id, checkpoint)
                        run = WebsiteExperience(self.db).run(workflow, persona, spec.seed, keep_running, save_website)
                        require_usable(run, workflow)
                def save_page(data):
                    checkpoint.update(data)
                    self.db.checkpoint(task_id, persona.id, checkpoint)
                response = engine.run(task_id, spec, persona, checkpoint, save_page, keep_running)
            if not saved:
                self.db.save_response(response, pending_form=spec.form_target is not None)
            if spec.form_target:
                self._fill_response(task_id, spec, persona, response, keep_running)
            self.db.event(task_id, f"{persona.name} 完成，驗證狀態 {response.status}")
        except Interrupted:
            state = "cancelled" if self.db.task(task_id)["status"] == "cancelled" else "pending"
            self.db.execute("UPDATE task_items SET status=? WHERE task_id=? AND persona_id=?", (state, task_id, persona.id))
        except BudgetExceeded as exc:
            self.db.execute("UPDATE task_items SET status='pending',error=? WHERE task_id=? AND persona_id=?", (str(exc), task_id, persona.id))
            self.db.task_status(task_id, "budget_paused")
            self.db.event(task_id, str(exc), "warning")
        except ProviderError as exc:
            if exc.kind != "api":
                self._item_failed(task_id, spec, persona, response, exc)
            else:
                # Key, quota, model or connection errors affect every remaining
                # persona: pause once instead of failing the whole queue.
                message = redact(str(exc))
                logger.warning("AI service error paused task=%s: %s", task_id, message)
                self.db.execute("UPDATE task_items SET status='pending',error=? WHERE task_id=? AND persona_id=?", (message, task_id, persona.id))
                if self.db.task(task_id)["status"] == "running":
                    self.db.task_status(task_id, "provider_paused")
                    self.db.event(task_id, f"AI 服務錯誤，已暫停整批：{message}。修正金鑰、額度或模型設定後按繼續；已完成結果與頁面進度保留。", "error")
        except Exception as exc:
            self._item_failed(task_id, spec, persona, response, exc)
    def _item_failed(self, task_id, spec, persona, response, exc):
        logger.error("Person simulation failed task=%s persona=%s", task_id, persona.id, exc_info=exc)
        message = redact(str(exc)) if isinstance(exc, AppError) else "執行失敗，請查看除錯日誌"
        unknown = bool(response and spec.form_target and self.db.rows(
            "SELECT 1 FROM submissions WHERE response_id=? AND status='unknown' AND dry_run=0", (response.id,)))
        self.db.execute("UPDATE task_items SET status=?,error=? WHERE task_id=? AND persona_id=?",
            ("unknown" if unknown else "failed", message, task_id, persona.id))
        self.db.event(task_id, message, "warning" if unknown else "error")

    def _fill_response(self, task_id, spec, persona, response, keep_running):
        from .automation import FormAutomation
        from .errors import AutomationError
        from .security import clean_form_url
        if response.persona_id != persona.id or response.questionnaire_snapshot.model_dump() != spec.questionnaire.model_dump():
            raise AppError("既有回答與本次人物 / 問卷版本不符")
        from .validator import AnswerValidator
        _, issues, pages, checked_status = AnswerValidator().validate(response.questionnaire_snapshot, response.persona_snapshot, response.answers)
        if pages != response.visited_pages:
            raise AppError("保存的回答分流路徑與驗證結果不符")
        from .validator import submittable
        if checked_status == "error":
            # Keep counting explicit errors as invalid, not as a harmless skip.
            self.db.execute("UPDATE task_items SET status='invalid',error=? WHERE task_id=? AND persona_id=?",
                ("回答存在明確錯誤；已保存，未填表", task_id, persona.id))
            return
        if not spec.form_dry_run and not submittable(checked_status, issues):
            self.db.execute("UPDATE task_items SET status='skipped',error=? WHERE task_id=? AND persona_id=?",
                ("答案尚需修正或人工檢查；已保存，略過實際提交", task_id, persona.id))
            return
        if not spec.form_dry_run and self.db.rows("SELECT id FROM submissions WHERE response_id=? AND url=? AND dry_run=0 AND status='success'",
                (response.id, clean_form_url(spec.form_target.url))):
            self.db.execute("UPDATE task_items SET status='skipped',error='此回答已成功提交，未重送' WHERE task_id=? AND persona_id=?", (task_id, persona.id))
            return
        automation = FormAutomation(self.db, self.db.path.parent / "artifacts")
        for attempt in range(min(spec.provider.retries, 3) + 1):
            if not keep_running():
                raise Interrupted("填表已暫停或取消")
            try:
                from .staged_survey import local_form_available
                with local_form_available(self.db, spec.form_target):
                    result = automation.run(spec.form_target, response, spec.form_allowlist, spec.form_dry_run, keep_running)
                self.db.checkpoint(task_id, persona.id, {"response_id": response.id, "form_result": result})
                self.db.execute("UPDATE task_items SET status='completed',error='' WHERE task_id=? AND persona_id=?", (task_id, persona.id))
                return
            except AutomationError as exc:
                if not exc.retryable or attempt >= min(spec.provider.retries, 3):
                    raise
                self.db.event(task_id, f"填表載入暫時失敗，第 {attempt + 1} 次退避重試：{exc}", "warning")
                deadline = time.monotonic() + 2 ** attempt
                while keep_running() and time.monotonic() < deadline:
                    time.sleep(.1)
