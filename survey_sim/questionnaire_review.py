import streamlit as st

from .errors import AppError
from .models import QuestionType as QT


def review_report(q):
    unsupported = [item.id for item in q.questions if item.type == QT.UNSUPPORTED]
    return {"pages": len(q.pages), "questions": len(q.questions), "required": sum(x.required for x in q.questions),
            "routes": sum(len(p.routes) for p in q.pages), "conditions": sum(len(x.display_if) for x in q.questions),
            "unsupported": unsupported, "warnings": q.import_warnings, "confirmed": q.confirmed,
            "diagnostics": q.import_diagnostics}


def apply_semantic_analysis(q):
    """Copy saved AI suggestions (concept / reverse / trait) onto the questions.
    Returns the questionnaire data and the number of changed questions; the caller
    saves it as a new, unconfirmed revision for the user to review."""
    from .models import Traits
    suggestions = {x.get("id"): x for x in (q.semantic_analysis or {}).get("questions", []) if isinstance(x, dict)}
    if not suggestions:
        raise AppError("尚無 AI 語意分析結果，請先按「分析整份問卷」。")
    allowed_traits = set(Traits.model_fields) | {"purchase_intention", "willingness_to_pay", ""}
    data, changed = q.model_dump(mode="json"), 0
    for page in data["pages"]:
        for item in page["questions"]:
            s = suggestions.get(item["id"])
            if not s:
                continue
            before = (item["concept"], item["reverse"], item["trait"])
            if isinstance(s.get("concept"), str):
                item["concept"] = s["concept"].strip()[:200]
            if isinstance(s.get("reverse"), bool) and item["type"] in {"linear_scale", "likert"}:
                item["reverse"] = s["reverse"]
            if isinstance(s.get("trait"), str) and s["trait"].strip() in allowed_traits:
                item["trait"] = s["trait"].strip()
            changed += before != (item["concept"], item["reverse"], item["trait"])
    return data, changed


def confirm_questionnaire(q, acknowledged):
    if not acknowledged:
        raise AppError("請先核對所有題目、選項、頁面及分流。")
    if review_report(q)["unsupported"]:
        raise AppError("仍有不支援的題目，請修正後確認。")
    q.confirmed = True
    return q


def preview(q, key="preview"):
    st.caption("此預覽用來核對題目與選項，不產生回答、不送出表單。分流規則列於頁面下方。")
    page_id = st.selectbox("預覽頁面", [p.id for p in q.pages], format_func=lambda id: next(p.title for p in q.pages if p.id == id), key=key + "_page")
    page = next(p for p in q.pages if p.id == page_id)
    for item in page.questions:
        st.markdown(f"**{item.id} · {item.title}{'（必填）' if item.required else ''}**")
        if item.type in {QT.SINGLE, QT.DROPDOWN}:
            st.selectbox("可用選項", [o.label for o in item.options], key=f"{key}_{q.id}_{item.id}", disabled=True)
        elif item.type == QT.MULTIPLE:
            st.multiselect("可用選項", [o.label for o in item.options], key=f"{key}_{q.id}_{item.id}", disabled=True)
            st.caption(f"至少 {item.min_choices} 項 / 最多 {item.max_choices or '不限'} 項")
        elif item.type in {QT.LIKERT, QT.LINEAR}:
            st.caption(f"量表 {item.scale_min}–{item.scale_max}{'；反向題' if item.reverse else ''}")
        elif item.rows:
            st.dataframe({"列": [r.label for r in item.rows], "選項": ["、".join(o.label for o in item.options)] * len(item.rows)}, hide_index=True)
        elif item.type == QT.UNSUPPORTED:
            st.error("尚未支援的題型，請修正。")
        else:
            st.caption(f"文字欄位，上限 {item.max_length} 字")
        for option in item.options:
            if option.is_other:
                st.text_input(f"{option.label}（勾選後填寫）", key=f"{key}_{q.id}_{item.id}_other", disabled=True)
                st.caption(f"選取『{option.label}』時需填寫補充文字，上限 {item.max_length} 字。")
        if item.display_if:
            st.json({"顯示條件": [x.model_dump() for x in item.display_if]})
    if page.routes:
        st.json({"分流": [r.model_dump() for r in page.routes]})
    st.caption("預設下一頁：" + (page.default_next or "依頁面順序"))
