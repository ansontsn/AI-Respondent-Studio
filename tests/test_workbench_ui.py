import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from survey_sim.personas import PersonaGenerator
from survey_sim.examples import general_example
from survey_sim.providers import make_provider


def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "workbench-ui"))
    from survey_sim.ui import runtime
    runtime.clear()
    rt = runtime()
    config = rt.db.get("provider", "mock-default")
    people = PersonaGenerator(make_provider(config)).generate_batch(3, 700, "一般", {"AI 自動混合": 1})
    for person in people:
        rt.db.save("persona", person)
    app = AppTest.from_file(Path.cwd() / "app.py", default_timeout=30).run()
    assert not app.exception and not app.error
    return rt, runtime, people, app


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception and not app.error


def test_five_pages_group_selection_and_one_click_answers(tmp_path, monkeypatch):
    rt, runtime, people, app = setup(tmp_path, monkeypatch)
    try:
        assert app.sidebar.radio[0].options == ["問卷工作台", "人物資料庫", "問卷管理", "任務紀錄", "AI 模型設定"]
        app.sidebar.radio[0].set_value("人物資料庫").run()
        click(app, "全選篩選結果")
        app.text_input(key="library_group_name").set_value("常用測試人物").run()
        click(app, "儲存人物群組")
        assert rt.db.list("persona_group")[0].persona_ids == [p.id for p in rt.db.list("persona")]
        click(app, "使用這些人物進入問卷工作台")
        assert len(app.multiselect(key="wb_people_selection").value) == 3
        app.selectbox(key="wb_questionnaire").set_value(general_example().id).run()
        app.number_input(key="wb_interval").set_value(0.).run()
        click(app, "開始批次處理")
        rt.runner.thread.join(timeout=20)
        app.run()
        assert not app.exception and not app.error
        assert len(rt.db.responses()) == 3 and not rt.db.rows("SELECT * FROM submissions")
        assert len(app.get("download_button")) >= 3
        job_id = rt.setting("latest_workbench_job")
        app.run()
        assert rt.setting("latest_workbench_job") == job_id and len(rt.db.responses()) == 3
        for page in app.sidebar.radio[0].options:
            app.sidebar.radio[0].set_value(page).run()
            assert not app.exception and not app.error, page
    finally:
        runtime.clear()


def test_ui_generates_new_people_and_submit_requires_explicit_confirmation(tmp_path, monkeypatch):
    rt, runtime, people, app = setup(tmp_path, monkeypatch)
    try:
        app.radio(key="wb_source").set_value("AI 自動建立人物").run()
        app.number_input(key="wb_count").set_value(2).run()
        app.selectbox(key="wb_questionnaire").set_value(general_example().id).run()
        app.number_input(key="wb_interval").set_value(0.).run()
        click(app, "開始批次處理")
        rt.runner.thread.join(timeout=20)
        app.run()
        assert not app.exception and not app.error
        assert len(rt.db.list("persona")) == 5 and len(rt.db.responses()) == 2
        app.selectbox(key="wb_mode").set_value("submit").run()
        assert next(b for b in app.button if b.label == "開始批次處理（實際提交）").disabled
        assert not rt.db.rows("SELECT * FROM submissions")
    finally:
        runtime.clear()


def test_google_url_parses_in_workbench_without_navigation_or_submission(tmp_path, monkeypatch):
    from survey_sim import parsers
    rt, runtime, people, app = setup(tmp_path, monkeypatch)
    try:
        q = rt.db.get("questionnaire", general_example().id).model_copy(deep=True)
        q.confirmed = False
        q.source_url = "https://docs.google.com/forms/d/e/owned-test/viewform"
        calls = []
        monkeypatch.setattr(parsers, "import_google", lambda url: calls.append(url) or q)
        app.radio(key="wb_questionnaire_source").set_value("Google Forms 網址").run()
        app.text_input(key="wb_url").set_value(q.source_url).run()
        assert calls == [q.source_url]
        app.checkbox(key="wb_confirm_" + q.id + str(q.revision)).set_value(True).run()
        app.multiselect(key="wb_people_selection").set_value([people[0].id]).run()
        app.number_input(key="wb_interval").set_value(0.).run()
        click(app, "開始批次處理")
        rt.runner.thread.join(timeout=20)
        app.run()
        assert not app.exception and not app.error
        assert len(rt.db.responses()) == 1 and calls == [q.source_url]
        assert not rt.db.rows("SELECT * FROM submissions")
        app.selectbox(key="wb_mode").set_value("submit").run()
        app.selectbox(key="wb_destination").set_value("這份 Google Forms").run()
        assert app.text_input(key="wb_success_text").value == ""
        assert next(b for b in app.button if b.label == "開始批次處理（實際提交）").disabled
    finally:
        runtime.clear()


def test_previous_unsent_uncertainty_answers_can_be_selected_without_sending(tmp_path, monkeypatch):
    from survey_sim.engine import AnswerEngine
    from survey_sim.models import TaskSpec
    from survey_sim.storage import dump
    from survey_sim.validator import AnswerValidator
    from survey_sim.v2_models import WorkbenchSpec
    from survey_sim.workbench import WorkbenchService

    rt, runtime, people, app = setup(tmp_path, monkeypatch)
    try:
        q = general_example()
        config = rt.db.get("provider", "mock-default")
        source = TaskSpec(questionnaire=q, personas=[people[0]], provider=config, interval_seconds=0)
        task_id = rt.db.create_task(source)
        response = AnswerEngine(make_provider(config)).run(task_id, source, people[0])
        response.answers[0].uncertain = True
        response.answers, response.issues, response.visited_pages, response.status = AnswerValidator().validate(
            q, people[0], response.answers)
        assert response.status == "review" and {i.code for i in response.issues} == {"uncertainty"}
        rt.db.save_response(response)
        rt.db.execute("UPDATE task_items SET status='skipped',error='答案尚需修正或人工檢查' WHERE task_id=?",
            (task_id,))
        job_id = WorkbenchService(rt.db, rt.secrets).create(
            WorkbenchSpec(questionnaire=q, provider=config, personas=[people[0]]))
        rt.db.execute("UPDATE workbench_jobs SET checkpoint=? WHERE id=?", (dump({"task_ids": [task_id]}), job_id))
        rt.set_setting("latest_workbench_job", job_id)
        app.selectbox(key="wb_mode").set_value("submit").run()
        app.radio(key="wb_source").set_value("使用已驗證答案").run()
        app.selectbox(key="wb_questionnaire").set_value(q.id).run()
        click(app, "帶入上一批未送出的不確定答案")
        assert app.multiselect(key="wb_responses").value == [response.id]
        assert not rt.db.rows("SELECT * FROM submissions")
    finally:
        runtime.clear()


def test_cached_runtime_upgrades_database_and_worker_without_losing_session_keys(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from survey_sim.storage import Database
    rt, runtime, people, app = setup(tmp_path, monkeypatch)
    try:
        class OlderDatabase(Database):
            pass
        rt.db = OlderDatabase(rt.db.path)
        rt.runner = SimpleNamespace(thread=None)
        secrets = rt.secrets
        secrets.put("cached-test", "synthetic-session-secret")
        app.run()
        assert not app.exception and not app.error
        assert type(rt.db) is Database and hasattr(rt.runner, "_fill_response")
        assert rt.secrets is secrets and secrets.session["cached-test"] == "synthetic-session-secret"
        assert len(rt.db.list("persona")) == len(people)
    finally:
        runtime.clear()


def test_partial_persona_failure_is_counted_in_final_ui_totals(tmp_path, monkeypatch):
    from survey_sim.errors import AppError
    rt, runtime, people, app = setup(tmp_path, monkeypatch)
    original = PersonaGenerator.generate_one
    def fail_one(self, seed, *args, **kwargs):
        if seed == 43:
            raise AppError("temporary generation error")
        return original(self, seed, *args, **kwargs)
    monkeypatch.setattr(PersonaGenerator, "generate_one", fail_one)
    try:
        app.radio(key="wb_source").set_value("AI 自動建立人物").run()
        app.number_input(key="wb_count").set_value(2).run()
        app.selectbox(key="wb_questionnaire").set_value(general_example().id).run()
        app.number_input(key="wb_interval").set_value(0.).run()
        click(app, "開始批次處理")
        rt.runner.thread.join(timeout=20)
        app.run()
        assert not app.exception and not app.error
        metrics = {m.label: int(m.value) for m in app.metric}
        assert metrics["任務總數"] == 2 and metrics["失敗"] == 1 and metrics["已完成 / 略過"] == 1
    finally:
        runtime.clear()
