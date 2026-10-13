from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .batch import BatchRunner
from .examples import onlyframe_example, general_example
from .models import ProviderConfig
from .security import SecretStore, setup_logging
from .storage import Database, dump

ROOT = Path(__file__).resolve().parent.parent


class Runtime:
    def __init__(self, data_dir=None):
        load_dotenv(ROOT / ".env")
        self.data_dir = Path(data_dir or os.getenv("APP_DATA_DIR", "data"))
        if not self.data_dir.is_absolute():
            self.data_dir = ROOT / self.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if (ROOT / "data" / "browsers").exists():
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "data" / "browsers"))
        setup_logging(self.data_dir / "logs")
        self.db = Database(self.data_dir / "simulator.sqlite3")
        self.db.recover()
        self.secrets = SecretStore()
        self.runner = BatchRunner(self.db, self.secrets)
        self.mock_server = None
        if not self.db.list("provider"):
            self.db.save("provider", ProviderConfig(id="mock-default"))
        if not self.db.list("questionnaire"):
            self.db.save("questionnaire", onlyframe_example())
            self.db.save("questionnaire", general_example())

    def setting(self, key, default=None):
        rows = self.db.rows("SELECT body FROM entities WHERE kind='setting' AND id=?", (key,))
        return json.loads(rows[0]["body"]) if rows else default

    def set_setting(self, key, value):
        from .models import now
        self.db.execute("INSERT INTO entities VALUES('setting',?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body,updated_at=excluded.updated_at", (key, dump(value), now()))

    def local_form(self):
        from .mock_form import MockFormServer
        from .errors import AppError
        if not self.mock_server:
            port = int(os.getenv("MOCK_FORM_PORT", "8765"))
            try:
                self.mock_server = MockFormServer(self.db, port).start()
            except OSError as exc:
                raise AppError(f"本地測試表單的 {port} 連接埠已被占用。請在 .env 更改 MOCK_FORM_PORT 或關閉舊程式。") from exc
        return self.mock_server
