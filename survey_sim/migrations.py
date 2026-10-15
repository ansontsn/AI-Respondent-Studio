"""Additive, transactional schema migration with a consistent pre-upgrade backup."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .errors import AppError


def migrate(path):
    path = Path(path)
    try:
        with sqlite3.connect(path, timeout=30) as conn:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            if current > 4:
                raise AppError("資料庫版本比此程式更新，請使用相容版本，避免降級寫入。")
            if current == 4:
                return
            # Backup before the first V2 write. A new, empty database needs no backup.
            populated = conn.execute("SELECT count(*) FROM entities").fetchone()[0] or conn.execute("SELECT count(*) FROM tasks").fetchone()[0]
            if populated:
                backup = path.parent / "backups" / ("before-v2.sqlite3" if current < 2 else "before-v3.sqlite3" if current < 3 else "before-v4.sqlite3")
                backup.parent.mkdir(parents=True, exist_ok=True)
                if not backup.exists():
                    with sqlite3.connect(backup) as target:
                        conn.backup(target)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS quality_actions(id TEXT PRIMARY KEY,response_id TEXT NOT NULL,new_task_id TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL)")
            timestamp = datetime.now(timezone.utc).isoformat()
            meta = json.loads(conn.execute("SELECT metadata FROM workspace WHERE id=1").fetchone()[0])
            if current < 2:
                conn.execute("INSERT OR IGNORE INTO schema_migrations VALUES(2,?)", (timestamp,))
            if "other_text" not in {row[1] for row in conn.execute("PRAGMA table_info(answers)")}:
                conn.execute("ALTER TABLE answers ADD COLUMN other_text TEXT NOT NULL DEFAULT ''")
            receipt_columns = {row[1] for row in conn.execute("PRAGMA table_info(local_receipts)")}
            if receipt_columns and "other_text" not in receipt_columns:
                conn.execute("ALTER TABLE local_receipts ADD COLUMN other_text TEXT NOT NULL DEFAULT '{}'")
            conn.execute("CREATE TABLE IF NOT EXISTS workbench_jobs(id TEXT PRIMARY KEY,spec TEXT NOT NULL,status TEXT NOT NULL,phase TEXT NOT NULL,checkpoint TEXT NOT NULL DEFAULT '{}',error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL)")
            meta["schema_version"] = 4
            conn.execute("UPDATE workspace SET metadata=? WHERE id=1", (json.dumps(meta, ensure_ascii=False),))
            conn.execute("INSERT OR IGNORE INTO schema_migrations VALUES(3,?)", (timestamp,))
            conn.execute("INSERT OR IGNORE INTO schema_migrations VALUES(4,?)", (timestamp,))
            conn.execute("PRAGMA user_version=4")
    except sqlite3.Error as exc:
        raise AppError("資料庫遷移失敗；交易已回復，請查看備份並確認檔案權限。") from exc
