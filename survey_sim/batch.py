from __future__ import annotations

import json
import logging
import threading
import time

from .engine import AnswerEngine, Interrupted
from .errors import AppError
from .models import TaskSpec
from .providers import make_provider
from .security import redact

logger = logging.getLogger(__name__)


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

    def _run(self, task_id):
        try:
            spec = TaskSpec.model_validate_json(self.db.task(task_id)["spec"])
            provider = make_provider(spec.provider, self.secrets.get(spec.provider.id, spec.provider.provider), self.db, task_id)
            engine = AnswerEngine(provider)
            while self.db.task(task_id)["status"] == "running":
                item = self.db.claim_item(task_id)
                if not item:
                    failed = self.db.rows("SELECT 1 FROM task_items WHERE task_id=? AND status IN ('failed','invalid')", (task_id,))
                    self.db.task_status(task_id, "completed_with_errors" if failed else "completed")
                    break
                persona = next(p for p in spec.personas if p.id == item["persona_id"])
                try:
                    response = engine.run(task_id, spec, persona, json.loads(item["checkpoint"]),
                        lambda data: self.db.checkpoint(task_id, persona.id, data),
                        lambda: self.db.task(task_id)["status"] == "running")
                    self.db.save_response(response)
                    self.db.event(task_id, f"{persona.name} 完成，驗證狀態 {response.status}")
                except Interrupted:
                    self.db.execute("UPDATE task_items SET status='pending' WHERE task_id=? AND persona_id=?", (task_id, persona.id))
                except Exception as exc:
                    logger.exception("Person simulation failed task=%s persona=%s", task_id, persona.id)
                    message = redact(str(exc)) if isinstance(exc, AppError) else "執行失敗，請查看除錯日誌"
                    self.db.execute("UPDATE task_items SET status='failed',error=? WHERE task_id=? AND persona_id=?", (message, task_id, persona.id))
                    self.db.event(task_id, message, "error")
                deadline = time.monotonic() + spec.interval_seconds
                while time.monotonic() < deadline and self.db.task(task_id)["status"] == "running":
                    time.sleep(min(.2, max(0, deadline - time.monotonic())))
        except Exception as exc:
            logger.exception("Batch task failed %s", task_id)
            self.db.event(task_id, redact(str(exc)) if isinstance(exc, AppError) else "批次服務失敗，請查看日誌", "error")
            self.db.task_status(task_id, "failed")
