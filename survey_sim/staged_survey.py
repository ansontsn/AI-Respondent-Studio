"""One persona: pre-use form pages, website experience, then post-use pages."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .automation import FormAutomation, FormNetworkGuard, browser_session, check_policy, landed_url
from .engine import Interrupted
from .errors import AppError, AutomationError
from .models import Answer, QuestionType, Response, WebsiteRun, uid
from .security import clean_url, clean_form_url
from .validator import visible
from .website_experience import DONE, WebsiteExperience, factual_values, make_plan, require_usable


def survey_workflow(spec, persona):
    if not persona.onlyframe_tier:
        raise AppError("此人物尚未選定 ONLYFRAME 方案，請在生成人物時啟用 AI 方案選擇。")
    return spec.website_workflow.model_copy(update={"tier": persona.onlyframe_tier})


def validate_survey_flow(spec, people=None):
    flow = spec.website_survey
    if flow is None:
        return
    if not spec.website_workflow or spec.website_tier_assignments:
        raise AppError("分階段問卷必須設定網站流程，並沿用人物方案，不能另行分配方案。")
    if not spec.website_workflow.use_persona_name:
        raise AppError("分階段流程的網站提交必須沿用人物姓名。")
    pages = {p.id: i for i, p in enumerate(spec.questionnaire.pages)}
    boundary = pages.get(flow.after_page_id)
    if boundary is None or boundary == len(pages) - 1:
        raise AppError("請指定有效的問卷暫停頁，並保留後續體驗題頁面。")
    qmap = {q.id: q for q in spec.questionnaire.questions}
    q = qmap.get(flow.tier_question_id)
    if not q or q.type not in {QuestionType.SINGLE, QuestionType.DROPDOWN} or not q.required:
        raise AppError("方案題必須是問卷內有效的必填單選或下拉題。")
    if flow.name_question_id:
        name_q = qmap.get(flow.name_question_id)
        if not name_q or name_q.type not in {QuestionType.SHORT, QuestionType.PARAGRAPH}:
            raise AppError("人物姓名題必須是有效的文字題。")
    if set(flow.tier_options) != {o.id for o in q.options} or any(o.is_other for o in q.options):
        raise AppError("方案題每個選項都需明確對應 BASIC、CUSTOM 或 PREMIUM。")
    if len(set(flow.tier_options.values())) != len(flow.tier_options):
        raise AppError("每種方案只能對應一個問卷選項。")
    after = {q.id for p in spec.questionnaire.pages[boundary + 1:] for q in p.questions}
    if set(spec.website_fact_bindings) - after:
        raise AppError("網站操作事實只能對應暫停點之後的體驗題。")
    if set(flow.fact_option_maps) - set(spec.website_fact_bindings):
        raise AppError("體驗題選項對應含未設定的事實題。")
    for person in people if people is not None else spec.personas:
        workflow = survey_workflow(spec, person)
        if workflow.tier not in flow.tier_options.values():
            raise AppError(f"{person.name} 的 {workflow.tier} 方案沒有相符問卷選項。")
        prototype = WebsiteRun(workflow_id=workflow.id, persona_id=person.id, url=workflow.url,
            plan=make_plan(workflow, person, spec.seed), mode=workflow.mode,
            receipt_code="" if workflow.mode == "preview" else "DES-TEST-PREFLIGHT",
            status="preview_completed" if workflow.mode == "preview" else "server_confirmed" if workflow.require_server_receipt else "local_saved")
        factual_values(spec.questionnaire, spec.website_fact_bindings, prototype, flow.fact_option_maps)
    probe = Response(task_id="preflight", persona_id=spec.personas[0].id,
        questionnaire_id=spec.questionnaire.id, persona_snapshot=spec.personas[0],
        questionnaire_snapshot=spec.questionnaire, provider_snapshot=spec.provider, answers=[])
    check_policy(flow.form_target, probe, flow.form_allowlist, flow.dry_run)


@contextmanager
def local_form_available(db, target):
    """Restart a saved local test endpoint without accepting another workspace's server."""
    server = None
    if target.kind == "local":
        import httpx
        from .mock_form import MockFormServer
        address = urlsplit(target.url)
        health = f"{address.scheme}://{address.netloc}/health"
        try:
            result = httpx.get(health, timeout=3, trust_env=False)
        except httpx.ConnectError:
            server = MockFormServer(db, address.port).start()
        else:
            if result.status_code != 200 or result.json().get("workspace_id") != db.metadata()["id"]:
                raise AutomationError("本地表單連接埠屬於其他工作區，已停止填表。")
    try:
        yield
    finally:
        if server:
            server.close()


class FormSession:
    """Keep the questionnaire page open while a separate website context is used."""
    def __init__(self, db, browser, flow, response, artifacts):
        self.db, self.flow, self.response = db, flow, response
        self.target = flow.form_target
        self.automation = FormAutomation(db, artifacts)
        self.clicked = False
        self.context = browser.new_context(locale="zh-TW", viewport={"width": 1280, "height": 1000}, service_workers="block")
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)

    def open(self):
        url = check_policy(self.target, self.response, self.flow.form_allowlist, self.flow.dry_run)
        if self.target.kind == "local":
            current = self.db.get("questionnaire", self.response.questionnaire_id)
            if current is None or current.model_dump() != self.response.questionnaire_snapshot.model_dump():
                raise AutomationError("本地問卷與任務快照不同，已停止填表。")
        self.network = FormNetworkGuard(self.page, self.target, url)
        self.page.route("**/*", self.network)
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if landed_url(self.page) != url:
            raise AutomationError("問卷轉址至未授權網址，已停止。")
        if self.page.locator('iframe[src*="recaptcha"],input[type="password"]').count():
            raise AutomationError("問卷需要驗證碼或登入，已停止自動化。")
        if self.target.kind == "local":
            self.page.evaluate("token => { window.testToken = token; }", self.response.id)

    def fill_page(self, source, answers, next_page):
        amap = {a.question_id: a for a in answers}
        values = {a.question_id: a.value for a in answers if a.value is not None}
        for q in source.questions:
            if not visible(q, values):
                continue
            answer = amap.get(q.id)
            if answer is None:
                raise AutomationError(f"{q.id} 缺少已保存答案，不能跳過必填題。")
            if answer.validation != "skipped":
                self.automation._fill(self.page, q, answer.value, self.target.kind, answer.other_text)
        if self.target.kind == "local":
            self.page.get_by_role("button", name="下一頁", exact=True).click()
            error = self.page.locator("#error").inner_text().strip()
            if error:
                raise AutomationError("本地問卷檢查失敗：" + error)
        elif next_page != "END":
            self.automation.advance_page(self.page, self.target, self.network)

    def finish(self, response):
        url = check_policy(self.target, response, self.flow.form_allowlist, self.flow.dry_run)
        id = self.db.reserve_submission(response.id, self.target, self.flow.dry_run)
        artifact = self.automation.artifacts / f"{id}.png"
        try:
            self.page.screenshot(path=str(artifact), full_page=True)
            if self.flow.dry_run:
                status, message = "dry_run", "問卷已填寫並保存預演畫面，未送出。"
            else:
                self.automation.submit_and_confirm(self.page, self.target, self.network, response,
                                                   lambda: setattr(self, "clicked", True))
                self.page.screenshot(path=str(artifact), full_page=True)
                status, message = "success", "已完成問卷填寫，並確認問卷提交成功。"
            self.db.finish_submission(id, status, message, str(artifact.resolve()))
            return {"id": id, "status": status, "message": message, "artifact": str(artifact.resolve()), "url": url}
        except Exception as exc:
            status = "unknown" if self.clicked else "failed"
            message = str(exc) if isinstance(exc, AppError) else "問卷提交核對失敗。"
            if self.clicked:
                message += " 提交狀態不明，禁止自動重送，請查證接收端。"
            self.db.finish_submission(id, status, message, str(artifact.resolve()) if artifact.exists() else "")
            raise AutomationError(message) from exc


class StagedSurveyRunner:
    def __init__(self, db, engine):
        self.db, self.engine = db, engine

    def run(self, task_id, spec, persona, checkpoint, should_continue):
        validate_survey_flow(spec, [persona])
        flow = spec.website_survey
        workflow = survey_workflow(spec, persona)
        def save(**data):
            checkpoint.update(data)
            self.db.checkpoint(task_id, persona.id, checkpoint)
        def phase(value, message):
            if checkpoint.get("phase") != value:
                save(phase=value)
                self.db.event(task_id, f"{persona.name} · {message}")
        final = Response.model_validate(checkpoint["completed_response"]) if checkpoint.get("completed_response") else None
        response_id = final.id if final else checkpoint.get("form_response_id") or uid()
        save(form_response_id=response_id)
        if final and not flow.dry_run:
            old = self.db.rows("SELECT * FROM submissions WHERE response_id=? AND url=? AND dry_run=0 AND status IN ('success','submitting','unknown') ORDER BY created_at DESC", (response_id, clean_form_url(flow.form_target.url)))
            if old:
                if old[0]["status"] != "success":
                    raise AutomationError("這份問卷已嘗試提交且結果不明，禁止自動重送。")
                final.form_result = {"id": old[0]["id"], "status": "success", "message": old[0]["message"], "artifact": old[0]["artifact"]}
                return final
        probe = final or Response(id=response_id, task_id=task_id, persona_id=persona.id,
            questionnaire_id=spec.questionnaire.id, persona_snapshot=persona,
            questionnaire_snapshot=spec.questionnaire, provider_snapshot=spec.provider, answers=[])
        boundary = next(i for i,p in enumerate(spec.questionnaire.pages) if p.id == flow.after_page_id)
        def ensure_website(page, data):
            if spec.questionnaire.pages.index(page) <= boundary:
                phase("pre_survey", "填寫網站操作前問卷")
                return
            if flow.after_page_id not in data.get("visited", []):
                raise AutomationError("問卷分流跳過設定的暫停點，已停止；請核對體驗題起點。")
            choice = next((a["value"] for a in data["answers"] if a["question_id"] == flow.tier_question_id), None)
            if choice is not None and flow.tier_options.get(choice) != persona.onlyframe_tier:
                raise AutomationError("問卷方案與人物固定方案不一致，禁止網站提交。")
            if flow.name_question_id:
                name = next((a["value"] for a in data["answers"] if a["question_id"] == flow.name_question_id), None)
                if name is not None and name != persona.name:
                    raise AutomationError("問卷姓名與人物姓名不一致，禁止網站提交。")
            previous = data.get("website_run")
            run = WebsiteRun.model_validate(previous) if previous else None
            if run and (run.persona_id != persona.id or run.plan.tier != workflow.tier or run.url != clean_url(workflow.url) or run.mode != workflow.mode or (run.persona_name and run.persona_name != persona.name)):
                raise AutomationError("保存的網站紀錄與同一人物、方案或網址不一致。")
            if run and (run.submission_started or run.status in DONE):
                require_usable(run, workflow)
            else:
                phase("website", f"前段問卷已保存；使用 {workflow.tier} 體驗網站")
                run = WebsiteExperience(self.db).run(workflow, persona, spec.seed, should_continue,
                    lambda r: save(website_run=r.model_dump(mode="json")), browser=browser)
                require_usable(run, workflow)
            phase("post_survey", "網站操作已完成；接續原問卷體驗題")

        with local_form_available(self.db, flow.form_target), browser_session() as browser:
            session = FormSession(self.db, browser, flow, probe, Path(self.db.path).parent / "artifacts")
            try:
                session.open()
                saved_answers = [Answer.model_validate(a) for a in checkpoint.get("answers", [])]
                values = {a.question_id: a.value for a in saved_answers if a.value is not None}
                # A restarted browser replays saved answers, never regenerates earlier pages.
                for page_id in checkpoint.get("visited", []):
                    if not should_continue():
                        raise Interrupted("已保存問卷進度，稍後可接續。")
                    source = next(p for p in spec.questionnaire.pages if p.id == page_id)
                    session.fill_page(source, saved_answers, spec.questionnaire.next_page(page_id, values))
                if final is None:
                    final = self.engine.run(task_id, spec, persona, checkpoint,
                        lambda data: save(**data), should_continue,
                        before_page=ensure_website,
                        on_page=lambda page, answers, next_id: session.fill_page(page, [Answer.model_validate(a) for a in checkpoint["answers"]], next_id))
                    final.id = response_id
                    save(completed_response=final.model_dump(mode="json"))
                if final.status == "error":
                    return final
                if not should_continue():
                    raise Interrupted("問卷已填完，尚未送出；已保存進度。")
                phase("form_finish", "核對並完成問卷")
                final.form_result = session.finish(final)
                save(completed_response=final.model_dump(mode="json"), form_result=final.form_result, phase="completed")
                return final
            finally:
                session.context.close()
