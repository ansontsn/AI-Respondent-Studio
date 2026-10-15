from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .errors import AppError
from .models import Questionnaire, Page, Question, QuestionType, Option, Binding, Condition, Route, uid
from .parsers import import_json, import_csv, import_google, analyze_questionnaire
from .providers import make_provider
from .ui import guarded, select_entity

TYPES = {"single": "單選", "multiple": "多選", "dropdown": "下拉選單", "short_text": "簡答", "paragraph": "段落",
         "linear_scale": "線性量表", "likert": "Likert 量表", "single_grid": "單選方格", "checkbox_grid": "核取方塊方格", "unsupported": "不支援特殊題型"}


def options_from_text(text):
    options = []
    for i, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        id, label = line.split("|", 1) if "|" in line else (f"O{i+1}", line)
        options.append(Option(id=id.strip(), label=label.strip()))
    return options


def save_revision(rt, q, data):
    data["id"], data["revision"], data["confirmed"] = q.id, q.revision + 1, False
    result = Questionnaire.model_validate(data)
    rt.db.save("questionnaire", result)
    return result


def questionnaires_page(rt):
    tab1, tab2, tab3 = st.tabs(["問卷清單與編輯", "匯入與建立", "預覽與確認"])
    with tab3:
        from .questionnaire_review import preview, review_report, confirm_questionnaire
        selected_q = select_entity("核對問卷", rt.db.list("questionnaire"), key="review_q")
        if selected_q:
            report = review_report(selected_q)
            for col, (label, field) in zip(st.columns(4), [("頁面", "pages"), ("題目", "questions"), ("必填", "required"), ("分流", "routes")]):
                col.metric(label, report[field])
            for warning in report["warnings"]:
                st.warning(warning)
            if report["diagnostics"]:
                with st.expander("解析狀態與待處理分流"):
                    st.json(report["diagnostics"])
            preview(selected_q, "q_review")
            checks = [st.checkbox(label, key=f"confirm_{selected_q.id}_{selected_q.revision}_{i}") for i, label in enumerate([
                "題目文字及選項已逐一核對", "所有頁面與題型已補齊", "必填、跳題及分流規則已確認", "解析警告已人工處理，並確認用途為模擬 / 測試"])]
            if st.button("保存問卷確認", type="primary"):
                updated = guarded(lambda: confirm_questionnaire(selected_q, all(checks)))
                if updated:
                    rt.db.save("questionnaire", updated)
                    st.success("此版本已確認，可以預覽回答及建立批次。")
    with tab2:
        with st.form("new_questionnaire"):
            title = st.text_input("新問卷名稱", "我的測試問卷")
            topic = st.text_input("問卷主題", "一般問卷")
            purpose = st.selectbox("問卷用途", ["test", "reference"], format_func=lambda v: "測試問卷" if v == "test" else "正式問卷參考（禁止自動提交）")
            if st.form_submit_button("建立可編輯問卷"):
                q = Questionnaire(title=title, topic=topic, purpose=purpose, pages=[Page(id="P1", title="第一頁", questions=[
                    Question(id="Q01", title="請編輯這道題目", type=QuestionType.SHORT)])])
                rt.db.save("questionnaire", q)
                st.success("已建立。請回問卷清單編輯題目與分流。")
        st.subheader("檔案匯入")
        uploaded = st.file_uploader("JSON 或 CSV 問卷", type=["json", "csv"])
        csv_title = st.text_input("CSV 問卷名稱", "匯入問卷")
        if uploaded and st.button("匯入問卷檔案"):
            def do_import():
                text = uploaded.getvalue().decode("utf-8-sig")
                q = import_json(text) if uploaded.name.lower().endswith(".json") else import_csv(text, csv_title)
                if rt.db.get("questionnaire", q.id):
                    q.id = uid()
                rt.db.save("questionnaire", q)
                st.success("已匯入草稿。請逐題核對、修正及確認。")
            guarded(do_import)
        st.subheader("Google Forms 公開網址")
        url = st.text_input("公開表單 URL")
        st.caption("先讀取公開頁面可辨識的問卷資料；若結構不相容，退回目前頁面的 DOM 草稿。頁面、分流及特殊限制會標示待核對，請在預覽與確認頁逐項檢查。")
        if st.button("讀取公開表單", disabled=not url):
            q = guarded(lambda: import_google(url))
            if q:
                rt.db.save("questionnaire", q)
                st.success("草稿已保存。請閱讀解析警告並人工修正。")
    with tab1:
        q = select_entity("問卷", rt.db.list("questionnaire"))
        if not q:
            return
        st.caption(f"ID：{q.id} · 修訂 {q.revision} · {'已確認' if q.confirmed else '待核對'} · {'測試' if q.purpose == 'test' else '正式問卷參考'}")
        for warning in q.import_warnings:
            st.warning(warning)
        st.dataframe(pd.DataFrame([{"頁面": p.title, "題目 ID": item.id, "題目": item.title, "題型": TYPES[item.type],
            "必填": item.required, "測量概念": item.concept, "反向": item.reverse, "條件數": len(item.display_if)} for p in q.pages for item in p.questions]), hide_index=True, width="stretch")
        st.download_button("下載完整問卷 JSON", q.model_dump_json(indent=2), file_name=f"{q.id}.json")
        with st.expander("問卷資訊"):
            with st.form(f"qmeta_{q.id}"):
                title = st.text_input("名稱", q.title)
                topic = st.text_input("主題", q.topic)
                audience = st.text_input("對象", q.audience)
                description = st.text_area("說明", q.description)
                if st.form_submit_button("儲存問卷資訊"):
                    def meta():
                        data = q.model_dump(mode="json")
                        data.update(title=title, topic=topic, audience=audience, description=description)
                        save_revision(rt, q, data)
                        st.success("已保存，需重新確認問卷。")
                    guarded(meta)
        with st.expander("編輯題目 / 新增題目", expanded=False):
            ids = {item.id: item for item in q.questions}
            selected = st.selectbox("選擇題目", ["new"] + list(ids), format_func=lambda v: "新增題目" if v == "new" else f"{v} · {ids[v].title}")
            item = ids.get(selected) or Question(id=f"Q{len(q.questions)+1:02d}", title="新題目", type=QuestionType.SHORT)
            with st.form(f"question_{q.id}_{selected}"):
                page_id = st.selectbox("所在頁面", [p.id for p in q.pages], index=next((i for i, p in enumerate(q.pages) if selected in [x.id for x in p.questions]), 0))
                qid = st.text_input("穩定題目 ID", item.id, disabled=selected != "new")
                title = st.text_input("題目文字", item.title)
                kind = st.selectbox("題型", list(TYPES), index=list(TYPES).index(item.type), format_func=TYPES.get)
                required = st.checkbox("必填", value=item.required)
                options = st.text_area("選項（每行 ID|選項文字；也可只填文字）", "\n".join(f"{o.id}|{o.label}" for o in item.options))
                other_option_id = st.text_input("其他文字選項 ID（單選 / 多選；留空表示沒有）", next((o.id for o in item.options if o.is_other), ""))
                st.caption("指定的選項被勾選時，會另存補充文字；ID 必須與上方選項一致。")
                rows = st.text_area("方格列（每行 ID|列文字）", "\n".join(f"{o.id}|{o.label}" for o in item.rows))
                a, b, c = st.columns(3)
                minimum = a.number_input("量表下界", value=item.scale_min, step=1)
                maximum = b.number_input("量表上界", value=item.scale_max, step=1)
                max_choices = c.number_input("最多選取（0 表示不限制）", min_value=0, value=item.max_choices or 0)
                min_choices = a.number_input("至少選取", min_value=0, value=item.min_choices)
                max_length = b.number_input("文字字數上限", min_value=1, value=item.max_length)
                concept = st.text_input("測量概念", item.concept)
                trait = st.text_input("關聯人格屬性（例如 price_sensitivity；可留白）", item.trait)
                reverse = st.checkbox("反向題", item.reverse)
                persona_field = st.text_input("直接對應人物欄位（例如 background.age；可留白）", item.persona_field)
                display_if = st.text_area("條件顯示 JSON（預設 []；參照較早題目）", json.dumps([x.model_dump() for x in item.display_if], ensure_ascii=False))
                st.caption('例如：[{"question_id":"Q03","operator":"eq","value":"yes"}]。可在下方用選單新增條件。')
                if st.form_submit_button("儲存題目"):
                    def save_question():
                        parsed_options = options_from_text(options)
                        if other_option_id.strip() and other_option_id.strip() not in {o.id for o in parsed_options}:
                            raise AppError("其他文字選項 ID 不在選項清單中。")
                        for option in parsed_options:
                            option.is_other = option.id == other_option_id.strip()
                        edited = Question(id=qid, title=title, type=kind, required=required, options=parsed_options,
                            rows=options_from_text(rows), scale_min=minimum, scale_max=maximum, max_choices=max_choices or None,
                            min_choices=min_choices, max_length=max_length, concept=concept, trait=trait, reverse=reverse,
                            persona_field=persona_field, display_if=json.loads(display_if), binding=item.binding,
                            notes=item.notes)
                        data = q.model_dump(mode="json")
                        for p in data["pages"]:
                            p["questions"] = [x for x in p["questions"] if x["id"] != selected]
                            if p["id"] == page_id:
                                # Keep original order when editing same page.
                                original = next(src for src in q.pages if src.id == page_id)
                                old_index = next((i for i, x in enumerate(original.questions) if x.id == selected), len(p["questions"]))
                                p["questions"].insert(min(old_index, len(p["questions"])), edited.model_dump(mode="json"))
                        save_revision(rt, q, data)
                        st.success("已保存題目，請重新確認。")
                    guarded(save_question)
            if selected != "new" and st.button("刪除此題目"):
                def delete_question():
                    data = q.model_dump(mode="json")
                    for p in data["pages"]:
                        p["questions"] = [x for x in p["questions"] if x["id"] != selected]
                    save_revision(rt, q, data)
                    st.success("題目已刪除。")
                guarded(delete_question)
        with st.expander("頁面與條件分流"):
            st.json([{ "頁面": p.id, "下一頁預設": p.default_next or "按順序", "條件分流": [r.model_dump() for r in p.routes]} for p in q.pages])
            a, b = st.columns(2)
            new_page_id = a.text_input("新頁面 ID", f"P{len(q.pages)+1}")
            new_page_title = b.text_input("新頁面名稱", "新頁面")
            if st.button("新增頁面"):
                def add_page():
                    data = q.model_dump(mode="json")
                    data["pages"].append(Page(id=new_page_id, title=new_page_title, questions=[]).model_dump())
                    save_revision(rt, q, data)
                    st.success("頁面已新增。")
                guarded(add_page)
            with st.form("add_route"):
                source = st.selectbox("分流來源頁面", [p.id for p in q.pages])
                question_id = st.selectbox("依據題目 ID", [x.id for x in q.questions])
                operator = st.selectbox("條件運算", ["eq", "ne", "includes", "gt", "gte", "lt", "lte"])
                value_text = st.text_input("比對值（選項 ID 或數字）", "yes")
                target = st.selectbox("跳轉至", [p.id for p in q.pages] + ["END"])
                if st.form_submit_button("新增分流規則"):
                    def add_route():
                        try:
                            value = json.loads(value_text)
                        except json.JSONDecodeError:
                            value = value_text
                        data = q.model_dump(mode="json")
                        page = next(p for p in data["pages"] if p["id"] == source)
                        page["routes"].append(Route(when=Condition(question_id=question_id, operator=operator, value=value), target=target).model_dump())
                        save_revision(rt, q, data)
                        st.success("已新增分流規則。")
                    guarded(add_route)
            with st.form("add_visibility"):
                affected = st.selectbox("要條件顯示的題目", [x.id for x in q.questions])
                previous = st.selectbox("顯示依據題目", [x.id for x in q.questions])
                condition_value = st.text_input("顯示時的選項 ID", "yes")
                if st.form_submit_button("新增題目顯示條件"):
                    def add_visibility():
                        data = q.model_dump(mode="json")
                        item = next(x for p in data["pages"] for x in p["questions"] if x["id"] == affected)
                        item["display_if"].append(Condition(question_id=previous, value=condition_value).model_dump())
                        save_revision(rt, q, data)
                        st.success("條件已保存。")
                    guarded(add_visibility)
        with st.expander("瀏覽器題目對應"):
            item = select_entity("題目對應", q.questions, key="binding_question")
            if item:
                with st.form("bindings"):
                    title = st.text_input("網頁上的題目標題", item.binding.title or item.title)
                    selector = st.text_input("題目容器 CSS Selector（本地不需設定）", item.binding.container_selector)
                    labels = st.text_area("選項 ID → 網頁文字 JSON", json.dumps(item.binding.option_labels, ensure_ascii=False))
                    rows = st.text_area("方格列 ID → CSS Selector JSON", json.dumps(item.binding.row_selectors, ensure_ascii=False))
                    if st.form_submit_button("儲存對應"):
                        def save_binding():
                            data = q.model_dump(mode="json")
                            question = next(x for p in data["pages"] for x in p["questions"] if x["id"] == item.id)
                            question["binding"] = Binding(title=title, container_selector=selector, option_labels=json.loads(labels), row_selectors=json.loads(rows)).model_dump()
                            save_revision(rt, q, data)
                            st.success("網頁對應已保存；請重新確認問卷並生成回答。")
                        guarded(save_binding)
        with st.expander("AI 問卷語意分析"):
            provider = select_entity("語意分析模型", rt.db.list("provider"))
            if provider and st.button("分析整份問卷"):
                data = guarded(lambda: analyze_questionnaire(make_provider(provider, rt.secrets.get(provider.id, provider.provider), rt.db), q))
                if data:
                    updated = q.model_dump(mode="json")
                    updated["semantic_analysis"] = data
                    save_revision(rt, q, updated)
                    st.success("分析已保存為建議；請核對概念及反向題後手動編輯。")
                    st.json(data)
            st.json(q.semantic_analysis)
            if q.semantic_analysis.get("questions"):
                st.caption("套用後，題目的測量概念、反向題及關聯人格屬性會用於人設一致性檢查；會建立新版本並需重新確認問卷。")
                if st.button("套用 AI 建議到題目"):
                    def apply_suggestions():
                        from .questionnaire_review import apply_semantic_analysis
                        data, changed = apply_semantic_analysis(q)
                        save_revision(rt, q, data)
                        st.success(f"已套用到 {changed} 題；請逐題核對後重新確認問卷。")
                    guarded(apply_suggestions)
        with st.expander("完整 JSON 編輯（排序、刪除分流、跨題一致性規則）"):
            text = st.text_area("完整問卷結構", q.model_dump_json(indent=2), height=440, key=f"qjson_{q.id}_{q.revision}")
            if st.button("儲存完整 JSON"):
                result = guarded(lambda: save_revision(rt, q, json.loads(text)))
                if result:
                    st.success("完整問卷已保存，請重新確認。")
        verified = st.checkbox("已逐題核對題型、選項、所有頁面及分流，確認此版本可模擬", value=q.confirmed)
        if st.button("確認問卷版本", type="primary"):
            def confirm():
                if any(x.type == QuestionType.UNSUPPORTED for x in q.questions):
                    raise AppError("尚有未支援特殊題型；請修正後確認。")
                q.confirmed = verified
                rt.db.save("questionnaire", q)
                st.success("問卷已確認。" if verified else "問卷已取消確認。")
            guarded(confirm)
        a, b = st.columns(2)
        if a.button("複製為獨立測試問卷"):
            new = q.model_copy(deep=True)
            new.id, new.title, new.purpose, new.confirmed = uid(), q.title + "（測試複本）", "test", False
            rt.db.save("questionnaire", new)
            st.rerun()
        if b.button("刪除問卷"):
            rt.db.delete("questionnaire", q.id)
            st.rerun()
