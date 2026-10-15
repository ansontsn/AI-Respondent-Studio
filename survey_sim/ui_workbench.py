import json

import pandas as pd
import streamlit as st

from .analysis import display_answer
from .models import TaskSpec, uid
from .parsers import import_json, import_csv
from .personas import PersonaGenerator
from .providers import make_provider
from .ui import guarded, select_entity, record_table
from .workflow import provider_ready, fingerprint, validated_plan


def navigate(section):
    st.session_state["nav"] = section


def workbench(rt):
    st.caption("建立問卷 → 受訪者 → AI 回答 → 品質檢查 → 比較分析 → 匯出。所有結果保存於本機。")
    cols = st.columns([3, 1])
    with cols[0]:
        st.subheader("開始新的模擬")
        st.write("快速精靈會逐步確認問卷、模型及人物，先測試一位，再執行完整批次。")
    cols[1].button("快速開始", type="primary", on_click=navigate, args=("快速開始",), width="stretch")
    questionnaires = rt.db.list("questionnaire")
    metrics = [("問卷", len(questionnaires)),
               ("虛擬人物", rt.db.rows("SELECT count(*) AS n FROM entities WHERE kind='persona'")[0]["n"]),
               ("已保存回答", rt.db.rows("SELECT count(*) AS n FROM responses")[0]["n"]),
               ("執行中任務", rt.db.rows("SELECT count(*) AS n FROM tasks WHERE status='running'")[0]["n"])]
    for col, (label, value) in zip(st.columns(4), metrics):
        col.metric(label, value)
    a, b = st.columns(2)
    with a:
        st.subheader("最近問卷")
        st.dataframe(pd.DataFrame([{"問卷": q.title, "版本": q.revision, "題目": len(q.questions), "狀態": "已確認" if q.confirmed else "待核對"} for q in questionnaires[:6]]), hide_index=True, width="stretch")
        st.button("管理問卷", on_click=navigate, args=("問卷管理",))
        st.subheader("模型設定狀態")
        records = []
        for c in rt.db.list("provider"):
            ready, message = provider_ready(c, rt.secrets)
            records.append({"設定檔": c.name, "服務商": c.provider, "模型": c.model, "狀態": message})
        st.dataframe(pd.DataFrame(records), hide_index=True, width="stretch")
    with b:
        st.subheader("最近模擬任務")
        record_table(rt.db.rows("SELECT id,status,created_at FROM tasks ORDER BY created_at DESC LIMIT 6"))
        st.button("開啟模擬控制台", on_click=navigate, args=("AI 模擬控制台",))
        st.subheader("模擬品質摘要")
        record_table(rt.db.rows("SELECT status,count(*) AS 回答數 FROM responses GROUP BY status"))
        st.caption("通過是格式及已設定邏輯檢查的結果，不代表對真人的預測準確率。")
        st.button("檢查回答品質", on_click=navigate, args=("回答品質",))
    with st.expander("提交與 API 統計"):
        st.metric("執行任務總數", rt.db.rows("SELECT count(*) AS n FROM tasks")[0]["n"])
        st.subheader("測試提交")
        record_table(rt.db.rows("SELECT status,count(*) AS 數量 FROM submissions GROUP BY status"))
        st.subheader("API 用量")
        record_table(rt.db.rows("SELECT provider,model,count(*) AS 請求數,sum(input_tokens) AS 輸入Token,sum(output_tokens) AS 輸出Token FROM usage GROUP BY provider,model"), "尚無 API 請求；Mock 不產生 Token 用量。")
        st.caption("成本僅在兩項單價及可查證的費率來源皆有設定時估算；未設定時保持空白。")
        record_table(rt.db.rows("SELECT provider,model,currency AS 幣別,sum(cost) AS 估算費用,count(cost) AS 可估算請求數 FROM usage GROUP BY provider,model,currency"), "尚無可統計的 API 費用。")


def current_plan(rt, w):
    q = rt.db.get("questionnaire", w.get("q_id", ""))
    c = rt.db.get("provider", w.get("provider_id", ""))
    people = [rt.db.get("persona", id) for id in w.get("person_ids", [])][:w.get("count", 10)]
    if not q or not c or any(p is None for p in people):
        from .errors import AppError
        raise AppError("選取資料已變動，請回前一步重新選擇。")
    return validated_plan(q, people, c, mode=w.get("mode", "natural"), seed=w.get("seed", 42),
                          interval_seconds=w.get("interval", 1), variability=w.get("variability", .15), budget_limit=w.get("budget_limit"),
                          **w.get("website_parameters", {}))


@st.fragment(run_every="2s")
def preview_panel(rt, w, spec):
    from .ui_operations import progress_view
    signature = fingerprint(spec)
    if w.get("preview_signature") != signature:
        w.pop("preview_task", None)
    if st.button("執行一人預覽", type="primary", disabled=bool(rt.runner.thread and rt.runner.thread.is_alive())):
        def run_preview():
            one = spec.model_copy(update={"personas": spec.personas[:1]}, deep=True)
            if one.website_survey:
                one.website_survey = one.website_survey.model_copy(update={"dry_run": True})
                one.website_workflow = one.website_workflow.model_copy(update={"mode": "preview", "require_server_receipt": False})
            id = rt.db.create_task(one)
            rt.runner.start(id)
            w.update(preview_task=id, preview_signature=signature)
        guarded(run_preview)
    task_id = w.get("preview_task")
    if task_id:
        progress_view(rt, task_id)
        responses = rt.db.responses(task_id)
        if responses:
            r = responses[0]
            qm = {q.id: q for q in r.questionnaire_snapshot.questions}
            st.dataframe(pd.DataFrame([{"題目": qm[a.question_id].title, "答案": display_answer(qm[a.question_id], a.value, a.other_text), "理由": a.rationale} for a in r.answers]), hide_index=True, width="stretch")
            st.success("一人預覽已完成並保存。請檢查答案後繼續。")
            if st.button("確認預覽，下一步", disabled=r.status == "error"):
                w["step"] = 5
                st.rerun()
    st.caption("預覽也可能產生真實 API 費用；Mock 無 API 費用。修改問卷、人物或參數後需重新預覽。")
    if spec.website_survey:
        st.caption("一人預覽只預覽網站設計與填寫問卷；完整批次才依保存設定提交。")


def wizard(rt):
    w = st.session_state.setdefault("wizard", {"step": 0})
    titles = ["選擇問卷", "選擇模型", "選擇受訪者", "模擬參數", "一人預覽", "執行與結果"]
    step = w["step"]
    st.progress((step + 1) / 6, text=f"步驟 {step+1} / 6 · {titles[step]}")
    if step > 0 and st.button("上一步"):
        w["step"] -= 1
        st.rerun()
    if step == 0:
        q = select_entity("要模擬的問卷", rt.db.list("questionnaire"), "wizard_q")
        upload = st.file_uploader("或匯入 JSON / CSV（包括官方 Forms JSON）", type=["json", "csv"], key="wizard_import")
        if upload and st.button("匯入為待確認草稿"):
            def do_import():
                text = upload.getvalue().decode("utf-8-sig")
                imported = import_json(text) if upload.name.lower().endswith(".json") else import_csv(text, upload.name)
                if rt.db.get("questionnaire", imported.id):
                    imported.id = uid()
                rt.db.save("questionnaire", imported)
                st.success("已保存草稿，請在問卷管理預覽與確認後回來。")
            guarded(do_import)
        st.button("建立或核對問卷", on_click=navigate, args=("問卷管理",))
        if q and not q.confirmed:
            st.warning("此問卷尚未人工確認，不能開始批次。")
        if st.button("下一步：選擇模型", type="primary", disabled=not q or not q.confirmed):
            w.update(q_id=q.id, step=1)
            st.rerun()
    elif step == 1:
        c = select_entity("模型設定檔", rt.db.list("provider"), "wizard_provider")
        ready, message = provider_ready(c, rt.secrets) if c else (False, "沒有可用設定")
        st.info(message)
        st.button("設定或測試模型", on_click=navigate, args=("AI 模型設定",))
        if st.button("下一步：受訪者", type="primary", disabled=not ready):
            w.update(provider_id=c.id, step=2)
            st.rerun()
    elif step == 2:
        persons = rt.db.list("persona")
        labels = {p.id: f"{p.name} · {p.archetype}" for p in persons}
        chosen = st.multiselect("使用已保存的人物", list(labels), default=list(labels)[:10], format_func=labels.get, key="wizard_people")
        with st.expander("生成新人物"):
            count = st.number_input("生成數量", 1, 1000, 10, key="wizard_generate_count")
            seed = st.number_input("人物種子", 0, 2_000_000_000, 42, key="wizard_generate_seed")
            choose_tier = st.checkbox("生成時由 AI 選定 ONLYFRAME 方案，之後固定沿用", key="wizard_choose_tier")
            if st.button("生成並保存"):
                def generate():
                    c = rt.db.get("provider", w["provider_id"])
                    q = rt.db.get("questionnaire", w["q_id"])
                    generator = PersonaGenerator(make_provider(c, rt.secrets.get(c.id, c.provider), rt.db))
                    generator.generate_batch(count, seed, q.topic, {"AI 自動混合": 1}, on_persona=lambda p, *_: rt.db.save("persona", p),
                        choose_website_tier=choose_tier, id_namespace=uid())
                    st.success("人物已保存，請從上方選取。")
                guarded(generate)
        if st.button("下一步：模擬參數", type="primary", disabled=not chosen):
            w.update(person_ids=chosen, step=3)
            st.rerun()
    elif step == 3:
        count = st.number_input("本次模擬人數", 1, len(w["person_ids"]), min(10, len(w["person_ids"])))
        mode = st.selectbox("回答模式", ["natural", "consistent", "custom"], format_func=lambda v: {"natural": "自然變動", "consistent": "高一致性", "custom": "自訂"}[v])
        seed = st.number_input("模擬種子", 0, 2_000_000_000, 42)
        interval, variability = 1., .15
        if st.session_state.get("ui_mode") == "進階模式":
            interval = st.number_input("人物間隔秒數", min_value=0., max_value=300., value=1.)
            variability = st.slider("自訂變動程度", 0., .5, .15, disabled=mode != "custom")
        budget = None
        if st.checkbox("啟用任務預算上限", key="wizard_budget_enable"):
            budget = st.number_input("任務費用上限（模型設定幣別）", min_value=0., value=10., key="wizard_budget_limit")
        from .ui_staged_survey import survey_options, prepare_survey_form
        website_parameters, website_error = survey_options(rt, rt.db.get("questionnaire", w["q_id"]), "wizard_survey")
        if st.button("下一步：預覽測試", type="primary", disabled=bool(website_error)):
            website_parameters = prepare_survey_form(rt, dict(website_parameters))
            w.update(count=count, mode=mode, seed=seed, interval=interval, variability=variability, budget_limit=budget, step=4)
            w["website_parameters"] = {key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value for key,value in website_parameters.items()}
            st.rerun()
    elif step == 4:
        spec = guarded(lambda: current_plan(rt, w))
        if spec:
            preview_panel(rt, w, spec)
    else:
        spec = guarded(lambda: current_plan(rt, w))
        if not spec:
            return
        st.write(f"問卷：{spec.questionnaire.title} · 模型：{spec.provider.name} · 人物：{len(spec.personas)} 位")
        confirmed_preview = w.get("preview_signature") == fingerprint(spec) and bool(rt.db.responses(w.get("preview_task", "")))
        if not confirmed_preview:
            st.warning("設定已變更，請回上一步重新預覽。")
        if st.button("開始完整模擬", type="primary", disabled=not confirmed_preview or bool(w.get("batch_task"))):
            def start():
                id = rt.db.create_task(spec)
                rt.runner.start(id)
                w["batch_task"] = id
            guarded(start)
        if w.get("batch_task"):
            from .ui_operations import progress_view
            batch_id = w["batch_task"]
            status = rt.db.task(batch_id)["status"]
            controls = st.columns(3)
            if controls[0].button("繼續本批次", disabled=status not in {"paused", "stopped", "budget_paused", "provider_paused"}):
                guarded(lambda: rt.runner.start(batch_id))
            if controls[1].button("暫停本批次", disabled=status != "running"):
                rt.runner.pause(batch_id)
            if controls[2].button("停止本批次", disabled=status not in {"running", "paused", "budget_paused", "provider_paused"}):
                rt.runner.stop(batch_id)
            progress_view(rt, batch_id)
            from .ui_results import export_buttons
            export_buttons(rt, w["batch_task"])
            st.button("查看回答", on_click=navigate, args=("回答檢查",))
        if st.button("建立另一個模擬"):
            st.session_state["wizard"] = {"step": 0}
            st.rerun()
