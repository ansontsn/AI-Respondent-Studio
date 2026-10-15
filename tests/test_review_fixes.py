"""Regression tests for defects found in the V2 code review."""
import json
import os

import httpx
import pytest

from survey_sim import batch as batch_module, providers as provider_module, workbench as workbench_module
from survey_sim.batch import BatchRunner
from survey_sim.errors import AppError
from survey_sim.examples import general_example
from survey_sim.mock_ai import MockProvider
from survey_sim.models import FormTarget, ProviderConfig, TaskSpec
from survey_sim.personas import mock_background, mock_persona
from survey_sim.questionnaire_review import confirm_questionnaire
from survey_sim.security import SecretStore
from survey_sim.v2_models import WorkbenchSpec
from survey_sim.workbench import WorkbenchService


def people(count):
    return [mock_persona(mock_background(i), i, "AI 自動混合") for i in range(count)]


class FakeOpenAI:
    """Local OpenAI wire replica: a fixed error status, or Mock answers once 'fixed'."""
    def __init__(self, status, headers=None):
        self.status, self.headers, self.requests = status, headers or {}, 0

    def __call__(self, request):
        self.requests += 1
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "simulated"}}, headers=self.headers)
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        operation = "persona" if "background" in payload and "schema" in payload and "archetype" in payload and "trait_overrides" in payload else \
            "background" if "schema" in payload else "answer_page"
        data = MockProvider(ProviderConfig()).generate(operation, payload, "").data
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(data, ensure_ascii=False)}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 10}})


@pytest.fixture
def fake_openai(monkeypatch):
    holder = {}
    original = provider_module.make_provider
    def make(config, key="", db=None, task_id="", transport=None):
        return original(config, "sk-simulated", db, task_id, transport=httpx.MockTransport(holder["server"]))
    monkeypatch.setattr(batch_module, "make_provider", make)
    monkeypatch.setattr(provider_module, "make_provider", make)
    return holder


OPENAI = ProviderConfig(id="openai-test", provider="openai", model="simulated", retries=2, request_interval=0)


class FakeWindowsBackend:
    pass


FakeWindowsBackend.__module__ = "keyring.backends.Windows"
FakeWindowsBackend.__name__ = "WinVaultKeyring"


def test_windows_credential_manager_backend_is_accepted(monkeypatch):
    import keyring
    saved = {}
    monkeypatch.setattr(keyring, "get_keyring", lambda: FakeWindowsBackend())
    monkeypatch.setattr(keyring, "set_password", lambda service, user, key: saved.update({(service, user): key}))
    SecretStore().put("config-1", "secret-value", persist=True)
    assert saved == {("AIQuestionnaireSimulator", "config-1"): "secret-value"}


@pytest.mark.skipif(os.name != "nt", reason="the plaintext-backend refusal applies to Windows")
def test_non_windows_backend_is_still_refused_on_windows(monkeypatch):
    import keyring

    class PlaintextKeyring:
        pass
    monkeypatch.setattr(keyring, "get_keyring", lambda: PlaintextKeyring())
    monkeypatch.setattr(keyring, "set_password", lambda *args: pytest.fail("must not write"))
    with pytest.raises(AppError, match="認證管理員無法保存"):
        SecretStore().put("config-1", "secret-value", persist=True)


def test_workbench_inline_confirmation_mismatch_is_blocked_before_any_ai_call(db):
    q = general_example(); q.confirmed = False
    db.save("questionnaire", q)
    inline = confirm_questionnaire(q.model_copy(deep=True), True)
    target = FormTarget(name="local", url=f"http://127.0.0.1:8765/form/{q.id}", questionnaire_id=q.id, authorized=True,
                        success_selector="#success[data-receipt]")
    spec = WorkbenchSpec(questionnaire=inline, provider=ProviderConfig(), personas=people(1), mode="dry_run",
                         form_target=target, form_allowlist=[target.url])
    service = WorkbenchService(db, SecretStore())
    with pytest.raises(AppError, match="問卷管理"):
        service.create(spec)
    assert not db.rows("SELECT id FROM workbench_jobs") and not db.rows("SELECT id FROM tasks")
    db.save("questionnaire", inline)  # what the workbench checkbox now persists
    assert service.create(spec)


@pytest.mark.parametrize("status,headers,expected_requests", [(401, {}, 1), (402, {}, 1), (429, {"Retry-After": "0"}, 3)])
def test_service_wide_api_error_pauses_once_and_resumes(db, fake_openai, status, headers, expected_requests):
    q = general_example(); q.confirmed = True
    server = fake_openai["server"] = FakeOpenAI(status, headers)
    task = db.create_task(TaskSpec(questionnaire=q, personas=people(4), provider=OPENAI, interval_seconds=0))
    runner = BatchRunner(db, SecretStore())
    runner.start(task); runner.thread.join(30)
    items = db.rows("SELECT status,error FROM task_items WHERE task_id=?", (task,))
    assert db.task(task)["status"] == "provider_paused"
    assert server.requests == expected_requests
    assert [i["status"] for i in items] == ["pending"] * 4 and items[0]["error"]
    server.status = 200  # the user fixes the key / quota
    runner.start(task); runner.thread.join(30)
    assert db.task(task)["status"] == "completed"
    assert len(db.responses(task)) == 4


def test_workbench_generation_pauses_on_invalid_key_without_failing_everyone(db, fake_openai):
    fake_openai["server"] = FakeOpenAI(401)
    service = WorkbenchService(db, SecretStore())
    runner = BatchRunner(db, service.secrets)
    job = service.create(WorkbenchSpec(provider=OPENAI, generate_count=5, mode="personas"))
    service.start(job, runner); runner.thread.join(30)
    row = service.job(job)
    generation = json.loads(row["checkpoint"])["generation"]
    assert row["status"] == "paused" and "API Key" in row["error"]
    assert [g["status"] for g in generation] == ["pending"] * 5
    assert fake_openai["server"].requests == 1


# ---- C-02: custom forms (strictly local replica servers) ----
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

from survey_sim.automation import FormAutomation, FormNetworkGuard
from survey_sim.engine import AnswerEngine
from survey_sim.errors import AutomationError
from survey_sim.models import Binding, Page, Question, QuestionType, Questionnaire

FORM = '<!doctype html><meta charset="utf-8"><form method="post" action="{action}"><div id="{qid}"><h3>{title}</h3><input type="text" name="{qid}"></div><button type="submit">{button}</button></form>'


@pytest.fixture
def custom_server():
    state = {"posts": [], "gets": []}
    pages = {"/": FORM.format(action="/thanks", qid="q1", title="意見", button="提交"),
             "/multi": FORM.format(action="/multi/2", qid="q1", title="意見", button="下一頁"),
             "/leak": FORM.format(action="/thanks", qid="q1", title="意見", button="提交") + "<script>location.href='/elsewhere'</script>"}
    class Handler(BaseHTTPRequestHandler):
        def html(self, body):
            self.send_response(200); self.send_header("Content-Type", "text/html;charset=utf-8"); self.end_headers(); self.wfile.write(body.encode())
        def do_GET(self):
            state["gets"].append(self.path); self.html(pages.get(self.path, "<p>other page</p>"))
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0))); state["posts"].append(self.path)
            self.html(FORM.format(action="/multi/done", qid="q2", title="建議", button="提交") if self.path == "/multi/2" else "<p>感謝填寫</p>")
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    state["base"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown(); server.server_close(); thread.join()


def answered(db, q):
    persona = people(1)[0]
    spec = TaskSpec(questionnaire=q, personas=[persona], provider=ProviderConfig(), interval_seconds=0)
    task = db.create_task(spec)
    response = AnswerEngine(MockProvider(ProviderConfig())).run(task, spec, persona)
    db.save_response(response)
    return response


def text_question(qid, title):
    return Question(id=qid, title=title, type=QuestionType.SHORT, binding=Binding(container_selector="#" + qid.lower()))


def custom_target(q, url, **extra):
    return FormTarget(name="custom", url=url, questionnaire_id=q.id, kind="custom", authorized=True, success_text="感謝填寫", **extra)


@pytest.mark.browser
@pytest.mark.parametrize("suffix", ["/", ""])
def test_custom_form_at_origin_url_posts_to_thank_you_page(db, tmp_path, custom_server, suffix):
    q = Questionnaire(id="custom-one", title="custom", confirmed=True, pages=[Page(id="P1", title="P1", questions=[text_question("Q1", "意見")])])
    response = answered(db, q)
    url = custom_server["base"] + suffix
    target = custom_target(q, url)
    tool = FormAutomation(db, tmp_path)
    assert tool.run(target, response, [url], dry_run=True)["status"] == "dry_run"
    assert custom_server["posts"] == []
    result = tool.run(target, response, [url], dry_run=False)
    assert result["status"] == "success" and custom_server["posts"] == ["/thanks"]
    with pytest.raises(AppError, match="避免重複提交"):
        tool.run(target, response, [url], dry_run=False)
    assert custom_server["posts"] == ["/thanks"]


@pytest.mark.browser
def test_custom_multi_page_form_advances_and_submits_once(db, tmp_path, custom_server):
    q = Questionnaire(id="custom-multi", title="custom", confirmed=True, pages=[
        Page(id="P1", title="P1", questions=[text_question("Q1", "意見")]),
        Page(id="P2", title="P2", questions=[text_question("Q2", "建議")])])
    response = answered(db, q)
    url = custom_server["base"] + "/multi"
    result = FormAutomation(db, tmp_path).run(custom_target(q, url), response, [url], dry_run=False)
    assert result["status"] == "success"
    assert custom_server["posts"] == ["/multi/2", "/multi/done"]


@pytest.mark.browser
def test_custom_form_cannot_navigate_elsewhere_before_submit(db, tmp_path, custom_server):
    q = Questionnaire(id="custom-leak", title="custom", confirmed=True, pages=[Page(id="P1", title="P1", questions=[text_question("Q1", "意見")])])
    response = answered(db, q)
    url = custom_server["base"] + "/leak"
    with pytest.raises(AutomationError, match="轉址至未授權網址"):
        FormAutomation(db, tmp_path).run(custom_target(q, url), response, [url], dry_run=True)
    assert "/elsewhere" not in custom_server["gets"] and custom_server["posts"] == []


def stub(page, url, method="POST", navigation=True):
    request = SimpleNamespace(url=url, post_data="", method=method, frame=page.main_frame, is_navigation_request=lambda: navigation)
    route = SimpleNamespace(request=request, result=None)
    route.abort = lambda: setattr(route, "result", "blocked")
    route.continue_ = lambda: setattr(route, "result", "allowed")
    return route


def test_blocked_navigation_is_never_counted_as_a_sent_submission():
    page = SimpleNamespace(main_frame=object())
    url = "http://127.0.0.1:9/survey"
    guard = FormNetworkGuard(page, FormTarget(name="c", url=url, questionnaire_id="Q", kind="custom", authorized=True), url)
    early = stub(page, "http://127.0.0.1:9/thanks"); guard(early)
    assert early.result == "blocked" and guard.submission_posts == 0
    other_origin = stub(page, "http://127.0.0.1:10/thanks"); guard.allow_submit = True; guard(other_origin)
    assert other_origin.result == "blocked" and guard.submission_posts == 0 and guard.blocked_writes == 2
    sent = stub(page, "http://127.0.0.1:9/thanks"); guard(sent)
    assert sent.result == "allowed" and guard.submission_posts == 1


def test_unauthorized_multi_page_custom_form_is_refused_even_for_dry_run(db):
    q = Questionnaire(id="custom-multi", title="custom", confirmed=True, pages=[
        Page(id="P1", title="P1", questions=[text_question("Q1", "意見")]),
        Page(id="P2", title="P2", questions=[text_question("Q2", "建議")])])
    response = answered(db, q)
    from survey_sim.automation import check_policy
    target = custom_target(q, "http://127.0.0.1:9/multi").model_copy(update={"authorized": False})
    with pytest.raises(AutomationError, match="多頁自訂表單"):
        check_policy(target, response, [target.url], dry_run=True)


# ---- C-06 / C-07 / C-10 / C-11 ----
def test_condition_text_errors_name_the_line_in_chinese():
    from survey_sim.ui_conditions import weights_from_text
    with pytest.raises(AppError, match="職業第 2 行「工程師50」缺少「|」"):
        weights_from_text("設計師|20\n工程師50", "職業")
    with pytest.raises(AppError, match="不是數字"):
        weights_from_text("工程師|五十", "職業")
    assert weights_from_text("工程師|50\n\n設計師|50") == {"工程師": 50., "設計師": 50.}


def test_friendly_errors_hide_python_and_pydantic_internals():
    from survey_sim.models import Questionnaire
    from survey_sim.ui import friendly_error
    from pydantic import ValidationError
    with pytest.raises(ValidationError) as caught:
        Questionnaire(title="x", pages=[])
    text = friendly_error(caught.value)
    assert "問卷至少需要一頁及一道題目" in text and "validation error" not in text
    with pytest.raises(json.JSONDecodeError) as broken:
        json.loads('{"a": }')
    assert friendly_error(broken.value).startswith("JSON 格式錯誤：第 1 行")
    assert "unpack" not in friendly_error(ValueError("not enough values to unpack"))


def test_manual_verification_unblocks_or_completes_the_waiting_item(db):
    q = general_example(); q.confirmed = True
    persona = people(1)[0]
    task = db.create_task(TaskSpec(questionnaire=q, personas=[persona], provider=ProviderConfig()))
    response = AnswerEngine(MockProvider(ProviderConfig())).run(task, TaskSpec(questionnaire=q, personas=[persona], provider=ProviderConfig()), persona)
    db.save_response(response)
    target = FormTarget(name="t", url="https://example.com/form", questionnaire_id=q.id, kind="custom", authorized=True)
    for resolution, expected in [("failed", "failed"), ("success", "completed")]:
        db.execute("UPDATE task_items SET status='unknown' WHERE task_id=?", (task,))
        db.execute("DELETE FROM submissions")
        sid = db.reserve_submission(response.id, target, dry_run=False)
        db.finish_submission(sid, "unknown", "acknowledgement lost")
        db.resolve_submission(sid, resolution)
        assert db.rows("SELECT status FROM task_items WHERE task_id=?", (task,))[0]["status"] == expected
    with pytest.raises(AppError):
        db.resolve_submission(sid, "failed")  # only unknown records need a manual check


def test_pause_does_not_rewrite_a_finished_job(db):
    service = WorkbenchService(db, SecretStore())
    job = service.create(WorkbenchSpec(provider=ProviderConfig(), generate_count=1, mode="personas"))
    for status in ["completed_with_errors", "failed"]:
        db.execute("UPDATE workbench_jobs SET status=? WHERE id=?", (status, job))
        service.control(job, "paused")
        assert service.job(job)["status"] == status


def test_start_blockers_explain_every_disabled_reason():
    from survey_sim.ui_pipeline import start_blockers
    q = general_example(); q.confirmed = False
    reasons = start_blockers(True, "submit", "使用現有人物", q, None, [], 0, [], None, False)
    assert any("執行中" in r for r in reasons) and any("核對" in r for r in reasons)
    assert any("人物條件" in r for r in reasons) and any("至少選取一位人物" in r for r in reasons)
    assert any("填表目的地" in r for r in reasons)
    q.confirmed = True
    target = FormTarget(name="g", url="https://docs.google.com/forms/d/e/X/viewform", questionnaire_id=q.id, kind="google")
    reasons = start_blockers(False, "submit", "使用現有人物", q, object(), people(1), 0, [], target, False)
    assert reasons == ["請勾選已取得此測試表單的授權。", "請勾選「本次確定將模擬答案提交到以上測試表單」。", "請填寫表單送出後實際顯示的成功文字。"]
    assert start_blockers(False, "answers", "使用現有人物", q, object(), people(1), 0, [], None, False) == []


# ---- C-05 / C-09 / S-03 ----
from survey_sim.errors import ProviderError
from survey_sim.examples import onlyframe_example
from survey_sim.personas import PersonaGenerator


def test_each_generation_click_adds_people_instead_of_overwriting(db):
    generator = PersonaGenerator(MockProvider(ProviderConfig()))
    first = generator.generate_batch(3, 42, "一般", {"AI 自動混合": 1}, id_namespace="click-1")
    again = generator.generate_batch(3, 42, "一般", {"AI 自動混合": 1}, id_namespace="click-1")
    second = generator.generate_batch(3, 42, "一般", {"AI 自動混合": 1}, id_namespace="click-2")
    assert [p.id for p in first] == [p.id for p in again]          # reproducible within a batch id
    assert not {p.id for p in first} & {p.id for p in second}      # a new click is a new batch
    for p in first + second:
        db.save("persona", p)
    assert len(db.list("persona")) == 6


class CountingProvider(MockProvider):
    def __init__(self, config, mutate=None, error=None):
        super().__init__(config)
        self.calls, self.mutate, self.error = [], mutate, error

    def generate(self, operation, payload, system):
        self.calls.append(operation)
        if self.error:
            raise self.error
        result = super().generate(operation, payload, system)
        if self.mutate:
            self.mutate(operation, payload, result.data)
        return result


def test_truncated_page_is_not_retried_with_the_same_token_limit():
    q = onlyframe_example(); persona = people(1)[0]
    provider = CountingProvider(ProviderConfig(), error=ProviderError("AI 輸出被 Token 上限截斷；請增加最大輸出 Token。", kind="truncated"))
    from survey_sim.engine import AnswerEngine
    with pytest.raises(ProviderError, match="截斷"):
        AnswerEngine(provider).run("t", TaskSpec(questionnaire=q, personas=[persona], provider=ProviderConfig()), persona)
    assert provider.calls == ["answer_page"]


def test_persona_field_questions_are_filled_from_the_persona_without_repair():
    q = onlyframe_example(); persona = people(1)[0]
    def reword(operation, payload, data):
        for answer in data["answers"]:
            if answer["question_id"] == "Q01":
                answer["value"] = answer["value"] + " 歲"
    provider = CountingProvider(ProviderConfig(), mutate=reword)
    from survey_sim.engine import AnswerEngine
    response = AnswerEngine(provider).run("t", TaskSpec(questionnaire=q, personas=[persona], provider=ProviderConfig()), persona)
    age = next(a for a in response.answers if a.question_id == "Q01")
    assert age.value == str(persona.background.age) and response.status != "error"
    assert "repair_page" not in provider.calls
    assert any(r.get("kind") == "persona_field" for r in response.repair_history)


# ---- S-02 / S-05 / S-06 / S-07 ----
from survey_sim.models import Issue
from survey_sim.personas import similarity
from survey_sim.validator import submittable


def test_background_requests_list_recent_people_to_avoid():
    provider = CountingProvider(ProviderConfig())
    seen = []
    original = provider.generate
    def record(operation, payload, system):
        if operation == "background":
            seen.append(payload.get("avoid_profiles"))
        return original(operation, payload, system)
    provider.generate = record
    PersonaGenerator(provider).generate_batch(3, 42, "一般", {"AI 自動混合": 1})
    assert seen[0] is None and len(seen[1]) == 1 and len(seen[2]) == 2
    assert "歲" in seen[2][0]


def test_similarity_now_sees_interests_and_lifestyle():
    a = people(1)[0]
    b = a.model_copy(deep=True)
    assert similarity(a, b) == 1
    b.background.interests = ["完全不同的興趣"]
    b.background.lifestyle = "完全不同的生活"
    assert similarity(a, b) <= .8


def test_page_requests_send_only_what_answering_needs():
    q = onlyframe_example(); persona = people(1)[0]
    persona.topic_attributes["generation_conditions"] = {"big": "x" * 5000}
    sizes, payloads = [], []
    class Spy(MockProvider):
        def generate(self, operation, payload, system):
            sizes.append(len(json.dumps(payload, ensure_ascii=False)))
            payloads.append(payload)
            return super().generate(operation, payload, system)
    from survey_sim.engine import AnswerEngine
    response = AnswerEngine(Spy(ProviderConfig())).run("t", TaskSpec(questionnaire=q, personas=[persona], provider=ProviderConfig()), persona)
    assert response.status != "error"
    text = json.dumps(payloads, ensure_ascii=False)
    assert "binding" not in text and "import_warnings" not in text and "generation_conditions" not in text
    last = payloads[-1]
    assert all("rationale" not in a for a in last["previous_answers"])
    current = next(p for p in last["questionnaire"]["pages"] if p["id"] == last["page"]["id"])
    assert isinstance(current["questions"], str)  # the current page is sent once, in "page"
    assert sum(sizes) < 25000, sizes  # was ~46,000 characters for this questionnaire before the review


def test_saved_semantic_suggestions_can_be_applied_to_questions():
    from survey_sim.questionnaire_review import apply_semantic_analysis
    from survey_sim.models import Questionnaire
    q = onlyframe_example()
    target = next(x for x in q.questions if x.type.value in {"likert", "linear_scale"})
    q.semantic_analysis = {"questions": [{"id": target.id, "concept": "價格敏感", "reverse": True, "trait": "price_sensitivity"},
                                         {"id": "UNKNOWN", "concept": "x"}, {"id": q.questions[0].id, "trait": "not-a-trait"}]}
    data, changed = apply_semantic_analysis(q)
    updated = Questionnaire.model_validate(data)
    item = next(x for x in updated.questions if x.id == target.id)
    assert (item.concept, item.reverse, item.trait) == ("價格敏感", True, "price_sensitivity") and changed >= 1
    assert next(x for x in updated.questions if x.id == q.questions[0].id).trait == q.questions[0].trait


def test_persona_level_notes_do_not_block_submission_but_answer_reviews_do():
    budget = Issue(question_id="PERSONA", level="review", code="budget", message="預算")
    uncertain = Issue(question_id="Q1", level="review", code="uncertainty", message="不確定")
    preference = Issue(question_id="Q2", level="review", code="preference", message="差異")
    assert submittable("passed", []) and submittable("review", [budget, uncertain])
    assert not submittable("review", [budget, preference]) and not submittable("error", [budget])


# ---- Item 8: several personas at the same time ----
import time as _time

from survey_sim.batch import concurrency


class SlowMock(MockProvider):
    """Mock answers that take a while, recording how many requests overlap."""
    def __init__(self, config, delay=.4):
        super().__init__(config)
        self.delay, self.active, self.peak, self.calls = delay, 0, 0, 0
        self.lock = threading.Lock()

    def generate(self, operation, payload, system):
        with self.lock:
            self.active += 1; self.calls += 1
            self.peak = max(self.peak, self.active)
        try:
            _time.sleep(self.delay)
            return super().generate(operation, payload, system)
        finally:
            with self.lock:
                self.active -= 1


@pytest.fixture
def slow(monkeypatch):
    provider = SlowMock(ProviderConfig())
    monkeypatch.setattr(batch_module, "make_provider", lambda *args, **kwargs: provider)
    monkeypatch.setattr(provider_module, "make_provider", lambda *args, **kwargs: provider)
    return provider


def run_task(db, spec, timeout=60):
    task = db.create_task(spec)
    runner = BatchRunner(db, SecretStore())
    start = _time.monotonic(); runner.start(task); runner.thread.join(timeout)
    return task, _time.monotonic() - start, runner


def test_parallel_answers_are_faster_and_each_persona_answers_once(db, slow):
    q = general_example(); q.confirmed = True
    spec = TaskSpec(questionnaire=q, personas=people(6), provider=ProviderConfig(), interval_seconds=0, concurrency=3)
    task, elapsed, _ = run_task(db, spec)
    assert db.task(task)["status"] == "completed"
    responses = db.responses(task)
    assert sorted(r.persona_id for r in responses) == sorted(p.id for p in spec.personas)
    assert slow.peak == 3 and slow.calls == 6
    assert elapsed < 6 * slow.delay * .75  # sequential would need at least 2.4 s


def test_parallel_pause_keeps_queue_and_resume_finishes(db, slow):
    q = general_example(); q.confirmed = True
    spec = TaskSpec(questionnaire=q, personas=people(9), provider=ProviderConfig(), interval_seconds=0, concurrency=3)
    task = db.create_task(spec)
    runner = BatchRunner(db, SecretStore())
    runner.start(task); _time.sleep(.6); runner.pause(task); runner.thread.join(30)
    statuses = [r["status"] for r in db.rows("SELECT status FROM task_items WHERE task_id=?", (task,))]
    assert db.task(task)["status"] == "paused" and "running" not in statuses and "pending" in statuses
    runner.start(task); runner.thread.join(30)
    assert db.task(task)["status"] == "completed" and len(db.responses(task)) == 9


def test_parallel_workers_pause_once_on_invalid_key(db, fake_openai):
    q = general_example(); q.confirmed = True
    fake_openai["server"] = FakeOpenAI(401)
    spec = TaskSpec(questionnaire=q, personas=people(8), provider=OPENAI, interval_seconds=0, concurrency=3)
    task, _, _ = run_task(db, spec)
    assert db.task(task)["status"] == "provider_paused"
    assert fake_openai["server"].requests <= 3
    assert {r["status"] for r in db.rows("SELECT status FROM task_items WHERE task_id=?", (task,))} == {"pending"}


def test_budget_limits_and_website_flows_stay_sequential():
    q = general_example(); q.confirmed = True
    base = TaskSpec(questionnaire=q, personas=people(2), provider=ProviderConfig(), concurrency=4)
    assert concurrency(base) == 4
    assert concurrency(base.model_copy(update={"budget_limit": 1.})) == 1
    assert concurrency(base.model_copy(update={"concurrency": 1})) == 1


def test_workbench_generates_people_in_parallel_with_unique_names(db, slow):
    service = WorkbenchService(db, SecretStore())
    runner = BatchRunner(db, service.secrets)
    job = service.create(WorkbenchSpec(provider=ProviderConfig(), generate_count=6, mode="personas", concurrency=3))
    start = _time.monotonic(); service.start(job, runner); runner.thread.join(60)
    elapsed = _time.monotonic() - start
    generation = json.loads(service.job(job)["checkpoint"])["generation"]
    saved = db.list("persona")
    assert service.job(job)["status"] == "completed" and {g["status"] for g in generation} == {"completed"}
    assert len(saved) == 6 and len({p.name for p in saved}) == 6
    assert slow.peak == 3 and elapsed < 12 * slow.delay * .75  # 2 requests per person


@pytest.mark.browser
def test_parallel_local_form_submission_receives_each_response_once(db, tmp_path):
    from survey_sim.mock_form import MockFormServer
    import socket
    q = general_example(); q.confirmed = True
    db.save("questionnaire", q)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    target = FormTarget(name="local", url=f"http://127.0.0.1:{port}/form/{q.id}", questionnaire_id=q.id, authorized=True,
                        success_selector="#success[data-receipt]")
    spec = TaskSpec(questionnaire=q, personas=people(4), provider=ProviderConfig(), interval_seconds=0, concurrency=3,
                    form_target=target, form_allowlist=[target.url], form_dry_run=False)
    task, _, _ = run_task(db, spec, timeout=180)
    assert db.task(task)["status"] == "completed", db.rows("SELECT status,error FROM task_items WHERE task_id=?", (task,))
    assert [s["status"] for s in db.rows("SELECT status FROM submissions")] == ["success"] * 4
    receipts = db.rows("SELECT token FROM local_receipts")
    assert sorted(r["token"] for r in receipts) == sorted(r.id for r in db.responses(task))
