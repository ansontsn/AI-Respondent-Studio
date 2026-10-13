from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from .errors import AutomationError, AppError
from .models import QuestionType
from .security import clean_url

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


def check_policy(target, response, allowlist, dry_run):
    url = clean_url(target.url)
    allowed = {clean_url(u) for u in allowlist if u.strip()}
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
    if response.status == "error":
        raise AutomationError("回答仍有明確錯誤，請修正後再執行填表。")
    if target.kind == "google" and (urlsplit(url).hostname != "docs.google.com" or "/forms/" not in urlsplit(url).path or not urlsplit(url).path.endswith("/viewform")):
        raise AutomationError("Google Forms 請使用展開後的 docs.google.com/forms/.../viewform 完整網址。")
    if not dry_run and target.kind != "local" and not (target.success_selector or target.success_text):
        raise AutomationError("請設定提交成功的明確元素或訊息，才能啟用實際提交。")
    return url


class FormAutomation:
    def __init__(self, db, artifacts: Path):
        self.db, self.artifacts = db, Path(artifacts)
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def plan(self, response):
        questions = {q.id: q for q in response.questionnaire_snapshot.questions}
        return [{"題目 ID": a.question_id, "題目": questions[a.question_id].title, "答案": a.value,
                 "動作": "略過" if a.validation == "skipped" else "填寫"} for a in response.answers]

    def _container(self, page, q, kind):
        if kind == "local":
            return page.locator(f'[data-qid="{q.id}"]')
        if q.binding.container_selector:
            return page.locator(q.binding.container_selector)
        title = q.binding.title or q.title
        return page.get_by_role("listitem").filter(has=page.get_by_role("heading", name=re.compile(r"^" + re.escape(title) + r"\s*\*?\s*$")))

    def _fill(self, page, q, value, kind):
        if value is None or value == "" or value == []:
            return
        box = self._container(page, q, kind)
        if box.count() != 1 or not box.is_visible():
            raise AutomationError(f"{q.id} 題目無法唯一對應或不在目前頁面；請檢查題目對應設定。")
        labels = {o.id: q.binding.option_labels.get(o.id, o.label) for o in q.options}
        def click_option(scope, id, checkbox=False):
            if kind == "local":
                control = scope.locator(f'input[data-opt="{id}"]')
                control.check()
                if not control.is_checked():
                    raise AutomationError(f"{q.id} 選項未被勾選")
            else:
                role = "checkbox" if checkbox else "radio"
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

    def run(self, target, response, allowlist, dry_run=True):
        from playwright.sync_api import sync_playwright
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
        browser = page = None
        try:
            with sync_playwright() as pw:
                browser = launch_browser(pw)
                context = browser.new_context(locale="zh-TW", viewport={"width": 1280, "height": 1000})
                page = context.new_page()
                page.set_default_timeout(15000)
                initial = urlsplit(url)
                def guard(route):
                    req = route.request
                    dest = urlsplit(req.url)
                    if req.is_navigation_request() and req.frame == page.main_frame:
                        permitted = dest.scheme == initial.scheme and dest.netloc == initial.netloc and (dest.path == initial.path or (target.kind == "google" and clicked and dest.path == initial.path.removesuffix("viewform") + "formResponse"))
                        if not permitted:
                            route.abort()
                            return
                    route.continue_()
                page.route("**/*", guard)
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if clean_url(page.url.split("?")[0]) != url:
                    raise AutomationError("測試表單轉址至未授權網址，已停止。")
                if page.locator('iframe[src*="recaptcha"],input[type="password"]').count():
                    raise AutomationError("表單需要驗證碼或登入，已停止自動化。")
                if target.kind == "local":
                    page.evaluate("token => { window.testToken = token; }", response.id)
                qmap = {q.id: q for q in response.questionnaire_snapshot.questions}
                amap = {a.question_id: a for a in response.answers}
                for index, page_id in enumerate(response.visited_pages):
                    source_page = next(p for p in response.questionnaire_snapshot.pages if p.id == page_id)
                    for q in source_page.questions:
                        a = amap[q.id]
                        if a.validation != "skipped":
                            self._fill(page, q, a.value, target.kind)
                    if target.kind == "local":
                        page.get_by_role("button", name="下一頁", exact=True).click()
                        if page.locator("#error").inner_text().strip():
                            raise AutomationError("本地表單必填檢查失敗：" + page.locator("#error").inner_text())
                    elif index < len(response.visited_pages) - 1:
                        before = page.content()
                        page.get_by_role("button", name=target.next_text, exact=True).click()
                        page.wait_for_timeout(600)
                        if page.content() == before:
                            raise AutomationError("多頁導覽未改變頁面，可能有必填錯誤")
                page.screenshot(path=str(artifact), full_page=True)
                if dry_run:
                    message = "Dry Run 已填寫並保存預覽，未提交。"
                    self.db.finish_submission(id, "dry_run", message, str(artifact.resolve()))
                    return {"id": id, "status": "dry_run", "message": message, "artifact": str(artifact.resolve())}
                selector = (target.success_selector or "#success[data-receipt]") if target.kind == "local" else target.success_selector
                if selector:
                    success = page.locator(selector)
                else:
                    success = page.get_by_text(target.success_text, exact=True)
                if success.count() and success.first.is_visible():
                    raise AutomationError("成功標記在提交前已可見，無法作為提交驗證。請修正設定。")
                submit_button = page.get_by_role("button", name=target.submit_text, exact=True)
                if submit_button.count() != 1 or not submit_button.is_visible():
                    raise AutomationError("無法唯一找到可見的提交按鈕，尚未送出。請檢查導覽與提交文字。")
                clicked = True  # A click timeout could still send a network request.
                submit_button.click()
                success.first.wait_for(state="visible", timeout=15000)
                if target.kind == "local":
                    receipt = success.first.get_attribute("data-receipt")
                    if not receipt or not self.db.rows("SELECT id FROM local_receipts WHERE id=? AND token=?", (receipt, response.id)):
                        raise AutomationError("畫面顯示成功，但未找到本地收件紀錄")
                page.screenshot(path=str(artifact), full_page=True)
                message = "已確認提交成功" + (f"，本地收件編號 {receipt}" if target.kind == "local" else "，成功標記已出現")
                self.db.finish_submission(id, "success", message, str(artifact.resolve()))
                return {"id": id, "status": "success", "message": message, "artifact": str(artifact.resolve())}
        except Exception as exc:
            logger.exception("Browser automation failed submission=%s", id)
            state = "unknown" if clicked else "failed"
            message = str(exc) if isinstance(exc, AppError) else "瀏覽器操作失敗；請檢查載入、題目對應及導覽文字。"
            if clicked:
                message += " 提交狀態不明，請人工查證；系統已阻擋重複提交。"
            self.db.finish_submission(id, state, message, str(artifact.resolve()) if artifact.exists() else "")
            raise AutomationError(message) from exc
        finally:
            # Playwright's context manager also closes the browser on exceptions.
            pass
