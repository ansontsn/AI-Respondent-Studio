from __future__ import annotations

import os
import re

import streamlit as st

from .models import FormTarget, QuestionType, WebsiteSurveyFlow
from .website_experience import COLORS, TIERS, TEST_BINDINGS


FACTS = {"tier": TIERS, "frame_color": COLORS, "features": ["框色", "文字", "背景", "貼飾"],
         "storage": ["preview_completed", "local_saved", "server_confirmed"], "submitted": ["yes", "no"], "receipt_code": []}
FACT_LABELS = {"none": "依人物回答的感受或背景題", "tier": "實際使用方案", "frame_color": "實際框色",
    "features": "實際使用功能", "storage": "實際保存狀態", "submitted": "是否已提交設計", "receipt_code": "設計編號"}
VALUE_LABELS = {"preview_completed": "僅預覽，沒有提交", "local_saved": "已保存本機", "server_confirmed": "雲端已接收", "yes": "是", "no": "否"}


def guessed_tier(option):
    matches = [tier for tier in TIERS if option.id == tier or re.search(r"\b" + tier + r"\b", option.label, re.I)]
    return matches[0] if len(matches) == 1 else ""


def survey_options(rt, q, prefix, workflow=None, default=False):
    if q is None:
        return {}, ""
    enabled = st.checkbox("啟用：前段問卷 → 網站設計 → 回來填體驗題", value=default, key=prefix + "_enabled")
    if not enabled:
        return {}, ""
    st.caption("沿用人物生成時選定的方案。前段答案保存後，保留原問卷頁面，網站操作完成再接續體驗題。")
    if len(q.pages) < 2:
        message = "這份問卷只有一頁，請先在問卷管理分出前段與體驗題頁面。"
        st.warning(message)
        return {}, message
    if workflow is None:
        workflows = rt.db.list("website_workflow")
        if not workflows:
            message = "請先到「網站體驗模擬」儲存 ONLYFRAME 網站操作設定。"
            st.warning(message)
            return {}, message
        by_id = {w.id: w for w in workflows}
        chosen = st.selectbox("使用的網站流程", list(by_id), format_func=lambda key: by_id[key].name, key=prefix + "_workflow")
        workflow = by_id[chosen]
    operation_page = next((i for i,p in enumerate(q.pages) if i > 0 and "網站操作" in p.title), None)
    default_boundary = operation_page - 1 if operation_page is not None else min(1, len(q.pages) - 2)
    boundary_id = st.selectbox("問卷在哪一頁填完後，前往網站", [p.id for p in q.pages[:-1]],
        index=default_boundary, format_func=lambda key: next(p.title for p in q.pages if p.id == key), key=prefix + "_boundary_" + q.id)
    if operation_page is not None:
        st.caption("這份問卷的網站操作區段包含提交結果題，預設先完成網站操作，再回來回答該區段。")
    boundary = next(i for i,p in enumerate(q.pages) if p.id == boundary_id)
    candidates = [item for item in q.questions if item.required and item.type in {QuestionType.SINGLE, QuestionType.DROPDOWN}]
    if not candidates:
        message = "問卷沒有必填方案選擇題，請先確認問卷。"
        st.warning(message)
        return {}, message
    candidate_ids = [item.id for item in candidates]
    default_question = next((i for i,item in enumerate(candidates) if all(guessed_tier(o) for o in item.options)), 0)
    qid = st.selectbox("哪一題填寫人物的固定方案", candidate_ids, index=default_question,
        format_func=lambda key: next(item.title for item in candidates if item.id == key), key=prefix + "_tier_question_" + q.id + boundary_id)
    question = next(item for item in candidates if item.id == qid)
    st.caption("方案題可在前段或體驗題區，答案都沿用人物生成時選定的方案。")
    text_questions = [item for item in q.questions if item.type in {QuestionType.SHORT, QuestionType.PARAGRAPH}]
    name_choices = [""] + [item.id for item in text_questions]
    default_name = next((item.id for item in text_questions if item.persona_field == "name"), "")
    name_question = st.selectbox("問卷中的人物姓名題（若有）", name_choices, index=name_choices.index(default_name),
        format_func=lambda key: next((item.title for item in text_questions if item.id == key), "沒有姓名題"), key=prefix + "_name_question_" + q.id)
    tier_options, error = {}, ""
    with st.expander("確認問卷選項與方案的對應", expanded=True):
        for option in question.options:
            choices = [""] + TIERS
            tier = st.selectbox(option.label + " 對應方案", choices, index=choices.index(guessed_tier(option)),
                format_func=lambda key: key or "請指定方案", key=prefix + "_tier_" + q.id + qid + option.id)
            if tier:
                tier_options[option.id] = tier
            else:
                error = "請確認每個方案選項的對應。"
    targets = {t.id: t for t in rt.db.list("target") if t.questionnaire_id == q.id and t.purpose == "test"}
    choice = st.selectbox("接續填寫的表單", ["local_auto"] + list(targets),
        format_func=lambda key: "本機測試表單（依這份問卷建立）" if key == "local_auto" else targets[key].name, key=prefix + "_target_" + q.id)
    if choice == "local_auto":
        port = rt.mock_server.port if rt.mock_server else int(os.getenv("MOCK_FORM_PORT", "8765"))
        target = FormTarget(id="staged-local-" + q.id, name=q.title + " · 分階段本機測試",
            url=f"http://127.0.0.1:{port}/form/{q.id}", questionnaire_id=q.id, authorized=True, success_selector="#success[data-receipt]")
        allowlist = [target.url]
    else:
        target, allowlist = targets[choice], rt.setting("url_allowlist", [])
    dry_run = st.selectbox("整份問卷的結束方式", [True, False],
        format_func=lambda value: "預演：填完體驗題，保留預覽" if value else "填完體驗題後送出測試問卷", key=prefix + "_dry")
    st.caption("網站是否提交設計，依所選網站流程的結束方式；問卷預演不會送出問卷。")
    bindings, maps = {}, {}
    with st.expander("指定體驗題中的操作事實（方案、提交狀態等）"):
        for item in [item for page in q.pages[boundary + 1:] for item in page.questions]:
            default_fact = TEST_BINDINGS.get(item.id, "none") if q.id == "onlyframe-staged-test-v1" else "none"
            fact = st.selectbox(item.title, list(FACT_LABELS), index=list(FACT_LABELS).index(default_fact),
                format_func=FACT_LABELS.get, key=prefix + "_fact_" + q.id + item.id)
            if fact == "none":
                continue
            bindings[item.id] = fact
            if item.options:
                mapping = {}
                for value in FACTS[fact]:
                    options = [""] + [o.id for o in item.options]
                    default_id = next((o.id for o in item.options if o.id == value or o.label == value), "")
                    selected = st.selectbox(VALUE_LABELS.get(value, value) + " 對應的問卷選項", options, index=options.index(default_id),
                        format_func=lambda key, item=item: next((o.label for o in item.options if o.id == key), "請指定選項"),
                        key=prefix + "_fact_option_" + q.id + item.id + fact + value)
                    if selected:
                        mapping[value] = selected
                    else:
                        error = "請確認體驗事實題的選項對應。"
                maps[item.id] = mapping
    if error:
        st.warning(error)
        return {}, error
    flow = WebsiteSurveyFlow(after_page_id=boundary_id, tier_question_id=qid, tier_options=tier_options,
        name_question_id=name_question, form_target=target, form_allowlist=allowlist, dry_run=dry_run, fact_option_maps=maps)
    return {"website_workflow": workflow, "website_survey": flow, "website_fact_bindings": bindings, "compact_context": True}, ""


def prepare_survey_form(rt, parameters):
    flow = parameters.get("website_survey")
    if flow and flow.form_target.id.startswith("staged-local-"):
        target = flow.form_target.model_copy(update={"url": rt.local_form().url(flow.form_target.questionnaire_id)})
        parameters["website_survey"] = flow.model_copy(update={"form_target": target, "form_allowlist": [target.url]})
        rt.db.save("target", target)
    return parameters
