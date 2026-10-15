from conftest import navigate
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from survey_sim.models import ProviderConfig
from survey_sim.personas import PersonaGenerator
from survey_sim.providers import make_provider


def test_all_nine_ui_pages_and_real_persona_button(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "ui-data"))
    from survey_sim.ui import runtime
    runtime.clear()
    app = AppTest.from_file(Path.cwd() / "app.py", default_timeout=20).run()
    assert not app.exception
    navigate(app, "虛擬人物管理")
    next(b for b in app.button if b.label == "生成並儲存人物").click().run()
    assert not app.exception
    assert len(runtime().db.list("persona")) == 10
    navigate(app, "AI 模擬控制台")
    next(b for b in app.button if b.label == "建立批次任務").click().run()
    next(b for b in app.button if b.label == "開始 / 繼續").click().run()
    rt = runtime()
    rt.runner.thread.join(timeout=20)
    assert rt.db.responses()
    for page in ["儀表板", "AI 模型設定", "問卷管理", "虛擬人物管理", "AI 模擬控制台", "回答檢查", "自動填表測試", "結果分析", "系統設定"]:
        navigate(app, page)
        assert not app.exception, page
        assert not app.error, (page, [e.value for e in app.error])
    runtime.clear()
