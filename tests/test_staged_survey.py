from conftest import navigate
import copy
import json

import pytest

import test_website_experience as website_tests
from survey_sim.batch import BatchRunner
from survey_sim.engine import AnswerEngine, Interrupted
from survey_sim.errors import AppError, AutomationError
from survey_sim.mock_ai import MockProvider
from survey_sim.mock_form import MockFormServer
from survey_sim.models import FormTarget, TaskSpec, WebsiteSurveyFlow, WebsiteWorkflow, Route, Condition, Question, QuestionType, Option
from survey_sim.personas import PersonaGenerator
from survey_sim.quality import regenerate
from survey_sim.security import SecretStore
from survey_sim.staged_survey import StagedSurveyRunner, FormSession
from survey_sim.website_experience import WebsiteExperience, staged_test_questionnaire, TEST_BINDINGS, TIERS

site = website_tests.site


@pytest.fixture
def three_site(site, monkeypatch):
    original = website_tests.HTML
    enhanced = original.replace("let color='',font='',txt='';", "let color='',font='',txt='',chosenTier='CUSTOM',bg='';")
    enhanced = enhanced.replace("function start(){body.innerHTML='<button onclick=\"editor()\">選擇此方案 (CUSTOM)</button>'}",
        "function start(){body.innerHTML='<button onclick=\"selectTier(\\\'BASIC\\\')\">選擇此方案 (BASIC)</button><button onclick=\"selectTier(\\\'CUSTOM\\\')\">選擇此方案 (CUSTOM)</button><button onclick=\"selectTier(\\\'PREMIUM\\\')\">選擇此方案 (PREMIUM)</button>'} function selectTier(t){chosenTier=t;editor();}")
    enhanced = enhanced.replace('<h1>CUSTOM｜文字客製</h1>', '<h1>${chosenTier}｜方案</h1>')
    enhanced = enhanced.replace('<button title="曜石黑">文字色</button>',
        '<button title="曜石黑">文字色</button><button>主題背景</button><button onclick="bg=\'晨光微曦漸層\'">晨光微曦漸層</button><button>裝飾貼飾</button><button aria-label="加入水晶四芒星" onclick="this.innerText=\'1 枚\'">貼飾</button>')
    enhanced = enhanced.replace('CUSTOM ${txt}', '${chosenTier} ${txt} ${bg}')
    enhanced = enhanced.replace("plan:'CUSTOM',custom_text:txt", "plan:chosenTier,custom_text:txt||'(未設定文字)'")
    monkeypatch.setattr(website_tests, "HTML", enhanced)
    return site


@pytest.fixture
def staged_spec(db, persona, config, three_site):
    q = staged_test_questionnaire()
    q.confirmed = True
    db.save("questionnaire", q)
    server = MockFormServer(db, 0).start()
    target = FormTarget(name="分階段測試", url=server.url(q.id), questionnaire_id=q.id, authorized=True)
    p = persona.model_copy(update={"onlyframe_tier": "CUSTOM", "onlyframe_tier_reason": "操作前選定文字客製。"}, deep=True)
    spec = TaskSpec(questionnaire=q, personas=[p], provider=config, interval_seconds=0,
        website_workflow=website_tests.workflow(three_site, mode="submit", authorized_test=True),
        website_fact_bindings=TEST_BINDINGS,
        website_survey=WebsiteSurveyFlow(after_page_id="scheme", tier_question_id="planned_tier",
            tier_options={tier.lower(): tier for tier in TIERS}, form_target=target, form_allowlist=[target.url], dry_run=False))
    yield spec
    server.close()


class SpyProvider(MockProvider):
    def __init__(self, config, trace=None):
        super().__init__(config)
        self.payloads = []
        self.trace = trace if trace is not None else []

    def generate(self, operation, payload, system):
        self.payloads.append(copy.deepcopy(payload))
        self.trace.append(payload["page"]["id"])
        result = super().generate(operation, payload, system)
        for answer in result.data["answers"]:
            if answer["question_id"] == "planned_tier":
                answer["value"] = "premium"  # Deliberate mismatch; fixed scheme must win.
            if answer["question_id"] == "site_tier":
                answer["value"] = "BASIC"
        return result


@pytest.mark.parametrize("preference,tier", [(.2,"BASIC"),(.5,"CUSTOM"),(.9,"PREMIUM")])
def test_generation_selects_and_saves_scheme_from_background(config, preference, tier):
    p = PersonaGenerator(MockProvider(config)).generate_one(736, "AI 自動混合", "ONLYFRAME",
        trait_overrides={"personalization": preference}, choose_website_tier=True)
    assert p.onlyframe_tier == tier and p.onlyframe_tier_reason
    generic = PersonaGenerator(MockProvider(config)).generate_one(736, "AI 自動混合", "ONLYFRAME")
    assert generic.onlyframe_tier is None and generic.id != p.id


@pytest.mark.browser
@pytest.mark.parametrize("tier", TIERS)
def test_three_tiers_fill_two_pages_then_website_then_same_form(db, staged_spec, tier, monkeypatch):
    spec = staged_spec
    spec.personas[0].onlyframe_tier = tier
    person = spec.personas[0]
    trace = []
    provider = SpyProvider(spec.provider, trace)
    original = WebsiteExperience.run
    def observe(self, workflow, persona, seed, should_continue, on_saved, browser=None):
        trace.append("website")
        form = browser.contexts[0].pages[0]
        before = form.evaluate("({current,answers,visited,token:window.testToken})")
        assert before["visited"] == ["background", "scheme"]
        assert before["answers"]["planned_tier"] == tier.lower()
        assert before["answers"]["person_name"] == person.name
        assert before["current"] == "experience"
        assert not db.rows("SELECT * FROM local_receipts")
        result = original(self, workflow, persona, seed, should_continue, on_saved, browser=browser)
        assert form.evaluate("({current,answers,visited,token:window.testToken})") == before
        return result
    monkeypatch.setattr(WebsiteExperience, "run", observe)
    task = db.create_task(spec)
    cp = {}
    result = StagedSurveyRunner(db, AnswerEngine(provider)).run(task, spec, person, cp, lambda: True)
    db.save_response(result)
    assert trace == ["background", "scheme", "website", "experience"]
    assert result.status == "passed" and result.form_result["status"] == "success"
    assert result.website_run.plan.tier == tier and result.website_run.contact_name == person.name
    assert all("website_experience" not in payload for payload in provider.payloads[:2])
    assert provider.payloads[2]["website_experience"]["方案"] == tier
    answers = {a.question_id:a.value for a in result.answers}
    assert answers["planned_tier"] == tier.lower() and answers["site_tier"] == tier
    received = json.loads(db.rows("SELECT answers FROM local_receipts")[0]["answers"])
    assert received["person_name"] == person.name and received["planned_tier"] == tier.lower() and received["site_tier"] == tier
    receipt = json.loads(open(result.website_run.receipt_file, encoding="utf-8").read())
    assert receipt["plan"] == tier and receipt["customer_name"] == person.name


@pytest.mark.browser
def test_pause_after_website_resumes_without_regeneration_or_design_resubmit(db, staged_spec, monkeypatch):
    spec, active, calls = staged_spec, [True], []
    original = WebsiteExperience.run
    def pause_after(self, *args, **kwargs):
        calls.append("website")
        result = original(self, *args, **kwargs)
        active[0] = False
        return result
    monkeypatch.setattr(WebsiteExperience, "run", pause_after)
    task, cp = db.create_task(spec), {}
    first = SpyProvider(spec.provider)
    with pytest.raises(Interrupted):
        StagedSurveyRunner(db, AnswerEngine(first)).run(task, spec, spec.personas[0], cp, lambda: active[0])
    assert cp["visited"] == ["background", "scheme"] and cp["website_run"]["status"] == "local_saved"
    original_answers = copy.deepcopy(cp["answers"])
    active[0] = True
    second = SpyProvider(spec.provider)
    result = StagedSurveyRunner(db, AnswerEngine(second)).run(task, spec, spec.personas[0], cp, lambda: True)
    assert [p["page"]["id"] for p in second.payloads] == ["experience"]
    assert [(a.question_id,a.value,a.rationale) for a in result.answers[:len(original_answers)]] == [(a["question_id"],a["value"],a["rationale"]) for a in original_answers]
    assert calls == ["website"] and len(db.rows("SELECT * FROM local_receipts")) == 1


@pytest.mark.browser
def test_failed_design_stops_experience_answers_and_keeps_pre_pages(db, staged_spec, three_site):
    spec = staged_spec
    three_site["mode"] = "rejected"
    spec.website_workflow.submission_endpoint = three_site["url"].rstrip("/") + "/rest/v1/design_submissions"
    task, cp, provider = db.create_task(spec), {}, SpyProvider(spec.provider)
    with pytest.raises(AutomationError):
        StagedSurveyRunner(db, AnswerEngine(provider)).run(task, spec, spec.personas[0], cp, lambda: True)
    assert [p["page"]["id"] for p in provider.payloads] == ["background", "scheme"]
    assert cp["visited"] == ["background", "scheme"] and cp["next_page"] == "experience"
    assert not db.rows("SELECT * FROM local_receipts")
    assert cp["website_run"]["status"] not in {"local_saved", "server_confirmed"}


@pytest.mark.browser
def test_successful_form_resume_before_response_save_does_not_submit_twice(db, staged_spec):
    spec, cp = staged_spec, {}
    task = db.create_task(spec)
    first = StagedSurveyRunner(db, AnswerEngine(SpyProvider(spec.provider))).run(task, spec, spec.personas[0], cp, lambda: True)
    second = StagedSurveyRunner(db, AnswerEngine(SpyProvider(spec.provider))).run(task, spec, spec.personas[0], cp, lambda: True)
    assert first.id == second.id and second.form_result["status"] == "success"
    assert len(db.rows("SELECT * FROM local_receipts")) == 1 and len(db.rows("SELECT * FROM submissions")) == 1


@pytest.mark.browser
def test_unknown_form_receipt_blocks_retry_without_new_provider_or_website_calls(db, staged_spec, monkeypatch):
    original = db.finish_submission
    def lost_ack(id, status, message, artifact=""):
        original(id, "unknown" if status == "success" else status, message, artifact)
        if status == "success":
            raise AutomationError("測試：問卷提交後核對中斷")
    monkeypatch.setattr(db, "finish_submission", lost_ack)
    spec, cp = staged_spec, {}
    task = db.create_task(spec)
    with pytest.raises(AutomationError):
        StagedSurveyRunner(db, AnswerEngine(SpyProvider(spec.provider))).run(task, spec, spec.personas[0], cp, lambda: True)
    assert cp["completed_response"] and len(db.rows("SELECT * FROM local_receipts")) == 1
    spy = SpyProvider(spec.provider)
    with pytest.raises(AutomationError, match="禁止自動重送"):
        StagedSurveyRunner(db, AnswerEngine(spy)).run(task, spec, spec.personas[0], cp, lambda: True)
    assert not spy.payloads and len(db.rows("SELECT * FROM local_receipts")) == 1


@pytest.mark.parametrize("error", ["missing_tier", "last_page", "post_tier", "assignments", "duplicate_options", "wrong_target"])
def test_bad_stage_setup_rejected_before_any_browser_effect(db, staged_spec, error):
    spec = staged_spec
    if error == "missing_tier": spec.personas[0].onlyframe_tier = None
    if error == "last_page": spec.website_survey.after_page_id = "experience"
    if error == "post_tier": spec.website_survey.tier_question_id = "site_tier"
    if error == "assignments": spec.website_tier_assignments = {spec.personas[0].id:"BASIC"}
    if error == "duplicate_options": spec.website_survey.tier_options = {"basic":"CUSTOM","custom":"CUSTOM","premium":"PREMIUM"}
    if error == "wrong_target": spec.website_survey.form_target.questionnaire_id = "other"
    with pytest.raises(AppError): db.create_task(spec)
    assert not db.list("website_run")


def test_fixed_persona_scheme_also_wins_in_legacy_website_operations(db, persona, config):
    from survey_sim.website_experience import workflow_for_person, website_test_questionnaire
    person = persona.model_copy(update={"onlyframe_tier": "BASIC"})
    q = website_test_questionnaire(); q.confirmed = True
    spec = TaskSpec(questionnaire=q, personas=[person], provider=config, website_workflow=WebsiteWorkflow(tier="PREMIUM"))
    assert workflow_for_person(spec, person.id).tier == "BASIC"
    spec.website_tier_assignments = {person.id:"CUSTOM"}
    with pytest.raises(AppError, match="固定方案"): db.create_task(spec)


@pytest.mark.browser
def test_quality_regeneration_preserves_pre_answers_and_never_resubmits_form_or_design(db, staged_spec):
    spec = staged_spec
    task = db.create_task(spec)
    runner = BatchRunner(db, SecretStore())
    runner.start(task); runner.thread.join(30)
    assert db.task(task)["status"] == "completed"
    result = db.responses(task)[0]
    repaired_task = regenerate(db, [result.id], seed=555)
    repaired_spec = TaskSpec.model_validate_json(db.task(repaired_task)["spec"])
    assert repaired_spec.website_survey.dry_run
    runner.start(repaired_task); runner.thread.join(30)
    assert db.task(repaired_task)["status"] == "completed"
    repaired = db.responses(repaired_task)[0]
    assert repaired.website_run.id == result.website_run.id
    assert {a.question_id:a.value for a in repaired.answers[:3]} == {a.question_id:a.value for a in result.answers[:3]}
    assert len(db.rows("SELECT * FROM local_receipts")) == 1 and len(db.list("website_run")) == 1
    assert repaired.form_result["status"] == "dry_run"


@pytest.mark.browser
def test_early_exit_does_not_trigger_website_experience(db, staged_spec):
    spec = staged_spec
    consent = Question(id="consent", title="測試參與", type=QuestionType.SINGLE, options=[Option(id="no",label="不參與")])
    spec.questionnaire.pages[0].questions = [consent]
    spec.questionnaire.pages[0].routes = [Route(when=Condition(question_id="consent", value="no"), target="END")]
    db.save("questionnaire", spec.questionnaire)
    task = db.create_task(spec)
    result = StagedSurveyRunner(db, AnswerEngine(MockProvider(spec.provider))).run(task, spec, spec.personas[0], {}, lambda: True)
    assert result.visited_pages == ["background"] and result.website_run is None
    assert not db.list("website_run") and result.form_result["status"] == "success"


@pytest.mark.browser
def test_scheme_question_can_follow_website_and_name_is_fixed(db, staged_spec):
    spec = staged_spec
    # A real questionnaire can ask which scheme was used only after the experience.
    spec.questionnaire.pages[1].questions = [Question(id="before_preferences", title="操作前偏好", type=QuestionType.PARAGRAPH)]
    spec.questionnaire.pages[0].questions[0].persona_field = ""
    spec.website_survey.tier_question_id = "site_tier"
    spec.website_survey.tier_options = {tier:tier for tier in TIERS}
    spec.website_survey.name_question_id = "person_name"
    db.save("questionnaire", spec.questionnaire)
    task, cp = db.create_task(spec), {}
    provider = SpyProvider(spec.provider)
    result = StagedSurveyRunner(db, AnswerEngine(provider)).run(task, spec, spec.personas[0], cp, lambda: True)
    received = json.loads(db.rows("SELECT answers FROM local_receipts")[0]["answers"])
    assert received["person_name"] == spec.personas[0].name and received["site_tier"] == "CUSTOM"
    assert result.website_run.plan.tier == "CUSTOM" and result.form_result["status"] == "success"
    assert "website_experience" not in provider.payloads[1] and "website_experience" in provider.payloads[2]
    assert any(change["kind"] == "persona_identity" for change in result.repair_history)


def test_ui_generates_fixed_schemes_and_creates_staged_task(tmp_path, monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from survey_sim.ui import runtime
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "staged-ui"))
    monkeypatch.setenv("MOCK_FORM_PORT", "0")
    runtime.clear()
    rt = runtime()
    q = staged_test_questionnaire(); q.confirmed = True
    rt.db.save("questionnaire", q)
    rt.db.save("website_workflow", WebsiteWorkflow())
    app = AppTest.from_file(Path.cwd() / "app.py", default_timeout=30).run()
    try:
        navigate(app, "虛擬人物管理")
        next(item for item in app.checkbox if item.label == "生成時由 AI 選定 ONLYFRAME 方案，之後固定沿用").set_value(True).run()
        next(item for item in app.number_input if item.label == "人物數量").set_value(3).run()
        next(button for button in app.button if button.label == "生成並儲存人物").click().run()
        assert not app.exception and not app.error
        people = rt.db.list("persona")
        assert len(people) == 3 and all(p.onlyframe_tier and p.onlyframe_tier_reason for p in people)
        navigate(app, "網站體驗模擬")
        next(item for item in app.selectbox if item.key == "website_q").set_value(q.id).run()
        next(item for item in app.multiselect if item.label == "網站操作人物").set_value([p.id for p in people]).run()
        assert next(item for item in app.checkbox if item.key == "website_survey_enabled").value
        next(button for button in app.button if button.label == "建立網站操作與答題任務").click().run()
        assert not app.exception and not app.error
        task = TaskSpec.model_validate_json(rt.db.rows("SELECT spec FROM tasks")[0]["spec"])
        assert task.website_survey.after_page_id == "scheme" and not task.website_tier_assignments
        assert task.website_survey.tier_options == {tier.lower():tier for tier in TIERS}
        assert task.website_fact_bindings == TEST_BINDINGS
        assert {p.id:p.onlyframe_tier for p in task.personas} == {p.id:p.onlyframe_tier for p in people}
        assert not rt.db.list("website_run")
    finally:
        if rt.mock_server: rt.mock_server.close()
        runtime.clear()
