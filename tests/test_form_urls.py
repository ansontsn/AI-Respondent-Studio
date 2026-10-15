from conftest import navigate
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from survey_sim.automation import check_policy
from survey_sim.engine import AnswerEngine
from survey_sim.errors import AppError
from survey_sim.models import FormTarget
from survey_sim.providers import make_provider
from survey_sim.security import clean_form_url, clean_url


FORM = "https://docs.google.com/forms/d/e/TEST_FORM_ID/viewform"


@pytest.mark.parametrize("parameter", ["dialog", "sf_link", "send_form", "sharing", "pp_url"])
def test_google_responder_sharing_parameters_have_one_canonical_url(parameter):
    assert clean_form_url(FORM + "?usp=" + parameter) == FORM
    assert clean_form_url(FORM + "/?usp=" + parameter) == FORM
    assert clean_form_url(FORM) == FORM


@pytest.mark.parametrize("url", [
    FORM + "?api_key=not-a-real-key",
    FORM + "?usp=dialog&api_key=not-a-real-key",
    FORM + "?usp=pp_url&entry.123=pre-filled",
    FORM + "?entry.123=pre-filled",
    FORM + "?usp=dialog#fragment",
    FORM + "?usp=unknown",
    FORM + "?usp=",
    FORM + "?usp=dialog&broken",
    FORM.replace("viewform", "edit") + "?usp=dialog",
    FORM.replace("docs.google.com", "example.com") + "?usp=dialog",
    FORM.replace("https:", "http:") + "?usp=dialog",
    FORM.replace("docs.google.com", "person:password@docs.google.com") + "?usp=dialog",
])
def test_unrecognized_parameters_prefill_and_credentials_remain_rejected(url):
    with pytest.raises(AppError):
        clean_form_url(url)


def test_provider_url_validation_stays_strict():
    with pytest.raises(AppError):
        clean_url(FORM + "?usp=dialog", api=True)


@pytest.mark.parametrize("target_suffix,allowed_suffix", [("?usp=dialog", ""), ("", "?usp=sf_link"), ("?usp=dialog", "?usp=send_form")])
def test_saved_form_and_allowlist_compare_canonical_google_urls(saved_response, target_suffix, allowed_suffix):
    target = FormTarget(name="Google 測試", url=FORM + target_suffix, questionnaire_id=saved_response.questionnaire_id, kind="google", authorized=True)
    assert check_policy(target, saved_response, [FORM + allowed_suffix], dry_run=True) == FORM


def test_google_form_id_still_must_match_allowlist(saved_response):
    target = FormTarget(name="Google 測試", url=FORM + "?usp=dialog", questionnaire_id=saved_response.questionnaire_id, kind="google", authorized=True)
    with pytest.raises(AppError, match="未列入允許清單"):
        check_policy(target, saved_response, [FORM.replace("TEST_FORM_ID", "OTHER_FORM_ID") + "?usp=dialog"], dry_run=True)


def test_sharing_parameter_cannot_bypass_duplicate_submission_guard(db, saved_response):
    target = FormTarget(name="Google 測試", url=FORM + "?usp=dialog", questionnaire_id=saved_response.questionnaire_id, kind="google", authorized=True)
    id = db.reserve_submission(saved_response.id, target, False)
    db.finish_submission(id, "unknown", "本機測試：提交結果不明")
    target.url = FORM + "?usp=sf_link"
    with pytest.raises(AppError, match="重複提交"):
        db.reserve_submission(saved_response.id, target, False)
    assert db.rows("SELECT url FROM submissions")[0]["url"] == FORM


def test_ui_saves_shared_google_link_and_matching_allowlist(tmp_path, monkeypatch):
    from survey_sim.ui import runtime
    from survey_sim.personas import PersonaGenerator
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "url-ui"))
    runtime.clear()
    rt = runtime()
    c = rt.db.get("provider", "mock-default")
    q = rt.db.get("questionnaire", "onlyframe-demo-v1")
    p = PersonaGenerator(make_provider(c)).generate_one(975, "AI 自動混合", q.topic)
    from survey_sim.models import TaskSpec
    spec = TaskSpec(questionnaire=q, personas=[p], provider=c)
    task = rt.db.create_task(spec)
    rt.db.save_response(AnswerEngine(make_provider(c)).run(task, spec, p))
    app = AppTest.from_file(Path.cwd() / "app.py", default_timeout=30).run()
    try:
        navigate(app, "自動填表測試")
        next(item for item in app.selectbox if item.label == "測試表單").set_value("new").run()
        next(item for item in app.text_input if item.label == "完整測試 URL").set_value(FORM + "?usp=dialog")
        next(item for item in app.checkbox if item.label == "我確認這是自有或明確授權的測試表單，允許送入虛擬答案").set_value(True)
        next(button for button in app.button if button.label == "保存測試表單").click().run()
        assert not app.exception and not app.error
        target = rt.db.list("target")[0]
        assert target.url == FORM and target.authorized
        next(item for item in app.text_area if item.label.startswith("URL Allowlist")).set_value(FORM + "?usp=dialog")
        next(button for button in app.button if button.label == "保存允許清單").click().run()
        assert not app.exception and not app.error
        assert rt.setting("url_allowlist") == [FORM]
    finally:
        runtime.clear()
