from __future__ import annotations

import csv
import hashlib
import io
import json
from urllib.parse import urlsplit

from .errors import AppError
from .models import Binding, Page, Question, Questionnaire, QuestionType, Option


def import_json(content: str) -> Questionnaire:
    try:
        data = json.loads(content.lstrip("\ufeff"))
        if "items" in data and "info" in data:
            from .google_import import parse_official_form
            return parse_official_form(data)
        data["confirmed"] = False
        return Questionnaire.model_validate(data)
    except Exception as exc:
        raise AppError(f"JSON 問卷格式不合法：{exc}") from exc


def import_csv(content: str, title: str) -> Questionnaire:
    try:
        rows = list(csv.DictReader(io.StringIO(content.lstrip("\ufeff"))))
        if not rows or not {"id", "title", "type"} <= set(rows[0]):
            raise ValueError("CSV 必須包含 id,title,type 欄位")
        pages = {}
        for row in rows:
            page_id = row.get("page_id") or "P1"
            if page_id not in pages:
                pages[page_id] = {"id": page_id, "title": row.get("page_title") or page_id, "questions": [],
                                  "routes": json.loads(row.get("routes") or "[]"), "default_next": row.get("default_next") or None}
            options_raw = row.get("options") or "[]"
            if options_raw.startswith("["):
                options = json.loads(options_raw)
                options = [{"id": f"O{i+1}", "label": o} if isinstance(o, str) else o for i, o in enumerate(options)]
            else:
                options = [{"id": f"O{i+1}", "label": label.strip()} for i, label in enumerate(options_raw.split("|")) if label.strip()]
            q = {"id": row["id"], "title": row["title"], "type": row["type"], "options": options,
                 "required": (row.get("required") or "true").lower() not in {"false", "0", "否"},
                 "concept": row.get("concept") or "", "trait": row.get("trait") or "",
                 "reverse": (row.get("reverse") or "false").lower() in {"true", "1", "是"},
                 "persona_field": row.get("persona_field") or "", "rows": json.loads(row.get("rows") or "[]"),
                 "display_if": json.loads(row.get("display_if") or "[]"),
                 "binding": json.loads(row.get("binding") or "{}")}
            for field in ["scale_min", "scale_max", "min_choices", "max_choices", "max_length"]:
                if row.get(field):
                    q[field] = int(row[field])
            pages[page_id]["questions"].append(q)
        return Questionnaire(title=title, pages=[Page.model_validate(p) for p in pages.values()])
    except Exception as exc:
        raise AppError(f"CSV 問卷無法匯入：{exc}") from exc


def analyze_questionnaire(provider, questionnaire):
    result = provider.generate("analyze", {"questionnaire": questionnaire.model_dump(mode="json"),
        "output_example": {"topic": "主題", "audience": "研究對象", "summary": "整體關聯與不適用情境",
            "questions": [{"id": "題目ID", "concept": "概念", "reverse": False, "trait": "適用的 trait 或空字串"}]}},
        "理解整份問卷，辨識主題、對象、概念關聯、反向題、分流及不適用情境。只提出語意註記，不修改題目ID、選項或分流。依 output_example 輸出。")
    data = result.data
    valid_ids = {q.id for q in questionnaire.questions}
    if not isinstance(data.get("questions"), list) or any(not isinstance(x, dict) for x in data["questions"]):
        raise AppError("AI 語意分析格式不完整，未套用。")
    returned_ids = [x.get("id") for x in data["questions"]]
    if set(returned_ids) != valid_ids or len(returned_ids) != len(valid_ids):
        raise AppError("AI 語意分析有遺漏、未知或重複題目 ID，未套用。")
    return data


def parse_google_dom(html: str, url: str) -> Questionnaire:
    """Best-effort public DOM import. Google's DOM is NOT a stable public API."""
    from bs4 import BeautifulSoup
    from .google_import import parse_public_metadata
    try:
        richer = parse_public_metadata(html, url)
    except AppError as exc:
        if "要求登入" in str(exc):
            raise
        richer = None
        metadata_warning = str(exc)
    else:
        metadata_warning = ""
    if richer is not None:
        return richer
    soup = BeautifulSoup(html, "html.parser")
    warnings = ["公開 DOM 僅能辨識目前可見頁面；未確認後續頁面、條件分流、驗證及特殊題型。請逐題人工核對並補齊整份問卷。",
                "Google Forms DOM 不是官方穩定 API；題目 ID 優先使用可見資料屬性，否則以標題雜湊產生。改題名後需人工維護 ID。"]
    questions, seen = [], set()
    if metadata_warning:
        warnings.append(metadata_warning)
    blocks = soup.select('[role="listitem"]')
    for block in blocks:
        heading = block.select_one('[role="heading"]')
        if not heading:
            continue
        title = heading.get_text(" ", strip=True).rstrip(" *")
        stable = block.get("data-item-id") or hashlib.sha256(title.encode()).hexdigest()[:16]
        id = "G_" + str(stable).replace("-", "_")
        if id in seen:
            raise AppError("網頁有重複標題或無法區分的題目 ID；請改用 JSON / CSV 匯入並設定對應。")
        seen.add(id)
        options = []
        kind = QuestionType.UNSUPPORTED
        def choice_options(controls):
            result = []
            for i, control in enumerate(controls):
                is_other = control.get("data-value") == "__other_option__" or control.get("data-is-other") == "true"
                label = "其他" if is_other else control.get("data-value") or control.get("aria-label") or control.get_text(" ", strip=True)
                result.append(Option(id="O_OTHER" if is_other else f"O{i+1}", label=label, is_other=is_other))
            return result
        if block.select('[role="row"]'):
            warnings.append(f"{title} 方格需人工建立列與控制項對應")
        elif block.select('[role="radio"]'):
            kind, controls = QuestionType.SINGLE, block.select('[role="radio"]')
            options = choice_options(controls)
            values = [o.label for o in options]
            if block.get("data-question-type") in {"scale", "linear_scale"} and all(v.isdigit() for v in values):
                numbers = [int(v) for v in values]
                if sorted(numbers) == list(range(min(numbers), max(numbers) + 1)) and len(numbers) >= 2:
                    kind = QuestionType.LINEAR
        elif block.select('[role="checkbox"]'):
            kind, controls = QuestionType.MULTIPLE, block.select('[role="checkbox"]')
            options = choice_options(controls)
        elif block.select_one("textarea"):
            kind = QuestionType.PARAGRAPH
        elif block.select_one("select"):
            kind = QuestionType.DROPDOWN
            options = [Option(id=f"O{i+1}", label=x.get_text(" ", strip=True)) for i, x in enumerate(block.select("select option")) if x.get_text(strip=True)]
        elif block.select_one('input[type="text"],input[type="email"],input[type="number"]'):
            kind = QuestionType.SHORT
        if kind in {QuestionType.SINGLE, QuestionType.MULTIPLE} and block.select_one('input[type="text"],input:not([type]),textarea') and not any(o.is_other for o in options):
            kind = QuestionType.UNSUPPORTED
            warnings.append(f"{title} 含未能可靠對應的補充文字欄位，請人工設定其他選項。")
        if kind == QuestionType.UNSUPPORTED:
            warnings.append(f"{title} 題型或選項尚未解析，需人工修正")
        required = bool(block.select_one('[aria-required="true"]')) or "*" in heading.get_text()
        bounds = {"scale_min": min(numbers), "scale_max": max(numbers)} if kind == QuestionType.LINEAR else {}
        questions.append(Question(id=id, title=title, type=kind, options=[] if bounds else options, required=required,
                                  **bounds,
                                  binding=Binding(title=title), notes="公開 DOM 草稿，需人工核對"))
    if not questions:
        raise AppError("未找到可可靠辨識的題目；表單可能需要登入、已關閉，或網站結構已改變。請手動匯入。")
    title_tag = soup.select_one("title")
    return Questionnaire(title=title_tag.get_text(strip=True) if title_tag else "Google Forms 匯入草稿",
                         pages=[Page(id="P1", title="公開頁面草稿", questions=questions)], source_url=url,
                         import_warnings=warnings, confirmed=False,
                         import_diagnostics={"method": "visible_dom", "pages_detected": 1, "requires_manual_review": True})


def import_google(url: str) -> Questionnaire:
    from .automation import launch_browser
    from playwright.sync_api import sync_playwright
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https" or parsed.hostname not in {"docs.google.com", "forms.gle"}:
        raise AppError("請提供 https://docs.google.com/forms/.../viewform 或 forms.gle 公開網址。")
    try:
        with sync_playwright() as pw:
            browser = launch_browser(pw)
            page = browser.new_page(locale="zh-TW")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1000)
            final = urlsplit(page.url)
            if final.hostname != "docs.google.com" or "/forms/" not in final.path:
                raise AppError("此表單轉至登入或非公開頁面，無法匯入。")
            challenges = page.locator('iframe[src*="recaptcha"][src*="bframe"],input[type="password"]')
            if any(challenges.nth(i).is_visible() for i in range(challenges.count())):
                raise AppError("表單需要驗證或登入，請使用手動匯入。")
            questionnaire = parse_google_dom(page.content(), page.url.split("?")[0])
            browser.close()
            return questionnaire
    except AppError:
        raise
    except Exception as exc:
        raise AppError("Google Forms 網頁載入或解析失敗，請檢查連線或改用 JSON / CSV 匯入。") from exc
