from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .errors import AppError

_known_secrets: set[str] = set()
ENV_NAMES = {"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
             "gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
             "compatible": "COMPATIBLE_API_KEY", "ollama": "OLLAMA_API_KEY"}


def register_secret(value: str) -> str:
    if value:
        _known_secrets.add(value)
    return value


def redact(value: str) -> str:
    for secret in sorted(_known_secrets, key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?i)(Bearer\s+)[^\s\"']+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)((?:api[_-]?key|x-goog-api-key|authorization)[\s\"':=]+)[^\s,\"'}]+",
                   r"\1[REDACTED]", value)
    return value


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


def setup_logging(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("survey_sim")
    if not logger.handlers:
        handler = RotatingFileHandler(directory / "debug.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    # httpx debug logs can contain endpoints; do not enable them.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for name in ENV_NAMES.values():
        register_secret(os.getenv(name, ""))


class SecretStore:
    """Memory by default; persistent secrets only via OS credential storage."""
    def __init__(self):
        self.session: dict[str, str] = {}

    def put(self, config_id: str, key: str, persist: bool = False):
        register_secret(key)
        self.session[config_id] = key
        if persist:
            try:
                import keyring
                backend = keyring.get_keyring()
                if "Windows" not in type(backend).__name__ and os.name == "nt":
                    raise RuntimeError("Windows credential backend unavailable")
                keyring.set_password("AIQuestionnaireSimulator", config_id, key)
            except Exception as exc:
                raise AppError("金鑰已留在本次工作階段，但 Windows 認證管理員無法保存；請確認 keyring 安裝。") from exc

    def get(self, config_id: str, provider: str) -> str:
        key = self.session.get(config_id, "")
        if not key:
            try:
                import keyring
                key = keyring.get_password("AIQuestionnaireSimulator", config_id) or ""
            except Exception:
                pass
        return register_secret(key or os.getenv(ENV_NAMES.get(provider, ""), ""))

    def delete(self, config_id: str):
        self.session.pop(config_id, None)
        try:
            import keyring
            keyring.delete_password("AIQuestionnaireSimulator", config_id)
        except Exception:
            pass


def clean_url(url: str, *, api: bool = False) -> str:
    p = urlsplit(url.strip())
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise AppError("網址須為完整 HTTP(S) URL，不能含帳密。")
    if p.query or p.fragment:
        raise AppError("請移除網址的查詢參數及片段，避免保存金鑰或不穩定的對應。")
    if api and p.scheme != "https" and p.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise AppError("遠端 API 必須使用 HTTPS；HTTP 僅限本機。")
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", ""))
