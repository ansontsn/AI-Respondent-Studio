import hashlib

from .errors import AppError
from .models import TaskSpec
from .storage import dump


def provider_ready(config, secrets):
    if config.provider == "mock":
        return True, "Mock 可直接操作"
    if not config.model.strip():
        return False, "尚未指定模型"
    if config.provider == "compatible" and not config.base_url:
        return False, "尚未設定 Base URL"
    if config.provider in {"ollama", "compatible"}:
        return True, "設定已填寫，實際可用性請測試連線"
    return (True, "已設定金鑰，請測試連線") if secrets.get(config.id, config.provider) else (False, "尚未設定 API Key")


def fingerprint(spec):
    return hashlib.sha256(dump(spec).encode()).hexdigest()


def validated_plan(q, personas, config, **parameters):
    if not q.confirmed:
        raise AppError("此問卷尚未人工確認，請先到問卷管理的預覽與確認。")
    if not personas:
        raise AppError("請至少選擇一位已儲存的人物。")
    # Also protect callers whose cached TaskSpec predates reload-safe validators.
    from pydantic import BaseModel
    def snapshot(item):
        return item.model_dump(mode="json") if isinstance(item, BaseModel) else item
    return TaskSpec(questionnaire=snapshot(q), personas=[snapshot(p) for p in personas], provider=snapshot(config),
                    **{key: snapshot(value) for key, value in parameters.items()})
