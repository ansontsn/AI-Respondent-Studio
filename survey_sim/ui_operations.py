from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .automation import FormAutomation
from .models import TaskSpec, FormTarget
from .security import clean_form_url
from .ui import guarded, select_entity, record_table
from .ui_people import active_provider

STATUSES = {"ready": "待執行", "running": "執行中", "paused": "已暫停", "stopped": "已停止", "failed": "失敗",
            "completed": "已完成", "completed_with_errors": "完成但有錯誤", "pending": "待執行", "invalid": "回答需修正",
            "passed": "通過", "review": "需要人工檢查", "error": "明確錯誤", "success": "已確認成功", "unknown": "提交狀態不明", "dry_run": "僅填寫預覽"}
STATUSES.update({"budget_paused": "預算限制暫停", "cancelled": "已取消", "provider_paused": "AI 服務錯誤暫停"})
STATUSES["blocked"]="提交被阻擋；未送出"
STATUSES["skipped"] = "已略過"


@st.fragment(run_every="2s")
def progress_view(rt, task_id):
    task = rt.db.task(task_id)
    items = rt.db.rows("SELECT persona_id,status,attempts,error,checkpoint FROM task_items WHERE task_id=?", (task_id,))
    # Every item that will not run again counts as processed (skipped / unknown included).
    completed = sum(x["status"] not in {"pending", "running"} for x in items)
    st.progress(completed / len(items) if items else 0., text=f"{STATUSES.get(task['status'],task['status'])} · {completed} / {len(items)}")
    phases = {"pre_survey": "填寫前段問卷", "website": "網站設計", "post_survey": "接續體驗題", "form_finish": "核對問卷提交", "completed": "已完成"}
    display_items = [{**{k:v for k,v in item.items() if k != "checkpoint"},
                      "目前階段": phases.get(json.loads(item["checkpoint"]).get("phase"), "")} for item in items]
    frame = pd.DataFrame(display_items)
    if not frame.empty:
        frame["status"] = frame["status"].map(lambda v: STATUSES.get(v, v))
    st.dataframe(frame.rename(columns={"persona_id": "人物 ID", "status": "狀態", "attempts": "嘗試次數", "error": "失敗原因"}), hide_index=True, width="stretch")
    events = rt.db.rows("SELECT level,message,created_at FROM events WHERE task_id=? ORDER BY id DESC LIMIT 15", (task_id,))
    st.dataframe(pd.DataFrame(events).rename(columns={"level": "等級", "message": "紀錄", "created_at": "時間（UTC）"}), hide_index=True, width="stretch")


def console_page(rt):
    st.caption("先預覽人物，再建立任務。每個任務固定保存人物、問卷及模型設定快照，已完成結果即時入庫。")
    q = select_entity("指定問卷", rt.db.list("questionnaire"))
    c = active_provider(rt)
    people = rt.db.list("persona")
    labels = {p.id: f"{p.name} · {p.archetype}" for p in people}
    ids = st.multiselect("選擇人物", list(labels), default=list(labels), format_func=labels.get)
    if ids:
        st.dataframe(pd.DataFrame([{"人物": p.name, "類型": p.archetype, "職業": p.background.occupation,
                                  "預算": p.behavior.spending_budget, "固定方案": p.onlyframe_tier or "未指定"} for p in people if p.id in ids]), hide_index=True)
    a, b, d = st.columns(3)
    mode = a.selectbox("回答模式", ["consistent", "natural", "custom"], index=1,
        format_func=lambda v: {"consistent": "高一致性", "natural": "自然變動", "custom": "自訂"}[v])
    seed = b.number_input("答題 Random Seed", min_value=0, max_value=2_000_000_000, value=42)
    interval = d.number_input("人物請求間隔（秒）", min_value=0., max_value=300., value=1.)
    variability = st.slider("自訂回答變動程度", 0., .5, .15, step=.01, disabled=mode != "custom")
    from .ui_staged_survey import survey_options, prepare_survey_form
    website_parameters, website_error = survey_options(rt, q, "console_survey")
    budget = None
    if st.checkbox("設定本次任務預算上限"):
        budget = st.number_input("費用上限（" + (c.rate_currency if c else "模型幣別") + "）", min_value=0., value=10.)
    if q and c and ids:
        from .costs import task_estimate
        estimate = task_estimate(TaskSpec(questionnaire=q, personas=[p for p in people if p.id in ids], provider=c))
        if estimate["high"] is None:
            st.caption(estimate["method"])
        else:
            st.caption(f"任務規劃費用：約 {estimate['low']:.6f}–{estimate['high']:.6f} {estimate['currency']}；{estimate['method']}")
    st.caption("一次執行一個批次；遇到 429 / 5xx 採有限退避重試。暫停及停止在當前請求完成、頁面保存後生效。")
    if st.button("建立批次任務", type="primary", disabled=not(q and c and ids) or bool(website_error)):
        def create():
            spec = TaskSpec(questionnaire=q, personas=[p for p in people if p.id in ids], provider=c, mode=mode,
                            seed=seed, interval_seconds=interval, variability=variability, budget_limit=budget,
                            **prepare_survey_form(rt, dict(website_parameters)))
            id = rt.db.create_task(spec)
            st.session_state["latest_task"] = id
            st.success("任務已建立，人物及設定已保存。按下開始執行。")
        guarded(create)
    st.divider()
    tasks = rt.db.rows("SELECT id,status,created_at FROM tasks ORDER BY created_at DESC")
    if not tasks:
        st.info("尚無任務。先建立人物，再建立批次。")
        return
    by_id = {t["id"]: t for t in tasks}
    task_id = st.selectbox("任務紀錄", list(by_id), format_func=lambda v: f"{by_id[v]['created_at'][:19]} · {STATUSES.get(by_id[v]['status'],by_id[v]['status'])} · {v[:8]}")
    columns = st.columns(5)
    if columns[0].button("開始 / 繼續", type="primary"):
        guarded(lambda: rt.runner.start(task_id))
    if columns[1].button("暫停"):
        guarded(lambda: rt.runner.pause(task_id))
    if columns[2].button("停止"):
        guarded(lambda: rt.runner.stop(task_id))
    if columns[3].button("重新排入失敗項目"):
        guarded(lambda: rt.db.retry_failed(task_id))
    if columns[4].button("更新狀態"):
        st.rerun()
    progress_view(rt, task_id)
    with st.expander("即時 API 用量與預算控制"):
        from .ui_v2_analysis import budget_controls
        budget_controls(rt, task_id)
    with st.expander("任務設定快照"):
        st.json(json.loads(rt.db.task(task_id)["spec"]))


def automation_page(rt):
    st.caption("先預覽操作與 Dry Run，再提交經確認授權的測試表單。提交狀態不明時會阻擋同份回答再次送出。")
    responses = rt.db.responses()
    if not responses:
        st.info("尚未產生回答。請先到 AI 模擬控制台完成任務。")
        return
    by_id = {r.id: r for r in responses}
    id = st.selectbox("填寫使用的回答", list(by_id), format_func=lambda v: f"{by_id[v].persona_snapshot.name} · {by_id[v].questionnaire_snapshot.title} · {v[:8]}")
    response = by_id[id]
    targets = [t for t in rt.db.list("target") if t.questionnaire_id == response.questionnaire_id]
    tmap = {t.id: t for t in targets}
    selected = st.selectbox("測試表單", ["local_new", "new"] + list(tmap), format_func=lambda v: "建立本地 Mock Form" if v == "local_new" else "設定外部測試表單" if v == "new" else tmap[v].name)
    target = tmap.get(selected)
    if selected == "local_new":
        st.info("本地表單包含目前問卷的題型、條件顯示及多頁分流；只在這台電腦接收測試回答。")
        if st.button("啟動並保存本地測試表單"):
            def create_local():
                server = rt.local_form()
                target = FormTarget(name=response.questionnaire_snapshot.title + " · 本地測試", url=server.url(response.questionnaire_id),
                    questionnaire_id=response.questionnaire_id, kind="local", authorized=True, success_selector="#success[data-receipt]")
                rt.db.save("target", target)
                allow = rt.setting("url_allowlist", [])
                rt.set_setting("url_allowlist", sorted(set(allow + [target.url])))
                st.success("本地表單已保存並列入允許清單。請在測試表單選單選取它。")
            guarded(create_local)
    else:
        t = target or FormTarget(name="外部測試表單", url="", questionnaire_id=response.questionnaire_id, kind="google")
        with st.form("target_editor"):
            name = st.text_input("表單名稱", t.name)
            url = st.text_input("完整測試 URL", t.url)
            kind = st.selectbox("表單類型", ["google", "custom", "local"], index=["google", "custom", "local"].index(t.kind))
            authorized = st.checkbox("我確認這是自有或明確授權的測試表單，允許送入虛擬答案", value=t.authorized)
            success_selector = st.text_input("成功狀態 CSS Selector（需提交後才出現）", t.success_selector)
            success_text = st.text_input("或：成功訊息完整文字", t.success_text)
            next_text = st.text_input("下一頁按鈕文字", t.next_text)
            submit_text = st.text_input("提交按鈕文字", t.submit_text)
            if st.form_submit_button("保存測試表單"):
                def save_target():
                    saved = FormTarget(id=t.id, name=name, url=clean_form_url(url), questionnaire_id=response.questionnaire_id, kind=kind,
                        authorized=authorized, success_selector=success_selector, success_text=success_text, next_text=next_text, submit_text=submit_text)
                    rt.db.save("target", saved)
                    st.success("設定已保存。外部網址需另加入下方允許清單。")
                    if url.strip() != saved.url:
                        st.info("已移除分享參數並統一網址：" + saved.url)
                guarded(save_target)
    allowlist = st.text_area("URL Allowlist（每行一個完整網址，精確比對）", "\n".join(rt.setting("url_allowlist", [])))
    if st.button("保存允許清單"):
        def save_allowlist():
            allowed = [clean_form_url(line.strip()) for line in allowlist.splitlines() if line.strip()]
            rt.set_setting("url_allowlist", allowed)
            st.success("允許清單已保存。")
        guarded(save_allowlist)
    automation = FormAutomation(rt.db, rt.data_dir / "artifacts")
    with st.expander("填寫操作預覽", expanded=True):
        st.dataframe(pd.DataFrame(automation.plan(response)).astype(str), hide_index=True, width="stretch")
    if target:
        st.link_button("開啟測試表單", target.url)
        a, b = st.columns(2)
        dry = a.button("執行 Dry Run", type="primary")
        submit = b.button("執行授權測試提交", disabled=not target.authorized)
        if dry or submit:
            def run():
                if target.kind == "local":
                    rt.local_form()
                return automation.run(target, response, rt.setting("url_allowlist", []), dry_run=dry)
            with st.spinner("正在操作瀏覽器並確認結果…"):
                result = guarded(run)
            if result:
                st.success(result["message"])
                if result["artifact"]:
                    st.image(result["artifact"], caption="測試操作結果", width="stretch")
    st.subheader("操作紀錄")
    record_table(rt.db.rows("SELECT id,url,dry_run,status,message,created_at FROM submissions ORDER BY created_at DESC LIMIT 30"))
    unknown = rt.db.rows("SELECT id,url FROM submissions WHERE status='unknown'")
    if unknown:
        with st.expander("人工處理提交狀態不明的紀錄"):
            selected_id = st.selectbox("待查證紀錄", [r["id"] for r in unknown])
            resolution = st.selectbox("在表單接收端查證的結果", ["success", "failed"], format_func=lambda v: "已確認收到（保留禁止重複）" if v == "success" else "已確認未收到（允許重新測試）")
            checked = st.checkbox("我已查閱接收端紀錄，確認上述結果")
            if st.button("保存人工查證", disabled=not checked):
                if guarded(lambda: rt.db.resolve_submission(selected_id, resolution) or True):
                    st.success("查證結果已保存。" + ("未收到的回答可在批次按「重新執行失敗項目」再填表。" if resolution == "failed" else ""))
