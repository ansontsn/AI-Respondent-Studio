import json
import os

import pandas as pd
import streamlit as st

from .models import FormTarget, ProviderConfig, Response
from .ui import guarded, record_table, select_entity
from .v2_models import PersonaConditions, PersonaGroup, WorkbenchSpec
from .workbench import WorkbenchService

# History tools shown in simple mode; the rest (older parallel entry points and the
# optional ONLYFRAME website flow) remain available in advanced mode.
CORE_TOOLS = {"回答檢查", "回答品質", "結果分析", "自動填表測試", "系統設定"}
MODES = {"answers": "產生、驗證並匯出模擬答案（預設）", "personas": "只建立或選取人物", "dry_run": "產生答案並批次填表 Dry Run", "submit": "提交到已授權測試表單"}


def people_selector(rt, key):
    people = rt.db.list("persona")
    by_id = {p.id: p for p in people}
    selection_key = key + "_selection"
    st.session_state.setdefault(selection_key, [i for i in rt.setting("selected_personas", []) if i in by_id])
    search = st.text_input("搜尋姓名、職業或興趣", key=key + "_search")
    with st.expander("依人物特徵篩選"):
        age = st.slider("年齡範圍", 18, 100, (18, 100), key=key + "_age")
        jobs = st.multiselect("篩選職業", sorted({p.background.occupation for p in people}), key=key + "_jobs")
        genders = st.multiselect("篩選性別", sorted({p.background.gender for p in people}), key=key + "_gender")
        from .personas import TRAIT_LABELS
        trait = st.selectbox("篩選人格特徵", [None] + list(TRAIT_LABELS), format_func=lambda v: "不限制" if v is None else TRAIT_LABELS[v], key=key + "_trait")
        bounds = st.slider("特徵範圍", 0., 1., (0., 1.), key=key + "_bounds") if trait else (0., 1.)
    filtered = [p for p in people if age[0] <= p.background.age <= age[1] and
        (not jobs or p.background.occupation in jobs) and (not genders or p.background.gender in genders) and
        (not trait or bounds[0] <= getattr(p.traits, trait) <= bounds[1]) and
        search.casefold() in (p.name + p.background.occupation + "、".join(p.background.interests)).casefold()]
    groups = {g.id: g for g in rt.db.list("persona_group")}
    group = st.selectbox("常用人物群組", [None] + list(groups), format_func=lambda i: "未選取群組" if i is None else groups[i].name, key=key + "_group")
    a, b, c = st.columns(3)
    if a.button("全選篩選結果", key=key + "_all"):
        st.session_state[selection_key] = list(dict.fromkeys(st.session_state[selection_key] + [p.id for p in filtered]))
    if b.button("取消全選", key=key + "_clear"):
        st.session_state[selection_key] = []
    if c.button("套用人物群組", disabled=group is None, key=key + "_apply"):
        st.session_state[selection_key] = [i for i in groups[group].persona_ids if i in by_id]
    selected = [i for i in st.session_state[selection_key] if i in by_id]
    options = list(dict.fromkeys([p.id for p in filtered] + selected))
    ids = st.multiselect("選取人物", options, format_func=lambda i: f"{by_id[i].name} · {by_id[i].background.age} 歲 · {by_id[i].background.occupation}", key=selection_key)
    st.caption(f"已選 {len(ids)} 位人物 · 篩選符合 {len(filtered)} 位；已選人物在變更篩選時仍會保留。")
    name = st.text_input("人物群組名稱", key=key + "_group_name")
    if st.button("儲存人物群組", disabled=not ids or not name.strip(), key=key + "_save_group"):
        def save():
            existing = next((g for g in groups.values() if g.name == name.strip()), None)
            model = PersonaGroup(name=name.strip(), persona_ids=ids)
            if existing:
                model.id = existing.id
            rt.db.save("persona_group", model)
            st.success("人物群組已保存，可在工作台重用。")
        guarded(save)
    return [by_id[i] for i in ids]


def people_library(rt):
    from .ui_people import people_page
    view = st.radio("人物資料庫操作", ["選取與群組", "建立與編輯"], horizontal=True, key="people_view")
    if view == "建立與編輯":
        people_page(rt)
        return
    selected = people_selector(rt, "library")
    if selected:
        st.dataframe([{"人物": p.name, "年齡": p.background.age, "職業": p.background.occupation,
            "所得": p.background.monthly_income, "興趣": "、".join(p.background.interests)} for p in selected], hide_index=True, width="stretch")
    def use_selection():
        rt.set_setting("selected_personas", [p.id for p in selected])
        st.session_state["wb_people_selection"] = [p.id for p in selected]
        st.session_state["nav"] = "問卷工作台"
    st.button("使用這些人物進入問卷工作台", disabled=not selected, on_click=use_selection, type="primary")


def form_settings(rt, q, mode):
    if not q:
        return None, [], False
    if q.purpose != "test":
        st.warning("此問卷標記為正式研究參考，可匯出模擬答案；不能自動填表或提交。")
        return None, [], False
    destinations = ["本機測試表單", "已保存的測試表單"] + (["這份 Google Forms"] if q.source_url else [])
    destination = st.selectbox("填表目的地", destinations, key="wb_destination")
    if destination == "已保存的測試表單":
        target = select_entity("測試表單", [t for t in rt.db.list("target") if t.questionnaire_id == q.id and t.purpose == "test"], "wb_target")
    elif destination == "這份 Google Forms":
        target = FormTarget(name=q.title + " · 授權測試", url=q.source_url, questionnaire_id=q.id, kind="google")
        message = st.text_input("表單實際成功畫面的完整文字", placeholder="請填入送出後真正顯示的文字", key="wb_success_text")
        target.success_text = message
    else:
        port = int(os.getenv("MOCK_FORM_PORT", "8765"))
        target = FormTarget(name=q.title + " · 本機測試", url=f"http://127.0.0.1:{port}/form/{q.id}", questionnaire_id=q.id,
            authorized=True, success_selector="#success[data-receipt]")
    if not target:
        return None, [], False
    st.code(target.url, language=None)
    authorized = st.checkbox("我擁有或已取得此測試表單授權，允許送入 AI 模擬答案", value=target.authorized, key="wb_authorized")
    target = target.model_copy(update={"authorized": authorized})
    confirmed = st.checkbox("本次確定將模擬答案提交到以上測試表單", key="wb_submit_confirm") if mode == "submit" else False
    if mode == "dry_run":
        st.info("Dry Run 只填寫及保存預覽。Google 多頁翻頁會傳送當頁資料，因此仍須授權；不點最後提交。")
    else:
        st.warning("格式、必填或跳題錯誤會略過；只有『AI 不確定』或人物層級提醒（例如預算註記）的答案可送到已授權測試表單，提醒仍保留。外部表單須填寫實際成功文字。")
    return target, [target.url], confirmed


def start_blockers(busy, mode, source, q, conditions, people, count, response_ids, target, submit_confirmed):
    """Every reason the start button is disabled, in the order the user can fix them."""
    reasons = []
    if busy:
        reasons.append("已有批次執行中，請等待完成或先暫停 / 取消。")
    if source == "使用已驗證答案" and mode not in {"dry_run", "submit"}:
        reasons.append("「使用已驗證答案」只能搭配「批次填表 Dry Run」或「提交到已授權測試表單」。")
    if mode != "personas" and not q:
        reasons.append("請選擇或讀取一份問卷。")
    elif mode != "personas" and not q.confirmed:
        reasons.append("請勾選「所有題目、選項、頁面、必填及跳題已核對」確認問卷。")
    if conditions is None:
        reasons.append("人物條件設定有誤，請依上方紅色訊息修正。")
    if not people and not count and not response_ids:
        reasons.append({"使用現有人物": "請至少選取一位人物。", "AI 自動建立人物": "請設定要建立的人數。"}.get(source, "請至少選取一份已驗證答案。"))
    if mode in {"dry_run", "submit"} and not target:
        reasons.append("請指定填表目的地（測試表單）。")
    if mode == "submit" and target:
        if not target.authorized:
            reasons.append("請勾選已取得此測試表單的授權。")
        if not submit_confirmed:
            reasons.append("請勾選「本次確定將模擬答案提交到以上測試表單」。")
        if target.kind != "local" and not (target.success_selector or target.success_text.strip()):
            reasons.append("請填寫表單送出後實際顯示的成功文字。")
    return reasons


def workbench_page(rt):
    st.caption("AI 模擬資料工作區。設定一次，即可建立人物、產生答案、驗證、儲存及匯出；預設不提交外部表單。")
    mode = st.selectbox("執行內容", list(MODES), format_func=MODES.get, key="wb_mode")
    source = st.radio("人物與答案來源", ["使用現有人物", "AI 自動建立人物", "使用已驗證答案"], horizontal=True, key="wb_source")
    st.subheader("1. 問卷設定")
    q = None
    if mode != "personas" or source == "使用已驗證答案":
        import_mode = st.radio("問卷來源", ["已保存問卷", "Google Forms 網址"], horizontal=True, key="wb_questionnaire_source")
        if import_mode == "Google Forms 網址":
            from .parsers import import_google
            url = st.text_input("Google Forms 網址", placeholder="https://docs.google.com/forms/.../viewform", key="wb_url")
            refresh = st.button("重新讀取問卷", disabled=not url)
            if url and (url != st.session_state.get("wb_read_url") or refresh):
                with st.spinner("唯讀解析題目、選項、必填及分流…"):
                    imported = guarded(lambda: import_google(url))
                st.session_state.update(wb_read_url=url, wb_imported=imported)
            q = st.session_state.get("wb_imported") if url else None
        else:
            q = select_entity("本次問卷", rt.db.list("questionnaire"), "wb_questionnaire")
        if q:
            from .questionnaire_review import confirm_questionnaire, review_report
            from .ui_questionnaires import TYPES
            info = review_report(q)
            st.write(f"{q.title} · {info['questions']} 題 · {info['pages']} 頁 · 必填 {info['required']} 題 · 跳題 {info['routes'] + info['conditions']} 處")
            with st.expander("題目、選項與跳題預覽"):
                st.dataframe([{"題目 ID": item.id, "題目": item.title, "題型": TYPES[item.type.value], "必填": item.required,
                    "選項": "、".join(o.label for o in item.options), "矩陣列": "、".join(o.label for o in item.rows)} for item in q.questions], hide_index=True, width="stretch")
                st.json({p.id: {"routes": [r.model_dump() for r in p.routes], "default_next": p.default_next,
                    "display_if": {i.id: [c.model_dump() for c in i.display_if] for i in p.questions if i.display_if}} for p in q.pages})
                for warning in q.import_warnings:
                    st.warning(warning)
            if not q.confirmed:
                checked = st.checkbox("所有題目、選項、頁面、必填及跳題已核對", key="wb_confirm_" + q.id + str(q.revision))
                if checked:
                    confirmed = guarded(lambda: confirm_questionnaire(q.model_copy(deep=True), True))
                    # A saved questionnaire is confirmed in the database too, so the
                    # local test form serves exactly the version used for answering.
                    if confirmed and import_mode == "已保存問卷":
                        rt.db.save("questionnaire", confirmed)
                    q = confirmed
    st.subheader("2. 人物設定")
    people, count, conditions, response_ids, ratios = [], 0, PersonaConditions(), [], {"AI 自動混合": 1.}
    topic = st.text_input("人物主題與生活情境", q.topic if q else "一般問卷", key="wb_topic")
    if source == "使用現有人物":
        people = people_selector(rt, "wb_people")
    elif source == "AI 自動建立人物":
        from .personas import ARCHETYPES
        from .ui_conditions import conditions_editor
        count = st.number_input("欲建立的人數", 1, 10000, 10, key="wb_count")
        archetype = st.selectbox("人物類型", ARCHETYPES, index=1, key="wb_archetype")
        ratios = {archetype: 1.}
        if st.checkbox("自訂人物類型分布", key="wb_ratios_enable"):
            frame = st.data_editor(pd.DataFrame({"類型": ARCHETYPES[2:9], "比例": [20., 20., 15., 15., 10., 10., 10.]}), hide_index=True, disabled=["類型"], key="wb_ratios")
            ratios = dict(zip(frame["類型"], frame["比例"]))
        with st.expander("年齡、職業、收入、興趣與自訂分布"):
            controls = conditions_editor("wb_conditions")
        custom = st.text_area("共同背景或自訂特徵", key="wb_custom")
        conditions = None if controls is False else guarded(lambda: PersonaConditions.model_validate({**(controls or {}), "custom_background": custom + "\n" + (controls or {}).get("custom_background", "")}))
        st.caption("人物會逐位保存；同批次檢查最近 100 位人物的相似度，最多重生 2 次，仍相似時保留供人工核對。")
    elif q:
        available = [Response.model_validate_json(r["body"]) for r in rt.db.rows("SELECT body FROM responses WHERE questionnaire_id=? AND status!='error' ORDER BY created_at DESC", (q.id,))]
        if mode == "submit":
            from .validator import submittable
            available = [r for r in available if submittable(r.status, r.issues)]
        mapping = {r.id: r for r in available}
        latest = rt.setting("latest_workbench_job")
        reusable = []
        if mode == "submit" and latest:
            old = rt.db.rows("SELECT checkpoint FROM workbench_jobs WHERE id=?", (latest,))
            for task in json.loads(old[0]["checkpoint"]).get("task_ids", []) if old else []:
                reusable.extend(r["id"] for r in rt.db.rows(
                    "SELECT r.id FROM responses r JOIN task_items i ON i.task_id=r.task_id AND i.persona_id=r.persona_id "
                    "WHERE r.task_id=? AND i.status='skipped' AND i.error LIKE '答案尚需%'", (task,)) if r["id"] in mapping)
        if st.button("帶入上一批未送出的不確定答案", disabled=not reusable, key="wb_reuse_uncertain"):
            st.session_state["wb_responses"] = reusable
        response_ids = st.multiselect("已驗證答案", list(mapping), format_func=lambda i: f"{mapping[i].persona_snapshot.name} · {mapping[i].created_at[:19]} · {mapping[i].status} · {i[:8]}", key="wb_responses")
        st.caption(f"已選 {len(response_ids)} 份回答；此模式沿用已保存答案，不呼叫 AI 重新生成。")
    st.subheader("3. AI 模型與執行設定")
    profiles = rt.db.list("provider")
    active_provider = rt.setting("active_provider")
    profiles.sort(key=lambda p: p.id != active_provider)
    provider = select_entity("使用的 AI 模型", profiles, "wb_provider") or ProviderConfig()
    st.caption(provider.name + " · " + provider.provider + " / " + provider.model)
    seed = st.number_input("Random Seed", 0, 2000000000, 42, key="wb_seed")
    interval, variability, answer_mode, concurrency = 1., .15, "natural", 3
    with st.expander("批次參數"):
        answer_mode = st.selectbox("回答模式", ["natural", "consistent", "custom"], key="wb_answer_mode")
        variability = st.slider("回答變動程度", 0., .5, .15, disabled=answer_mode != "custom", key="wb_variability")
        interval = st.number_input("人物間隔（秒）", 0., 300., 1., key="wb_interval")
        concurrency = st.number_input("同時處理人數", 1, 5, 3, key="wb_concurrency",
            help="同時生成人物、答題及填表的人數。數字越大越快，但較容易觸發 AI 服務的速率限制（429），填表時每人會開一個瀏覽器。")
        st.caption("同時處理會加快整批速度；遇到速率限制時系統會暫停整批，可降低人數後按繼續。")
        tokens = st.number_input("最大輸出 Token", 128, 131072, provider.max_tokens, key="wb_tokens_" + provider.id)
        timeout = st.number_input("API Timeout（秒）", 1., 600., float(provider.timeout), key="wb_timeout_" + provider.id)
        provider = provider.model_copy(update={"max_tokens": tokens, "timeout": timeout})
    target, allowlist, submit_confirmed = (None, [], False)
    if mode in {"dry_run", "submit"}:
        target, allowlist, submit_confirmed = form_settings(rt, q, mode)
    service = WorkbenchService(rt.db, rt.secrets)
    busy = bool(rt.runner.thread and rt.runner.thread.is_alive())
    reasons = start_blockers(busy, mode, source, q, conditions, people, count, response_ids, target, submit_confirmed)
    if reasons:
        st.info("尚不能開始：\n" + "\n".join("- " + reason for reason in reasons))
    if st.button("開始批次處理" if mode != "submit" else "開始批次處理（實際提交）", type="primary", disabled=bool(reasons)):
        def begin():
            if target and target.kind == "local":
                rt.local_form()
            spec = WorkbenchSpec(questionnaire=q, provider=provider, personas=people, generate_count=count,
                conditions=conditions, ratios=ratios, topic=topic, seed=seed, mode=mode, answer_mode=answer_mode,
                variability=variability, interval_seconds=interval, form_target=target, form_allowlist=allowlist,
                response_ids=response_ids, submission_confirmed=submit_confirmed, concurrency=int(concurrency))
            job_id = service.create(spec)
            rt.set_setting("latest_workbench_job", job_id)
            service.start(job_id, rt.runner)
            st.success("批次已啟動，人物、答案及任務進度會保存；可留在本頁查看結果。")
        guarded(begin)
    job_id = rt.setting("latest_workbench_job")
    if job_id and rt.db.rows("SELECT id FROM workbench_jobs WHERE id=?", (job_id,)):
        job_progress(rt, job_id)


def job_controls(rt, job_id):
    service = WorkbenchService(rt.db, rt.secrets)
    status = service.job(job_id)["status"]
    a, b, c, d = st.columns(4)
    if a.button("暫停本批次", disabled=status != "running", key="pause_" + job_id):
        guarded(lambda: service.control(job_id, "paused"))
    if b.button("取消本批次", disabled=status in {"completed", "cancelled"}, key="cancel_" + job_id):
        guarded(lambda: service.control(job_id, "cancelled"))
    if c.button("繼續本批次", disabled=status not in {"paused", "pending"}, key="resume_" + job_id):
        guarded(lambda: service.start(job_id, rt.runner))
    if d.button("重新執行失敗項目", disabled=status not in {"failed", "completed_with_errors"}, key="retry_" + job_id):
        def retry():
            service.retry(job_id)
            service.start(job_id, rt.runner)
        guarded(retry)
    st.caption("暫停及取消在當前請求或頁面完成後生效；已完成工作保留。提交狀態不明的回答必須人工查證，不能盲目重送。"
               "「回答需修正」的項目請到 任務紀錄 → 回答品質 重新生成（原回答保留）。")
    if status in {"paused", "cancelled", "failed", "completed_with_errors"} and st.button("匯出目前已保存結果", key="partial_export_" + job_id):
        guarded(lambda: service.export(job_id))


@st.fragment(run_every="2s")
def job_progress(rt, job_id):
    service = WorkbenchService(rt.db, rt.secrets)
    # Controls live in this auto-refreshing fragment so their enabled state follows the job.
    job_controls(rt, job_id)
    job = service.job(job_id)
    seen = "job_seen_running_" + job_id
    running = job["status"] == "running"
    if seen in st.session_state and st.session_state[seen] != running:
        st.session_state[seen] = running
        st.rerun()  # refresh the page-level start button as well
    st.session_state[seen] = running
    spec = WorkbenchSpec.model_validate_json(job["spec"])
    cp = json.loads(job["checkpoint"])
    items = [i for task in cp.get("task_ids", []) for i in rt.db.rows("SELECT * FROM task_items WHERE task_id=?", (task,))]
    display = items if items else cp.get("generation", [])
    total = spec.generate_count + len(spec.personas) + len(set(spec.response_ids))
    done = sum(i["status"] in {"completed", "skipped"} for i in display)
    failed = sum(i["status"] in {"failed", "invalid"} for i in display)
    unknown = sum(i["status"] == "unknown" for i in display)
    if items:
        failed += sum(i["status"] == "failed" for i in cp.get("generation", []))
    if spec.mode == "personas" and job["status"] in {"completed", "completed_with_errors"}:
        done += len(spec.personas)
    pending = sum(i["status"] == "pending" for i in display)
    for col, (name, value) in zip(st.columns(5), [("任務總數", total), ("已完成 / 略過", done), ("等待中", pending), ("失敗", failed), ("提交待查", unknown)]):
        col.metric(name, value)
    from .ui_operations import STATUSES
    phases = {"prepare": "準備任務", "personas": "生成人物", "answers": "答題與驗證", "forms": "答題與批次填表", "finished": "處理結束"}
    st.progress((done + failed + unknown) / total if total else 0., text=f"{STATUSES.get(job['status'], job['status'])} · {phases.get(job['phase'], job['phase'])} · {done + failed + unknown} / {total}")
    running = {i["persona_id"] for i in items if i["status"] == "running"}
    # Up to five people run at once; read just their names instead of every persona.
    names = [r["name"] for r in rt.db.rows(
        f"SELECT json_extract(body,'$.name') AS name FROM entities WHERE kind='persona' AND id IN ({','.join('?' * len(running))})",
        tuple(running))] if running else []
    current_name = ("、".join(names) if names else cp.get("current_person", "準備中")) if job["status"] == "running" else "本批次已結束或暫停"
    st.caption("目前人物：" + current_name + " · 模型：" + spec.provider.model)
    if job["error"]:
        st.error(job["error"])
    if spec.mode == "submit":
        response_ids = set(spec.response_ids)
        for task in cp.get("task_ids", []):
            response_ids.update(r["id"] for r in rt.db.rows("SELECT id FROM responses WHERE task_id=?", (task,)))
        states = [s["status"] for rid in response_ids for s in rt.db.rows(
            "SELECT status FROM submissions WHERE response_id=? AND created_at>=?", (rid, job["created_at"]))]
        st.info(f"本批次：成功畫面或本地收件 {states.count('success')}、提交狀態待查 {states.count('unknown')}、明確失敗 {states.count('failed')}。外部表單的實際回覆數仍需到表單後台核對。")
    record_table(display)
    for task in [job_id] + cp.get("task_ids", []):
        record_table(rt.db.rows("SELECT level,message,created_at FROM events WHERE task_id=? ORDER BY id DESC LIMIT 8", (task,)), "")
    usage = [u for task in [job_id] + cp.get("task_ids", []) for u in rt.db.rows("SELECT * FROM usage WHERE task_id=?", (task,))]
    st.caption(f"API 請求 {len(usage)} 次 · 已回報輸入 Token {sum(u['input_tokens'] or 0 for u in usage)} · 輸出 Token {sum(u['output_tokens'] or 0 for u in usage)} · 未回報用量 {sum(u['input_tokens'] is None or u['output_tokens'] is None for u in usage)} 次")
    st.caption(f"已知估算費用 {sum(u['cost'] or 0 for u in usage):.6f} {spec.provider.rate_currency} · 費用未回報 {sum(u['cost'] is None for u in usage)} 次；未知費用不能當成免費。")
    folder = rt.db.path.parent / "job-results" / job_id
    if (folder / "simulation.json").exists():
        st.write(json.loads((folder / "simulation.json").read_text(encoding="utf-8")).get("摘要", {}))
        for col, (name, extension) in zip(st.columns(3), [("JSON", "json"), ("CSV ZIP", "zip"), ("Excel", "xlsx")]):
            artifact = folder / ("simulation." + extension)
            if artifact.exists():
                col.download_button("下載模擬 " + name, artifact.read_bytes(),
                    file_name=f"simulation-{job_id}.{extension}", key="job_download_" + job_id + extension)


def history_page(rt):
    from .ui_operations import console_page, automation_page
    from .ui_results import review_page, analysis_page
    from .ui_v2_analysis import quality_page, model_comparison_page, motivation_page, scenario_page
    from .ui_configuration import settings_page
    from .ui_workbench import workbench, wizard
    from .ui_website import website_page
    tools = {"回答檢查": review_page, "回答品質": quality_page, "結果分析": analysis_page,
        "模型比較": model_comparison_page, "動機分析": motivation_page, "情境實驗": scenario_page,
        "系統設定": settings_page, "AI 模擬控制台": console_page, "自動填表測試": automation_page,
        "儀表板": workbench, "快速開始": wizard, "網站體驗模擬": website_page}
    advanced = st.session_state.get("ui_mode") == "進階模式"
    names = [name for name in tools if advanced or name in CORE_TOOLS]
    if st.session_state.get("history_view") not in ["整合批次任務"] + names:
        st.session_state.pop("history_view", None)
    view = st.selectbox("檢視內容", ["整合批次任務"] + names, key="history_view")
    if not advanced:
        st.caption("模擬控制台、快速開始、模型 / 情境實驗、網站體驗等其他工具在側欄「進階模式」中。")
    if view != "整合批次任務":
        st.subheader(view)
        tools[view](rt)
        return
    jobs = rt.db.rows("SELECT id,status,phase,error,created_at FROM workbench_jobs ORDER BY created_at DESC")
    record_table(jobs)
    if jobs:
        mapping = {j["id"]: j for j in jobs}
        job_id = st.selectbox("選擇批次任務", list(mapping), format_func=lambda i: mapping[i]["created_at"][:19] + " · " + mapping[i]["status"] + " · " + i[:8])
        job_progress(rt, job_id)
    else:
        st.info("從問卷工作台設定並開始第一批任務。舊任務、分析與備份仍可從上方檢視內容開啟。")
