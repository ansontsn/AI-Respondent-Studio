from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .errors import AppError
from .models import Persona, Questionnaire, ProviderConfig, Response, TaskSpec, FormTarget, now, uid

logger = logging.getLogger(__name__)


def dump(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS workspace (
                id INTEGER PRIMARY KEY CHECK(id=1), metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entities (
                kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, spec TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS task_items (
                task_id TEXT NOT NULL REFERENCES tasks(id), persona_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0, checkpoint TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(task_id,persona_id));
            CREATE TABLE IF NOT EXISTS responses (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, persona_id TEXT NOT NULL,
                questionnaire_id TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(task_id,persona_id));
            CREATE TABLE IF NOT EXISTS answers (
                response_id TEXT NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
                question_id TEXT NOT NULL, value TEXT, rationale TEXT NOT NULL,
                validation TEXT NOT NULL, PRIMARY KEY(response_id,question_id));
            CREATE TABLE IF NOT EXISTS usage (
                id TEXT PRIMARY KEY, config_id TEXT NOT NULL, task_id TEXT NOT NULL,
                provider TEXT NOT NULL, model TEXT NOT NULL, operation TEXT NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER, cost REAL, currency TEXT,
                rate_source TEXT, duration REAL, status TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                level TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY, response_id TEXT NOT NULL, target_id TEXT NOT NULL,
                url TEXT NOT NULL, dry_run INTEGER NOT NULL, status TEXT NOT NULL,
                message TEXT NOT NULL, artifact TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS submission_lookup ON submissions(response_id,url,status);
            """)
            meta = {"id": uid(), "name": "AI 問卷模擬工作區", "source": "AI 虛擬人物與問卷測試",
                    "dataset_kind": "simulation", "created_at": now(), "schema_version": 1,
                    "interpretation": "只描述模型建構情境，不代表真實受訪者或市場分布"}
            db.execute("INSERT OR IGNORE INTO workspace VALUES(1,?)", (dump(meta),))

    @contextmanager
    def connect(self):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=30)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        except sqlite3.Error as exc:
            logger.exception("Database operation failed")
            raise AppError("資料庫讀寫失敗，請確認磁碟空間及檔案權限；已完成結果保存在資料庫中。") from exc
        finally:
            if db is not None:
                db.close()

    def rows(self, sql: str, args=()) -> list[dict]:
        with self.connect() as db:
            return [dict(x) for x in db.execute(sql, args)]

    def execute(self, sql: str, args=()):
        with self.connect() as db:
            db.execute(sql, args)

    def metadata(self):
        return json.loads(self.rows("SELECT metadata FROM workspace WHERE id=1")[0]["metadata"])

    def save(self, kind: str, obj):
        # Model validation explicitly excludes secret fields from ProviderConfig.
        if kind == "persona":
            previous = self.get(kind, obj.id)
            if previous and previous != obj and obj.revision <= previous.revision:
                obj.revision = previous.revision + 1
        self.execute("INSERT INTO entities VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at",
                     (kind, obj.id, dump(obj), now()))

    def list(self, kind: str):
        types = {"persona": Persona, "questionnaire": Questionnaire, "provider": ProviderConfig, "target": FormTarget}
        return [types[kind].model_validate_json(x["body"]) for x in self.rows(
            "SELECT body FROM entities WHERE kind=? ORDER BY updated_at DESC", (kind,))]

    def get(self, kind: str, id: str):
        return next((x for x in self.list(kind) if x.id == id), None)

    def delete(self, kind: str, id: str):
        self.execute("DELETE FROM entities WHERE kind=? AND id=?", (kind, id))

    def event(self, task_id: str, message: str, level: str = "info"):
        from .security import redact
        self.execute("INSERT INTO events(task_id,level,message,created_at) VALUES(?,?,?,?)",
                     (task_id, level, redact(message), now()))

    def create_task(self, spec: TaskSpec) -> str:
        if not spec.questionnaire.confirmed:
            raise AppError("請先在問卷管理確認題目、選項及分流。")
        if not spec.personas or len({p.id for p in spec.personas}) != len(spec.personas):
            raise AppError("任務需要至少一位人物且人物 ID 不可重複。")
        id = uid()
        with self.connect() as db:
            db.execute("INSERT INTO tasks VALUES(?,?,?,?,?)", (id, dump(spec), "ready", now(), now()))
            db.executemany("INSERT INTO task_items(task_id,persona_id) VALUES(?,?)", [(id, p.id) for p in spec.personas])
        return id

    def task(self, id: str):
        rows = self.rows("SELECT * FROM tasks WHERE id=?", (id,))
        if not rows:
            raise AppError("找不到執行任務。")
        return rows[0]

    def task_status(self, id: str, status: str):
        self.execute("UPDATE tasks SET status=?,updated_at=? WHERE id=?", (status, now(), id))

    def claim_item(self, task_id: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task or task["status"] != "running":
                return None
            row = db.execute("SELECT * FROM task_items WHERE task_id=? AND status='pending' ORDER BY rowid LIMIT 1", (task_id,)).fetchone()
            if row:
                db.execute("UPDATE task_items SET status='running',attempts=attempts+1,error='' WHERE task_id=? AND persona_id=?",
                           (task_id, row["persona_id"]))
                return dict(row)
        return None

    def checkpoint(self, task_id: str, persona_id: str, value: dict):
        self.execute("UPDATE task_items SET checkpoint=? WHERE task_id=? AND persona_id=?", (dump(value), task_id, persona_id))

    def save_response(self, response: Response):
        with self.connect() as db:
            db.execute("INSERT INTO responses VALUES(?,?,?,?,?,?,?)", (response.id, response.task_id, response.persona_id,
                response.questionnaire_id, response.status, dump(response), response.created_at))
            db.executemany("INSERT INTO answers VALUES(?,?,?,?,?)", [(response.id, a.question_id, dump(a.value), a.rationale, a.validation)
                                                                    for a in response.answers])
            db.execute("UPDATE task_items SET status=?,error=?,checkpoint='{}' WHERE task_id=? AND persona_id=?",
                       ("invalid" if response.status == "error" else "completed", "回答存在明確錯誤" if response.status == "error" else "",
                        response.task_id, response.persona_id))

    def responses(self, task_id: str | None = None):
        rows = self.rows("SELECT body FROM responses" + (" WHERE task_id=?" if task_id else "") + " ORDER BY created_at",
                         (task_id,) if task_id else ())
        return [Response.model_validate_json(x["body"]) for x in rows]

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='paused',updated_at=? WHERE status='running'", (now(),))
            db.execute("UPDATE task_items SET status='pending',error='上次執行中斷，保留頁面進度' WHERE status='running'")
            # Never retry a submission that might have reached the server automatically.
            db.execute("UPDATE submissions SET status='unknown',message='程式中斷；需人工查證是否送達',updated_at=? WHERE status='submitting'", (now(),))

    def retry_failed(self, task_id: str):
        if self.task(task_id)["status"] == "running":
            raise AppError("請先暫停任務再重新排入失敗項目。")
        self.execute("UPDATE task_items SET status='pending',error='' WHERE task_id=? AND status='failed'", (task_id,))
        self.task_status(task_id, "ready")

    def reserve_submission(self, response_id: str, target: FormTarget, dry_run: bool) -> str:
        from .security import clean_url
        url = clean_url(target.url)
        id = uid()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not dry_run:
                row = db.execute("SELECT id FROM submissions WHERE response_id=? AND url=? AND dry_run=0 AND status IN ('submitting','success','unknown')",
                                 (response_id, url)).fetchone()
                if row:
                    raise AppError("此回答已提交、正在提交或狀態不明；為避免重複提交，請先人工查證。")
            db.execute("INSERT INTO submissions VALUES(?,?,?,?,?,?,?,?,?,?)", (id, response_id, target.id, url,
                int(dry_run), "filling" if dry_run else "submitting", "準備執行", "", now(), now()))
        return id

    def finish_submission(self, id: str, status: str, message: str, artifact: str = ""):
        from .security import redact
        self.execute("UPDATE submissions SET status=?,message=?,artifact=?,updated_at=? WHERE id=?", (status, redact(message), artifact, now(), id))

    def backup(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source:
            with sqlite3.connect(path) as target:
                source.backup(target)
