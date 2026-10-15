"""Read-only imports: guarded public metadata or official Forms API JSON.

Public metadata is undocumented; it always remains an unconfirmed draft.
No form is answered or submitted by this module.
"""
import hashlib
import json
import re

from .errors import AppError
from .models import Questionnaire, Page, Question, QuestionType as QT, Option, Binding, Condition, Route


def get(seq, index, default=None):
    return seq[index] if isinstance(seq, list) and len(seq) > index else default


def stable_option(label):
    return "O_" + hashlib.sha256(label.encode()).hexdigest()[:12]


def apply_routes(pages, raw_routes, warnings):
    positions = {p.id: i for i, p in enumerate(pages)}
    unresolved = []
    for page_id, qid, option_id, target in raw_routes:
        if target in {None, -2, "NEXT_SECTION", "GO_TO_ACTION_UNSPECIFIED"}:
            continue
        target_id = "END" if target in {-3, "SUBMIT_FORM"} else "P_" + str(target)
        if target_id != "END" and (target_id not in positions or positions[target_id] <= positions[page_id]):
            unresolved.append({"page": page_id, "question": qid, "option": option_id, "target": target})
            warnings.append(f"{qid or page_id} 存在未知或回頭分流，需人工改為可支援的前向路徑。")
            continue
        page = pages[positions[page_id]]
        if qid:
            page.routes.append(Route(when=Condition(question_id=qid, value=option_id), target=target_id))
        else:
            page.default_next = target_id
    return unresolved


def parse_public_metadata(html, url):
    match = re.search(r"FB_PUBLIC_LOAD_DATA_\s*=\s*", html)
    if not match:
        return None
    warnings = ["公開頁面 metadata 非官方穩定 API；需核對全部題目、頁面、分流及特殊限制，確認前不能批次執行。"]
    try:
        document, _ = json.JSONDecoder().raw_decode(html[match.end():].lstrip())
        form = document[1]
        items = form[1]
        if not isinstance(items, list):
            raise ValueError("element array missing")
        if get(document, 18):
            raise AppError("此表單的公開設定要求登入，請使用手動匯入或已授權的 Forms JSON。")
        pages = [Page(id="P1", title="第一頁", questions=[])]
        routes = []
        notes = []
        for item in items:
            if not isinstance(item, list) or len(item) < 4:
                raise ValueError("unknown element structure")
            item_id, title, code = item[0], item[1] or "未命名題目", item[3]
            if code == 8:
                # The page break records the previous section's default action.
                action = get(item, 5)
                if action not in {None, -2}:
                    routes.append((pages[-1].id, "", "", action))
                pages.append(Page(id="P_" + str(item_id), title=title, questions=[]))
                continue
            if code in {6, 11, 12}:
                notes.append(title + "：" + str(get(item, 2) or ""))
                if code in {11, 12}:
                    warnings.append(f"{title} 包含圖片或影片情境，請補上供 AI 理解的文字描述。")
                continue
            qid = "G_" + str(item_id).replace("-", "_")
            entries = get(item, 4, []) or []
            entry = get(entries, 0, [])
            kind = {0: QT.SHORT, 1: QT.PARAGRAPH, 2: QT.SINGLE, 3: QT.DROPDOWN, 4: QT.MULTIPLE, 5: QT.LINEAR}.get(code, QT.UNSUPPORTED)
            options = []
            original_options = get(entry, 1, []) or []
            for opt in original_options:
                label = get(opt, 0)
                is_other = get(opt, 4) == 1
                if is_other and code in {2, 4}:
                    label = label if isinstance(label, str) and label.strip() else "其他"
                if not isinstance(label, str) or not label:
                    kind = QT.UNSUPPORTED
                    warnings.append(f"{qid} 有無法辨識的選項，需人工修正。")
                    continue
                oid = "O_OTHER" if is_other else stable_option(label)
                options.append(Option(id=oid, label=label, is_other=is_other and code in {2, 4}))
                if is_other and code not in {2, 4}:
                    kind = QT.UNSUPPORTED
                    warnings.append(f"{qid} 此題型的『其他』文字選項尚未支援，需人工核對。")
                if code in {2, 3} and get(opt, 2) is not None:
                    routes.append((pages[-1].id, qid, oid, opt[2]))
            rows = []
            if code == 7:
                try:
                    multi = bool(get(entries[0], 11, [0])[0])
                    kind = QT.CHECK_GRID if multi else QT.GRID
                    rows = [Option(id="R_" + str(e[0]), label=e[3]) for e in entries]
                except (TypeError, IndexError, ValueError):
                    kind = QT.UNSUPPORTED
            bounds = {}
            if code == 5:
                values = [int(o.label) for o in options]
                if len(values) < 2 or sorted(values) != list(range(min(values), max(values) + 1)):
                    kind = QT.UNSUPPORTED
                    warnings.append(f"{qid} 量表範圍不連續或無法辨識。")
                else:
                    bounds = {"scale_min": min(values), "scale_max": max(values)}
                    options = []
            if get(entry, 4):
                warnings.append(f"{qid} 含額外作答驗證，需人工核對選取數或文字限制。")
            if kind == QT.UNSUPPORTED:
                warnings.append(f"{qid} 特殊題型 {code} 尚未支援，不能直接略過。")
            pages[-1].questions.append(Question(id=qid, title=title, type=kind, options=options, rows=rows,
                required=bool(get(entry, 2, False)), binding=Binding(title=title), notes=str(get(item, 2) or ""), **bounds))
        unresolved = apply_routes(pages, routes, warnings)
        return Questionnaire(title=get(form, 8) or get(document, 3) or "Google Forms 草稿", description=str(get(form, 0) or "") + "\n" + "\n".join(notes),
            pages=pages, source_url=url, import_warnings=warnings,
            import_diagnostics={"method": "public_metadata", "pages_detected": len(pages), "unresolved_routes": unresolved,
                                "requires_manual_review": True}, confirmed=False)
    except AppError:
        raise
    except (ValueError, TypeError, IndexError, KeyError) as exc:
        raise AppError("Google 公開 metadata 結構已變動或含不明資料；請使用 DOM 草稿 / 官方 JSON / 手動匯入，勿直接視為完整問卷。") from exc


def parse_official_form(data):
    """Import already-authorized forms.get JSON, without storing OAuth credentials."""
    warnings, routes = [], []
    pages = [Page(id="P1", title="第一頁", questions=[])]
    for item in data.get("items", []):
        if "pageBreakItem" in item:
            pages.append(Page(id="P_" + item["itemId"], title=item.get("title") or "新頁面", questions=[]))
            continue
        if "questionItem" not in item and "questionGroupItem" not in item:
            if item.get("title"):
                warnings.append(f"{item['title']} 為附加內容，請確認其是否影響作答情境。")
            continue
        title = item.get("title") or "未命名題目"
        raw = item.get("questionItem", {}).get("question", {})
        qid = "G_" + str(raw.get("questionId") or item["itemId"])
        kind, options, rows, bounds = QT.UNSUPPORTED, [], [], {}
        if "textQuestion" in raw:
            kind = QT.PARAGRAPH if raw["textQuestion"].get("paragraph") else QT.SHORT
        if "scaleQuestion" in raw:
            kind = QT.LINEAR
            bounds = {"scale_min": raw["scaleQuestion"]["low"], "scale_max": raw["scaleQuestion"]["high"]}
        if "choiceQuestion" in raw:
            choice = raw["choiceQuestion"]
            kind = {"RADIO": QT.SINGLE, "CHECKBOX": QT.MULTIPLE, "DROP_DOWN": QT.DROPDOWN}.get(choice.get("type"), QT.UNSUPPORTED)
            for opt in choice.get("options", []):
                label = opt.get("value") or "其他"
                oid = stable_option(label)
                is_other = bool(opt.get("isOther"))
                supported_other = choice.get("type") in {"RADIO", "CHECKBOX"}
                oid = "O_OTHER" if is_other else oid
                options.append(Option(id=oid, label=label, is_other=is_other and supported_other))
                if is_other and not supported_other:
                    kind = QT.UNSUPPORTED
                    warnings.append(f"{qid} 此題型的『其他』文字選項尚未支援，需人工核對。")
                target = opt.get("goToSectionId") or opt.get("goToAction")
                if target:
                    routes.append((pages[-1].id, qid, oid, target))
        if "questionGroupItem" in item:
            group = item["questionGroupItem"]
            columns = group.get("grid", {}).get("columns", {})
            if columns.get("type") in {"RADIO", "CHECKBOX"}:
                kind = QT.GRID if columns["type"] == "RADIO" else QT.CHECK_GRID
                options = [Option(id=stable_option(o["value"]), label=o["value"]) for o in columns.get("options", [])]
                rows = [Option(id="R_" + r["questionId"], label=r.get("rowQuestion", {}).get("title") or r["questionId"]) for r in group.get("questions", [])]
                raw["required"] = any(r.get("required") for r in group.get("questions", []))
        if kind == QT.UNSUPPORTED:
            warnings.append(f"{qid} 特殊題型尚未支援，需人工修正。")
        pages[-1].questions.append(Question(id=qid, title=title, type=kind, required=bool(raw.get("required")),
            options=options, rows=rows, binding=Binding(title=title), notes=item.get("description", ""), **bounds))
    unresolved = apply_routes(pages, routes, warnings)
    return Questionnaire(title=data.get("info", {}).get("title") or "Google 官方 JSON 草稿", pages=pages,
        description=data.get("info", {}).get("description", ""), import_warnings=warnings,
        source_url=(data.get("responderUri") or "").split("?")[0],
        import_diagnostics={"method": "official_forms_json", "pages_detected": len(pages), "unresolved_routes": unresolved,
                            "requires_manual_review": True})
