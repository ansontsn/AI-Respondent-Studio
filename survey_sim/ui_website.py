from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from .models import TaskSpec, WebsiteWorkflow
from .ui import guarded, select_entity
from .ui_operations import progress_view
from .ui_people import active_provider
from .website_experience import WebsiteExperience, check_workflow, make_plan, compact_facts, website_test_questionnaire, TEST_BINDINGS, TIERS, assign_tiers, workflow_for_person, release_blocked_submission

LABELS = {"running":"操作中", "preview_completed":"成品預覽完成", "local_saved":"已存本機；未證明雲端收到",
          "server_confirmed":"雲端已確認接收", "failed":"操作失敗", "blocked":"提交被阻擋；設計未送出", "unknown":"提交結果待查；禁止重送", "interrupted":"已中斷"}


def show_run(run):
    st.write("**" + LABELS[run.status] + "**")
    st.write(run.message)
    if run.network_events:
        with st.expander("接收請求與核對紀錄"):
            st.dataframe(run.network_events, hide_index=True, width="stretch")
    st.json(compact_facts(run), expanded=False)
    for image in run.screenshots:
        if Path(image).is_file():
            st.image(image, caption=Path(image).stem, width=800)
    st.download_button("下載操作紀錄 JSON", run.model_dump_json(indent=2), "website-run.json", "application/json", key="download_" + run.id)
    if run.receipt_file and Path(run.receipt_file).is_file():
        st.download_button("下載已保存的完整設計", Path(run.receipt_file).read_bytes(), "saved-design.json", "application/json", key="receipt_" + run.id)


def website_page(rt):
    st.caption("可接續前段問卷 → 網站設計 → 體驗題。人物生成時由 AI 選定方案，分階段流程固定沿用；BASIC 選框色、CUSTOM 加文字、PREMIUM 加背景與貼飾。")
    st.info("2026-10-14 已偵測到公開網站設定 Supabase。提交前請核對接收 API 並確認 AI 測試設計與真人研究紀錄分開；平台只在有相符接收證據時顯示雲端成功。正式 Google 問卷不會由此頁提交。")
    notice=st.session_state.pop("website_flow_notice",None)
    if notice:
        st.warning(notice)
    workflows = rt.db.list("website_workflow")
    with st.expander("匯入已下載的流程設定"):
        uploaded = st.file_uploader("網站流程 JSON", type=["json"], key="website_flow_upload")
        if uploaded and st.button("匯入網站流程"):
            def import_workflow():
                model = WebsiteWorkflow.model_validate_json(uploaded.getvalue())
                check_workflow(model)
                if model.mode=="submit" and not model.submission_endpoint:
                    from .website_experience import detect_submission_endpoint
                    detected = detect_submission_endpoint(model)
                    if detected:
                        st.session_state[detected_key] = detected
                        st.session_state["website_flow_notice"]="已偵測網站使用雲端。請核對進階欄位帶入的接收網址，再儲存一次；目前不會送出。"
                        st.rerun()
                rt.db.save("website_workflow", model)
                st.session_state["website_pending_choice"] = model.id
                st.rerun()
            guarded(import_workflow)
    by_id = {w.id: w for w in workflows}
    pending = st.session_state.pop("website_pending_choice", None)
    if pending in by_id:
        st.session_state["website_workflow_choice"] = pending
        st.success("網站流程已儲存，下方執行會使用這個設定。")
    chosen = st.selectbox("網站操作設定", ["new"] + list(by_id), index=1 if by_id else 0, format_func=lambda v: "建立新流程" if v == "new" else by_id[v].name, key="website_workflow_choice")
    w = by_id.get(chosen) or WebsiteWorkflow()
    detected_key = "website_detected_" + chosen
    if st.button("偵測網站設計接收網址（唯讀）"):
        from .website_experience import detect_submission_endpoint
        detected = guarded(lambda: detect_submission_endpoint(w))
        if detected:
            st.session_state[detected_key] = detected
            st.success("已讀到公開設定。進階欄位已帶入網址，請核對並儲存；偵測不代表雲端 API 已驗證成功。")
        elif detected == "":
            st.info("未讀到可確認的雲端設定，可保留預覽或人工核對。")
    with st.form("website_workflow_editor"):
        name = st.text_input("流程名稱", w.name)
        tier = st.selectbox("單人預設方案", TIERS, index=TIERS.index(w.tier))
        url = st.text_input("網站網址", w.url)
        allowlist = st.text_area("允許清單（每行完整網址）", "\n".join(w.allowlist))
        mode = st.selectbox("結束方式", ["preview", "submit"], index=["preview", "submit"].index(w.mode),
                            format_func=lambda v: "僅成品預覽（預設）" if v == "preview" else "提交設計並核對保存紀錄")
        authorized = st.checkbox("我確認此網站允許保存 AI 測試設計，且會與真人研究設計分開管理", value=w.authorized_test)
        plan_mode = st.selectbox("人物設計方式", ["persona_rules", "recorded"], index=["persona_rules", "recorded"].index(w.plan_mode),
                                  format_func=lambda v: "依人物興趣與偏好產生設計（規則，不花 API Token）" if v == "persona_rules" else "重播已驗證的固定設計")
        text = st.text_input("客製文字（留白由人物興趣產生）", w.design_text, max_chars=40)
        contact_name = st.text_input("測試聯絡姓名", w.contact_name)
        use_name = st.checkbox("提交時使用人物生成時的姓名", value=w.use_persona_name)
        st.caption("勾選後，每位人物沿用自己的姓名；上方固定測試姓名僅在未勾選時使用。")
        contact_email = st.text_input("測試聯絡信箱", w.contact_email)
        with st.expander("進階：雲端接收與操作逾時"):
            st.caption("只有網站確實使用雲端後，才填經核對的 /rest/v1/design_submissions 完整網址；不是 AI API Base URL。此處不填任何 API Key。")
            endpoint = st.text_input("允許的設計接收 API（本機保存留空）", st.session_state.get(detected_key, w.submission_endpoint))
            require_server = st.checkbox("必須取得雲端接收證明，才產生後續回答", value=w.require_server_receipt)
            timeout = st.number_input("單步及提交核對逾時（秒）", min_value=3, max_value=180, value=w.timeout_seconds)
        if st.form_submit_button("儲存網站流程", type="primary"):
            def save():
                model = WebsiteWorkflow(id=w.id, name=name, tier=tier, url=url, mode=mode, authorized_test=authorized,
                    allowlist=[s.strip() for s in allowlist.splitlines() if s.strip()], plan_mode=plan_mode,
                    design_text=text, contact_name=contact_name, use_persona_name=use_name, contact_email=contact_email,
                    submission_endpoint=endpoint, require_server_receipt=require_server, timeout_seconds=timeout)
                check_workflow(model)
                rt.db.save("website_workflow", model)
                st.session_state["website_pending_choice"] = model.id
                st.rerun()
            guarded(save)
    if chosen == "new":
        st.caption("先儲存流程，再從上方選單選取它。")
        return
    st.download_button("下載流程設定", w.model_dump_json(indent=2), "website-workflow.json", "application/json")
    person = select_entity("單人操作預覽", rt.db.list("persona"), key="website_person")
    seed = st.number_input("網站與答題 Seed", min_value=0, max_value=2_000_000_000, value=42)
    if person:
        person_workflow = w.model_copy(update={"tier": person.onlyframe_tier}) if person.onlyframe_tier else w
        if person.onlyframe_tier:
            st.caption("此人物固定使用 " + person.onlyframe_tier + "；單人操作也沿用這個方案。")
        st.json(make_plan(person_workflow, person, seed).model_dump(), expanded=False)
        if st.button("執行一次" + ("預覽" if w.mode == "preview" else "設計提交"), type="primary"):
            def execute():
                if rt.runner.thread and rt.runner.thread.is_alive():
                    st.error("目前批次仍在執行，請先暫停批次再執行單人操作。")
                    return
                with st.spinner("依已保存流程操作網站並核對結果…"):
                    run = WebsiteExperience(rt.db).run(person_workflow, person, seed)
                st.session_state["website_last_run"] = run.id
                st.success("操作紀錄已保存；本次瀏覽器流程沒有 AI API 請求。")
            guarded(execute)
    st.divider()
    st.subheader("問卷與網站體驗流程")
    if st.button("建立分階段流程測試問卷"):
        from .website_experience import staged_test_questionnaire
        if not rt.db.get("questionnaire", "onlyframe-staged-test-v1"):
            rt.db.save("questionnaire", staged_test_questionnaire())
            st.success("已建立三頁流程測試問卷，請到問卷管理核對並確認；第二頁後前往網站。")
        else:
            st.info("分階段測試問卷已存在，可到問卷管理查看。")
    if st.button("建立獨立的網站操作測試問卷"):
        if not rt.db.get("questionnaire", "onlyframe-website-test-v2"):
            rt.db.save("questionnaire", website_test_questionnaire())
            st.success("已建立 8 題測試問卷。請到問卷管理檢查並確認後再執行；沒有修改正式問卷。")
        else:
            st.info("測試問卷已存在，可到問卷管理查看。")
    questionnaire = select_entity("操作後使用的測試問卷", [q for q in rt.db.list("questionnaire") if q.purpose == "test" and q.confirmed], key="website_q")
    provider = active_provider(rt)
    people = rt.db.list("persona")
    ids = st.multiselect("網站操作人物", [p.id for p in people], format_func=lambda id: next(p.name for p in people if p.id == id))
    from .ui_staged_survey import survey_options, prepare_survey_form
    website_parameters, website_error = survey_options(rt, questionnaire, "website_survey", workflow=w,
        default=bool(questionnaire and len(questionnaire.pages) > 1))
    staged = bool(st.session_state.get("website_survey_enabled"))
    if staged and ids:
        st.dataframe([{"人物": p.name, "固定方案": p.onlyframe_tier or "尚未選定", "方案理由": p.onlyframe_tier_reason} for p in people if p.id in ids], hide_index=True)
    assignments = {}
    allocation_error = website_error
    has_fixed_tier = any(p.onlyframe_tier for p in people if p.id in ids)
    mixed = False if staged else st.checkbox("分配人物至三種方案", value=not has_fixed_tier, disabled=has_fixed_tier)
    if has_fixed_tier and not staged:
        st.caption("已選人物含固定方案，沿用人物方案；尚未指定方案的人物使用網站流程的預設方案。")
    if mixed:
        count = len(ids)
        cols = st.columns(3)
        counts = {tier: cols[index].number_input(tier + " 人數", min_value=0, max_value=10000,
                  value=count // 3 + (1 if index < count % 3 else 0), key=f"website_count_{tier}_{count}") for index,tier in enumerate(TIERS)}
        if ids:
            try:
                assignments = assign_tiers([p for p in people if p.id in ids], counts, seed)
                st.dataframe([{"人物姓名":p.name, "人物 ID":p.id, "分配方案":assignments[p.id]} for p in people if p.id in ids], hide_index=True)
                if not all(counts.values()):
                    st.caption("目前有人數為 0 的方案；三種流程都要有人執行時，請各分配至少 1 人。")
            except Exception as exc:
                allocation_error = str(exc)
                st.warning(allocation_error)
    reuse = False if staged else st.checkbox("優先使用同人物、同設計的已完成操作紀錄（避免重新提交）", value=True)
    budget = st.number_input("API 預算上限（0 = 不設定，模型費率幣別）", min_value=0., value=0.)
    st.caption("每位人物每頁通常一次 AI 請求；格式修正及網路重試採有限次數。真實 Token 與費用以模型回報及設定費率為準。")
    if st.button("建立網站操作與答題任務", disabled=not(questionnaire and provider and ids) or bool(allocation_error)):
        def create():
            parameters = {"website_workflow": w, "compact_context": True,
                "website_fact_bindings": TEST_BINDINGS if questionnaire.id in {"onlyframe-website-test-v1", "onlyframe-website-test-v2"} else {},
                "website_tier_assignments": assignments}
            parameters.update(prepare_survey_form(rt, dict(website_parameters)))
            spec = TaskSpec(questionnaire=questionnaire, provider=provider, personas=[p for p in people if p.id in ids],
                seed=seed, budget_limit=budget or None, **parameters)
            id = rt.db.create_task(spec)
            if reuse:
                for person in spec.personas:
                    person_workflow = workflow_for_person(spec, person.id)
                    old = next((r for r in rt.db.list("website_run") if r.persona_id == person.id and r.url == w.url and r.mode == w.mode and
                                r.plan == make_plan(person_workflow, person, seed) and r.status in {"preview_completed", "local_saved", "server_confirmed"} and
                                (not w.require_server_receipt or r.status == "server_confirmed")), None)
                    if old:
                        rt.db.checkpoint(id, person.id, {"website_run": old.model_dump(mode="json")})
            st.session_state["website_task"] = id
            st.success("任務已建立，按開始執行；也可到 AI 模擬控制台管理它。")
        guarded(create)
    task_id = st.session_state.get("website_task")
    if task_id:
        cols = st.columns(4)
        if cols[0].button("開始 / 繼續網站任務"):
            guarded(lambda: rt.runner.start(task_id))
        if cols[1].button("暫停網站任務"):
            rt.runner.pause(task_id)
        if cols[2].button("停止網站任務"):
            rt.runner.stop(task_id)
        if cols[3].button("重排失敗回答"):
            rt.db.retry_failed(task_id)
        progress_view(rt, task_id)
    st.divider()
    runs = rt.db.list("website_run")
    if runs:
        lookup = {r.id:r for r in runs}
        selected = st.selectbox("網站操作歷史", list(lookup), format_func=lambda id: lookup[id].created_at[:19] + " · " + (lookup[id].persona_name or lookup[id].persona_id[:8]) + " · " + lookup[id].plan.tier + " · " + LABELS[lookup[id].status])
        show_run(lookup[selected])
        old = lookup[selected]
        if old.status=="blocked" and old.insert_sent is False:
            if st.button("修正設定後，解除這筆未送出的重試限制", key="unlock_"+old.id):
                def unlock():
                    release_blocked_submission(rt.db,old.id)
                    st.success("確認新增請求未送出，已解除這筆限制；原紀錄仍保留。請選原人物及流程再執行，不會自動提交。")
                guarded(unlock)
