from conftest import navigate
from pathlib import Path

from streamlit.testing.v1 import AppTest

from survey_sim.models import ProviderConfig, Scenario
from survey_sim.personas import PersonaGenerator
from survey_sim.providers import make_provider
from survey_sim.v2_models import Experiment, ExperimentCell
from survey_sim.experiments import ExperimentService


def prepared_runtime(tmp_path,monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR",str(tmp_path/"v2-ui-data"))
    from survey_sim.ui import runtime
    runtime.clear();rt=runtime()
    c=rt.db.get("provider","mock-default")
    people=PersonaGenerator(make_provider(c)).generate_batch(3,500,"一般",{"AI 自動混合":1})
    for p in people:rt.db.save("persona",p)
    return rt,runtime,c,people


def click(app,label):
    next(b for b in app.button if b.label==label).click().run()
    assert not app.exception
    assert not app.error,[e.value for e in app.error]


def test_six_step_wizard_executes_preview_then_batch(tmp_path,monkeypatch):
    rt,runtime,c,people=prepared_runtime(tmp_path,monkeypatch)
    app=AppTest.from_file(Path.cwd()/"app.py",default_timeout=30).run()
    navigate(app, "快速開始")
    click(app,"下一步：選擇模型");click(app,"下一步：受訪者");click(app,"下一步：模擬參數");click(app,"下一步：預覽測試")
    click(app,"執行一人預覽")
    rt.runner.thread.join(timeout=10)
    app.run()
    click(app,"確認預覽，下一步");click(app,"開始完整模擬")
    rt.runner.thread.join(timeout=10)
    assert len(rt.db.responses())==4
    assert app.session_state["wizard"]["step"]==5
    runtime.clear()


def test_all_v2_pages_with_real_experiment_and_motivation_actions(tmp_path,monkeypatch):
    rt,runtime,c,people=prepared_runtime(tmp_path,monkeypatch)
    other=ProviderConfig(id="mock-ui-2",name="第二個 Mock")
    rt.db.save("provider",other)
    q=rt.db.get("questionnaire","onlyframe-demo-v1")
    service=ExperimentService(rt.db)
    model=service.create(Experiment(name="UI 模型比較",kind="model",questionnaire=q,personas=people,cells=[ExperimentCell(label="A",provider=c),ExperimentCell(label="B",provider=other)]),0)
    scenario=service.create(Experiment(name="UI 情境比較",kind="scenario",questionnaire=q,personas=people,cells=[
        ExperimentCell(label="A",provider=c,scenario=Scenario(name="A",description="基本",attributes={"price":200})),
        ExperimentCell(label="B",provider=c,scenario=Scenario(name="B",description="客製",attributes={"price":800,"customization":1}))]),0)
    rt.runner.start_group([x.task_id for e in [model,scenario] for x in e.cells]);rt.runner.thread.join(timeout=10)
    def reject_full_response_load(*args, **kwargs):
        raise AssertionError("儀表板計數不應載入完整回答快照")
    with monkeypatch.context() as patch:
        patch.setattr(rt.db, "responses", reject_full_response_load)
        app=AppTest.from_file(Path.cwd()/"app.py",default_timeout=30).run()
        navigate(app, "儀表板")
        assert not app.exception and not app.error
        metrics = {m.label: int(m.value) for m in app.metric}
        assert metrics["虛擬人物"] == len(people)
        assert metrics["已保存回答"] == len(people) * (len(model.cells) + len(scenario.cells))
    for page in ["儀表板","快速開始","AI 模型設定","問卷管理","虛擬人物管理","AI 模擬控制台","回答檢查","回答品質","模型比較","動機分析","情境實驗","網站體驗模擬","自動填表測試","結果分析","系統設定"]:
        navigate(app, page)
        assert not app.exception,page
        assert not app.error,(page,[e.value for e in app.error])
        if page=="動機分析":
            click(app,"分析回答動機")
            assert rt.setting("motivation_report_"+app.session_state["motivation_task"])
            click(app,"準備分析報告下載")
    navigate(app, "AI 模型設定")
    app.sidebar.radio[1].set_value("進階模式").run()
    assert not app.exception and not app.error
    assert any(b.label=="儲存設定" for b in app.button)
    runtime.clear()


def test_conditional_generation_button_and_simple_provider_save(tmp_path,monkeypatch):
    rt,runtime,c,people=prepared_runtime(tmp_path,monkeypatch)
    app=AppTest.from_file(Path.cwd()/"app.py",default_timeout=30).run()
    navigate(app, "虛擬人物管理")
    next(x for x in app.checkbox if x.label=="啟用受訪者條件與分布控制").set_value(True).run()
    next(x for x in app.checkbox if x.label=="指定每月所得範圍").set_value(True).run()
    click(app,"生成並儲存人物")
    controlled=[p for p in rt.db.list("persona") if "generation_conditions" in p.topic_attributes]
    assert len(controlled)==10 and all(18<=p.background.age<=65 for p in controlled)
    navigate(app, "AI 模型設定")
    click(app,"儲存模型設定")
    assert len(rt.db.list("provider"))==2
    runtime.clear()
