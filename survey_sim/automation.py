from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

from .errors import AutomationError, AppError
from .models import QuestionType
from .security import clean_form_url

logger = logging.getLogger(__name__)


def launch_browser(pw, headless=True):
    explicit = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "")
    if explicit:
        return pw.chromium.launch(headless=headless, executable_path=explicit)
    candidates = [Path(os.getenv("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
                  Path(os.getenv("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe"]
    for path in candidates:
        if path.exists():
            return pw.chromium.launch(headless=headless, executable_path=str(path))
    try:
        return pw.chromium.launch(headless=headless)
    except Exception as exc:
        raise AutomationError("找不到可用瀏覽器；請安裝 Chrome / Edge，或執行『安裝瀏覽器.bat』。") from exc


@contextmanager
def browser_session(existing=None):
    if existing is not None:
        yield existing
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        try:
            yield browser
        finally:
            browser.close()


def check_policy(target, response, allowlist, dry_run):
    url = clean_form_url(target.url)
    allowed = {clean_form_url(u) for u in allowlist if u.strip()}
    if url not in allowed:
        raise AutomationError("此 URL 未列入允許清單；請先保存完整的測試表單網址。")
    if target.purpose != "test" or response.questionnaire_snapshot.purpose != "test":
        raise AutomationError("正式研究 / 參考問卷禁止自動提交，請使用獨立測試問卷。")
    if target.questionnaire_id != response.questionnaire_id:
        raise AutomationError("表單與回答的問卷 ID 不一致。")
    if target.kind == "local" and (urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"} or urlsplit(url).path != f"/form/{response.questionnaire_id}"):
        raise AutomationError("本地表單類型只接受 loopback 主機及正確的 /form/問卷ID 路徑。")
    if not dry_run and not target.authorized:
        raise AutomationError("此測試表單尚未經使用者確認授權，僅能 Dry Run。")
    if target.kind == "google" and len(response.questionnaire_snapshot.pages) > 1 and not target.authorized:
        raise AutomationError("Google 多頁表單翻頁會傳送當頁答案，請先確認此為允許虛擬答案的授權測試表單。")
    if target.kind == "custom" and len(response.questionnaire_snapshot.pages) > 1 and not target.authorized:
        raise AutomationError("多頁自訂表單翻頁可能傳送當頁答案，請先確認此為允許虛擬答案的授權測試表單。")
    if response.status == "error":
        raise AutomationError("回答仍有明確錯誤，請修正後再執行填表。")
    if target.kind == "google" and (urlsplit(url).hostname != "docs.google.com" or "/forms/" not in urlsplit(url).path or not urlsplit(url).path.endswith("/viewform")):
        raise AutomationError("Google Forms 請使用展開後的 docs.google.com/forms/.../viewform 完整網址。")
    if not dry_run and target.kind != "local" and not (target.success_selector or target.success_text):
        raise AutomationError("請設定提交成功的明確元素或訊息，才能啟用實際提交。")
    return url


def landed_url(page):
    """A blocked navigation leaves a browser error page whose URL is not HTTP(S)."""
    try:
        return clean_form_url(page.url)
    except AppError:
        return ""


def comparable_path(path):
    """clean_url drops trailing slashes; the browser requests '/' for an origin."""
    return path.rstrip("/") or "/"


class FormNetworkGuard:
    """Google's continue=1 POST advances sections; only the last click may submit.

    A write is counted as sent only when the request is actually let through."""
    def __init__(self, page, target, url):
        self.page, self.target, self.initial = page, target, urlsplit(url)
        self.submit_path = (f"/submit/{target.questionnaire_id}" if target.kind == "local" else
                            self.initial.path.removesuffix("viewform") + "formResponse")
        self.allowed_paths = {comparable_path(self.initial.path)}
        self.allow_next = self.allow_submit = self.navigated = False
        self.navigation_posts = self.submission_posts = self.blocked_writes = 0

    def __call__(self, route):
        req, dest = route.request, urlsplit(route.request.url)
        custom = self.target.kind == "custom"
        same_origin = (dest.scheme, dest.netloc) == (self.initial.scheme, self.initial.netloc)
        main_navigation = req.is_navigation_request() and req.frame == self.page.main_frame
        endpoint = same_origin and dest.path == self.submit_path
        continuing = False
        if self.target.kind == "google" and req.method == "POST" and endpoint:
            fields = parse_qs(req.post_data or "", keep_blank_values=True)
            continuing = fields.get("continue") == ["1"] and "submit" not in fields
        write = req.method not in {"GET", "HEAD", "OPTIONS"}
        permitted_next = permitted_submit = False
        if write:
            # Advancing a page may send that page's answers; it needs authorization.
            permitted_next = self.target.authorized and self.allow_next and same_origin and (
                (self.target.kind == "google" and main_navigation and endpoint and continuing) or custom)
            permitted_submit = (not permitted_next and self.allow_submit and req.method == "POST" and same_origin
                                and not continuing and (endpoint or custom))
            if not (permitted_next or permitted_submit):
                self.blocked_writes += 1
                route.abort()
                return
        if main_navigation:
            path = comparable_path(dest.path)
            # Custom forms may move to another same-origin page (next page, thank-you page)
            # only while the user-configured next / submit click is in progress.
            permitted_path = same_origin and (
                path in self.allowed_paths or
                (endpoint and (self.navigated or self.allow_submit or permitted_next)) or
                (custom and (self.allow_next or self.allow_submit or permitted_next or permitted_submit)))
            if not permitted_path:
                if write:
                    self.blocked_writes += 1
                route.abort()
                return
            self.allowed_paths.add(path)
        if permitted_next:
            self.navigated = True
            self.navigation_posts += 1
            if not custom:
                self.allow_next = False
        elif permitted_submit:
            self.submission_posts += 1
            self.navigated = True
            if not custom:
                self.allow_submit = False
        route.continue_()


class FormAutomation:
    def __init__(self, db, artifacts: Path):
        self.db, self.artifacts = db, Path(artifacts)
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def plan(self, response):
        questions = {q.id: q for q in response.questionnaire_snapshot.questions}
        return [{"題目 ID": a.question_id, "題目": questions[a.question_id].title, "答案": a.value, "其他補充文字": a.other_text,
                 "動作": "略過" if a.validation == "skipped" else "填寫"} for a in response.answers]

    def _container(self, page, q, kind):
        if kind == "local":
            return page.locator(f'[data-qid="{q.id}"]')
        if q.binding.container_selector:
            return page.locator(q.binding.container_selector)
        title = (q.binding.title or q.title).strip()
        # Google includes its required-marker aria-label in the accessible name.
        # Match the visible heading text, including <br> / whitespace differences.
        pattern = re.compile(r"^\s*" + r"\s*".join(re.escape(part) for part in re.split(r"\s+", title)) + r"\s*\*?\s*$")
        headings = page.locator('[role="heading"]').filter(has_text=pattern)
        return page.get_by_role("listitem").filter(has=headings)

    def navigation_button(self, page, target, *, submit=False):
        configured = target.submit_text if submit else target.next_text
        button = page.get_by_role("button", name=configured, exact=True)
        if button.count() == 1 and button.is_visible():
            return button
        aliases = {"提交", "送出", "Submit"} if submit else {"下一頁", "下一步", "繼續", "继续", "Next"}
        if target.kind == "google" and configured in aliases:
            pattern = re.compile(r"^(?:" + "|".join(re.escape(label) for label in sorted(aliases)) + r")$")
            button = page.get_by_role("button", name=pattern).filter(visible=True)
            if button.count() == 1:
                return button
        raise AutomationError("無法唯一找到" + ("提交" if submit else "下一頁") + "按鈕；請核對表單實際按鈕文字。")

    def submit_and_confirm(self, page, target, network, response, mark_clicked):
        """Click the final submit button once and wait for the configured success marker.
        Shared by single-form filling and the staged survey. Returns the local receipt
        ID for local forms, else ''. mark_clicked() runs just before the click."""
        selector = (target.success_selector or "#success[data-receipt]") if target.kind == "local" else target.success_selector
        success = page.locator(selector) if selector else page.get_by_text(target.success_text, exact=True)
        if success.count() and success.first.is_visible():
            raise AutomationError("成功標記在提交前已可見，無法作為提交驗證。請修正設定。")
        submit_button = self.navigation_button(page, target, submit=True)
        if submit_button.count() != 1 or not submit_button.is_visible():
            raise AutomationError("無法唯一找到可見的提交按鈕，尚未送出。請檢查導覽與提交文字。")
        mark_clicked()  # A click timeout could still send a network request.
        network.allow_submit = True
        submit_button.click()
        success.first.wait_for(state="visible", timeout=15000)
        if target.kind != "local":
            return ""
        receipt = success.first.get_attribute("data-receipt")
        if not receipt or not self.db.rows("SELECT id FROM local_receipts WHERE id=? AND token=?", (receipt, response.id)):
            raise AutomationError("畫面顯示成功，但未找到本地收件紀錄")
        return receipt

    def advance_page(self, page, target, network):
        before = page.content()
        network.allow_next = True
        try:
            self.navigation_button(page, target).click()
            page.wait_for_timeout(600)
        finally:
            network.allow_next = False
        if page.content() == before:
            raise AutomationError("多頁導覽未改變頁面，可能有必填錯誤")

    def _fill(self, page, q, value, kind, other_text=""):
        if value is None or value == "" or value == []:
            return
        box = self._container(page, q, kind)
        if box.count() != 1 or not box.is_visible():
            title = " ".join(q.title.split())[:120]
            raise AutomationError(f"「{title}」（{q.id}）題目無法唯一對應或不在目前頁面（找到 {box.count()} 個）；請檢查問卷分頁與題目對應。")
        labels = {o.id: q.binding.option_labels.get(o.id, o.label) for o in q.options}
        other_option = next((o for o in q.options if o.is_other), None)
        def click_option(scope, id, checkbox=False):
            if kind == "local":
                control = scope.locator(f'input[data-opt="{id}"]')
                control.check()
                if not control.is_checked():
                    raise AutomationError(f"{q.id} 選項未被勾選")
            else:
                role = "checkbox" if checkbox else "radio"
                if other_option and id == other_option.id and kind == "google" and id not in q.binding.option_labels:
                    control = scope.locator(f'[role="{role}"][data-value="__other_option__"]')
                    if not control.count():
                        control = scope.get_by_role(role, name=re.compile(r"^(其他|Other)\s*[:：]?\s*$", re.I))
                else:
                    control = scope.get_by_role(role, name=labels.get(id, str(id)), exact=True)
                if control.count() != 1:
                    raise AutomationError(f"{q.id} 選項無法唯一對應：{id}")
                if control.get_attribute("aria-checked") != "true":
                    control.click()
                if control.get_attribute("aria-checked") != "true" and not control.is_checked():
                    raise AutomationError(f"{q.id} 選項狀態未改變")
        if q.type in {QuestionType.SHORT, QuestionType.PARAGRAPH}:
            field = box.locator("textarea" if q.type == QuestionType.PARAGRAPH else 'input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"])')
            if field.count() != 1:
                raise AutomationError(f"{q.id} 文字欄位無法唯一對應")
            field.fill(str(value))
            field.dispatch_event("change")
            if field.input_value() != str(value):
                raise AutomationError(f"{q.id} 文字值不符")
        elif q.type == QuestionType.DROPDOWN:
            if kind == "local" or box.locator("select").count() == 1:
                field = box.locator("select")
                field.select_option(value=str(value)) if kind == "local" else field.select_option(label=labels[value])
            else:
                box.get_by_role("listbox").click()
                page.get_by_role("option", name=labels[value], exact=True).click()
        elif q.type in {QuestionType.SINGLE, QuestionType.MULTIPLE, QuestionType.LINEAR, QuestionType.LIKERT}:
            for id in value if isinstance(value, list) else [value]:
                click_option(box, str(id), q.type == QuestionType.MULTIPLE)
        elif q.type in {QuestionType.GRID, QuestionType.CHECK_GRID}:
            for row in q.rows:
                answer = value.get(row.id)
                if answer is None or answer == []:
                    continue
                if kind == "local":
                    row_box = box.locator(f'[data-rowid="{row.id}"]')
                elif row.id in q.binding.row_selectors:
                    row_box = box.locator(q.binding.row_selectors[row.id])
                else:
                    row_box = box.get_by_role("row").filter(has_text=row.label)
                if row_box.count() != 1:
                    raise AutomationError(f"{q.id} 方格列無法唯一對應，請設定 row_selectors")
                for id in answer if isinstance(answer, list) else [answer]:
                    click_option(row_box, id, q.type == QuestionType.CHECK_GRID)
        else:
            raise AutomationError(f"{q.id} 尚未支援此特殊題型")
        if other_text:
            field = box.locator('input[data-other-text]') if kind == "local" else box.locator('input[type="text"], input:not([type]), textarea')
            if field.count() != 1:
                raise AutomationError(f"{q.id} 其他文字欄位無法唯一對應")
            field.fill(other_text)
            field.dispatch_event("change")
            if field.input_value() != other_text:
                raise AutomationError(f"{q.id} 其他補充文字不符")

    def run(self, target, response, allowlist, dry_run=True, should_continue=None):
        from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
        from .engine import Interrupted
        from .validator import AnswerValidator
        _, _, _, status = AnswerValidator().validate(response.questionnaire_snapshot, response.persona_snapshot, response.answers)
        if status == "error":
            raise AutomationError("重新檢查回答時發現明確錯誤，已停止自動化。")
        url = check_policy(target, response, allowlist, dry_run)
        if target.kind == "local":
            current = self.db.get("questionnaire", response.questionnaire_id)
            if current is None or current.model_dump() != response.questionnaire_snapshot.model_dump():
                raise AutomationError("本地問卷已修改，與回答快照不同；請重新模擬後測試。")
        id = self.db.reserve_submission(response.id, target, dry_run)
        artifact = self.artifacts / f"{id}.png"
        clicked = False
        browser = page = network = None
        stage = "load"
        try:
            with sync_playwright() as pw:
                browser = launch_browser(pw)
                context = browser.new_context(locale="zh-TW", viewport={"width": 1280, "height": 1000}, service_workers="block")
                page = context.new_page()
                page.set_default_timeout(15000)
                network = FormNetworkGuard(page, target, url)
                page.route("**/*", network)
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if landed_url(page) != url:
                    raise AutomationError("測試表單轉址至未授權網址，已停止。")
                if page.locator('iframe[src*="recaptcha"],input[type="password"]').count():
                    raise AutomationError("表單需要驗證碼或登入，已停止自動化。")
                stage = "fill"
                if target.kind == "local":
                    page.evaluate("token => { window.testToken = token; }", response.id)
                qmap = {q.id: q for q in response.questionnaire_snapshot.questions}
                amap = {a.question_id: a for a in response.answers}
                for index, page_id in enumerate(response.visited_pages):
                    if should_continue and not should_continue():
                        raise Interrupted("填表已暫停或取消；保存答案，尚未提交")
                    source_page = next(p for p in response.questionnaire_snapshot.pages if p.id == page_id)
                    for q in source_page.questions:
                        a = amap[q.id]
                        if a.validation != "skipped":
                            self._fill(page, q, a.value, target.kind, a.other_text)
                    if target.kind == "local":
                        page.get_by_role("button", name="下一頁", exact=True).click()
                        if page.locator("#error").inner_text().strip():
                            raise AutomationError("本地表單必填檢查失敗：" + page.locator("#error").inner_text())
                    elif index < len(response.visited_pages) - 1:
                        self.advance_page(page, target, network)
                page.screenshot(path=str(artifact), full_page=True)
                if dry_run:
                    message = "Dry Run 已填寫並保存預覽，未提交。"
                    self.db.finish_submission(id, "dry_run", message, str(artifact.resolve()))
                    return {"id": id, "status": "dry_run", "message": message, "artifact": str(artifact.resolve()),
                            "navigation_posts": network.navigation_posts, "submission_posts": network.submission_posts}
                if should_continue and not should_continue():
                    raise Interrupted("提交前已暫停或取消，尚未送出")
                def mark_clicked():
                    nonlocal clicked
                    clicked = True
                receipt = self.submit_and_confirm(page, target, network, response, mark_clicked)
                page.screenshot(path=str(artifact), full_page=True)
                message = (f"本地收件已確認，編號 {receipt}" if target.kind == "local" else
                    "表單顯示設定的成功訊息；尚未核對表單回覆數")
                self.db.finish_submission(id, "success", message, str(artifact.resolve()))
                return {"id": id, "status": "success", "message": message, "artifact": str(artifact.resolve())}
        except Interrupted:
            self.db.finish_submission(id, "failed", "已暫停或取消；未提交")
            raise
        except Exception as exc:
            logger.exception("Browser automation failed submission=%s", id)
            sent = bool(network and network.submission_posts)
            state = "unknown" if sent else "failed"
            message = str(exc) if isinstance(exc, AppError) else "瀏覽器操作失敗；請檢查載入、題目對應及導覽文字。"
            if sent:
                message += " 提交狀態不明，請人工查證；系統已阻擋重複提交。"
            elif clicked:
                message += " 未發出最後提交請求；請核對表單必填欄位及導覽。"
            if network:
                message += f"（翻頁請求 {network.navigation_posts}、最後提交請求 {network.submission_posts}、攔截請求 {network.blocked_writes}）"
            if clicked and page:
                try:
                    page.screenshot(path=str(artifact), full_page=True)
                except Exception:
                    pass
            self.db.finish_submission(id, state, message, str(artifact.resolve()) if artifact.exists() else "")
            transient = stage == "load" and not clicked and (isinstance(exc, BrowserTimeout) or
                any(code in str(exc) for code in ("ERR_CONNECTION_RESET", "ERR_CONNECTION_REFUSED", "ERR_TIMED_OUT", "ERR_NETWORK_CHANGED")))
            raise AutomationError(message, retryable=transient) from exc
