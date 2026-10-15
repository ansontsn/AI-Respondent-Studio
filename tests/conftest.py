import pytest

from survey_sim.examples import onlyframe_example
from survey_sim.models import ProviderConfig, TaskSpec
from survey_sim.personas import PersonaGenerator
from survey_sim.providers import make_provider
from survey_sim.storage import Database
from survey_sim.engine import AnswerEngine


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.sqlite3")


@pytest.fixture
def config():
    return ProviderConfig(id="mock-test")


@pytest.fixture
def persona(config):
    return PersonaGenerator(make_provider(config)).generate_one(42, "價格敏感型", "ONLYFRAME 小卡框")


@pytest.fixture
def questionnaire():
    return onlyframe_example()


@pytest.fixture
def spec(questionnaire, persona, config):
    return TaskSpec(questionnaire=questionnaire, personas=[persona], provider=config, interval_seconds=0)


@pytest.fixture
def saved_response(db, spec, persona, config):
    db.save("questionnaire", spec.questionnaire)
    db.save("persona", persona)
    task = db.create_task(spec)
    r = AnswerEngine(make_provider(config)).run(task, spec, persona)
    db.save_response(r)
    return r


def navigate(app, section):
    """Old feature tests access retained tools through the five-page navigation.
    Older tools and the ONLYFRAME options are in advanced mode."""
    main = section in {"問卷工作台", "人物資料庫", "問卷管理", "任務紀錄", "AI 模型設定"}
    app.radio(key="ui_mode").set_value("簡易模式" if main else "進階模式").run()
    if section == "虛擬人物管理":
        app.sidebar.radio[0].set_value("人物資料庫").run()
        app.radio(key="people_view").set_value("建立與編輯").run()
    elif section in {"問卷工作台", "人物資料庫", "問卷管理", "任務紀錄", "AI 模型設定"}:
        app.sidebar.radio[0].set_value(section).run()
    else:
        app.sidebar.radio[0].set_value("任務紀錄").run()
        app.selectbox(key="history_view").set_value(section).run()
    return app
