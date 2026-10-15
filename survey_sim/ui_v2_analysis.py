import json

import pandas as pd
import plotly.express as px
import streamlit as st

from .costs import task_estimate, usage_summary
from .experiments import ExperimentService
from .models import TaskSpec, Scenario
from .motivations import motivation_report
from .providers import make_provider
from .quality import quality_report, regenerate
from .reports import report_exports
from .ui import guarded, select_entity, record_table
from .v2_models import Experiment, ExperimentCell


def download_report(report, key):
    cache = "report_" + key
    if st.button("準備分析報告下載", key="prepare_" + key):
        data = guarded(lambda: report_exports(report))
        if data:
            st.session_state[cache] = data
    if cache in st.session_state:
        for col, (name, data) in zip(st.columns(3), st.session_state[cache].items()):
            ext = {"JSON": "json", "CSV ZIP": "zip", "Excel": "xlsx"}[name]
            col.download_button(name, data, file_name=f"{key}.{ext}", key="download_" + key + name)


def choose_task(rt, key):
    tasks = rt.db.rows("SELECT id,status,created_at FROM tasks ORDER BY created_at DESC")
    if not tasks:
        st.info("先完成一個模擬任務，即可查看品質與分析。")
        return None
    mapping = {t["id"]: t for t in tasks}
    return st.selectbox("模擬任務", list(mapping), format_func=lambda id: f"{mapping[id]['created_at'][:19]} · {id[:8]}", key=key)


def quality_page(rt):
    st.caption("品質檢查結合格式、分流、既定人物及跨題規則；重複答案會提醒人工核對，並不要求所有人刻意選不同答案。")
    id = choose_task(rt, "quality_task")
    if not id:
        return
    report = quality_report(rt.db, id)
    for col, (label, value) in zip(st.columns(4), list(report["summary"].items())[:4]):
        col.metric(label, value)
    st.dataframe(pd.DataFrame(report["responses"]), hide_index=True, width="stretch")
    if report["findings"]:
        frame = pd.DataFrame(report["findings"])
        level = st.selectbox("異常等級", ["全部", "error", "review"], format_func=lambda x: {"全部": "全部", "error": "明確錯誤", "review": "人工檢查"}[x])
        st.dataframe(frame if level == "全部" else frame[frame["等級"] == level], hide_index=True, width="stretch")
        counts = frame.groupby(["代碼", "等級"]).size().reset_index(name="紀錄數")
        st.plotly_chart(px.bar(counts, x="代碼", y="紀錄數", color="等級", title="品質檢查異常紀錄"), width="stretch")
    else:
        st.success("目前未發現已設定規則下的異常。")
    if report["execution_failures"]:
        st.warning("有未完成或失敗人物，這些不會被當作有效回答。")
        record_table(report["execution_failures"])
    responses = rt.db.responses(id)
    labels = {r.id: r.persona_snapshot.name for r in responses}
    flagged = {f["response_id"] for f in report["findings"]}
    chosen = st.multiselect("選擇要重新生成的回答", list(labels), default=[r for r in labels if r in flagged], format_func=labels.get)
    seed = st.number_input("重新生成種子", min_value=0, max_value=2_000_000_000, value=43)
    if st.button("建立重新生成任務", type="primary", disabled=not chosen):
        task = guarded(lambda: regenerate(rt.db, chosen, seed))
        if task:
            st.session_state["quality_regeneration"] = task
            if guarded(lambda: rt.runner.start(task) or True):
                st.success("已保留原回答，使用原人物、問卷及模型快照重新執行。")
            else:
                st.info("重新生成任務已建立；目前批次結束後，可在 AI 模擬控制台按「開始 / 繼續」。")
    if st.session_state.get("quality_regeneration"):
        from .ui_operations import progress_view
        progress_view(rt, st.session_state["quality_regeneration"])
    download_report(report, "quality-" + id)


def experiment_inputs(rt, key):
    q = select_entity("實驗問卷", rt.db.list("questionnaire"), key + "_q")
    if q and not q.confirmed:
        st.warning("此問卷尚未確認，不能建立實驗。")
    people = rt.db.list("persona")
    mapping = {p.id: p for p in people}
    ids = st.multiselect("固定使用相同人物", list(mapping), default=list(mapping)[:10], format_func=lambda id: mapping[id].name, key=key + "_people")
    seed = st.number_input("實驗種子", min_value=0, max_value=2_000_000_000, value=42, key=key + "_seed")
    mode = st.selectbox("回答模式", ["consistent", "natural", "custom"], format_func=lambda v: {"consistent": "高一致性", "natural": "自然變動", "custom": "自訂"}[v], key=key + "_mode")
    variability = st.slider("自訂變動程度", 0., .5, .15, key=key + "_variability", disabled=mode != "custom")
    interval = st.number_input("人物間隔秒數", min_value=0., max_value=300., value=1., key=key + "_interval")
    budget = None
    if st.checkbox("設定每組任務的預算上限", key=key + "_has_budget"):
        budget = st.number_input("每組費用上限（各模型設定的幣別）", min_value=0., value=10., key=key + "_budget")
        st.caption("費率需在模型進階設定填寫；未知費用或預算不足會暫停，不代表服務商帳戶硬上限。")
    return q, [mapping[id] for id in ids], seed, mode, variability, interval, budget


@st.fragment(run_every="2s")
def experiment_status(rt, exp):
    from .ui_operations import STATUSES
    summary = ExperimentService(rt.db).summary(exp)
    frame = pd.DataFrame(summary)
    frame["狀態"] = frame["狀態"].map(lambda v: STATUSES.get(v, v))
    display = frame.copy()
    for column in ["完成率", "需邏輯人工檢查比例", "格式錯誤率"]:
        display[column] = display[column].map(lambda v: "尚無資料" if pd.isna(v) else f"{v:.1%}")
    quality_tab, usage_tab, cost_tab = st.tabs(["完成與品質", "耗時與 Token", "費用與模型設定"])
    with quality_tab:
        st.dataframe(display[["組別","狀態","預定人物","保存回答","完成率","失敗人物","格式錯誤率","需邏輯人工檢查比例"]], hide_index=True, width="stretch")
    with usage_tab:
        st.dataframe(display[["組別","平均人物耗時秒","耗時有紀錄的人物","API請求","輸入Token","輸出Token","未知Token請求"]], hide_index=True, width="stretch")
    with cost_tab:
        st.dataframe(display[["組別","服務商","模型","幣別","已知估算費用","未知費用請求"]], hide_index=True, width="stretch")
    if not frame.empty:
        st.plotly_chart(px.bar(frame, x="組別", y="完成率", title="各組模擬完成率", range_y=[0,1]), width="stretch")


def view_experiment(rt, exp):
    service = ExperimentService(rt.db)
    ids = [c.task_id for c in exp.cells]
    a, b, c, d = st.columns(4)
    unfinished = any(rt.db.task(id)["status"] not in {"completed", "completed_with_errors", "cancelled"} for id in ids)
    if a.button("執行 / 繼續實驗", type="primary", disabled=not unfinished):
        guarded(lambda: rt.runner.start_group(ids))
    if b.button("暫停目前任務"):
        if rt.runner.active_id in ids:
            rt.runner.pause(rt.runner.active_id)
    if c.button("取消未完成項目"):
        rt.runner.cancel_group(ids)
        st.success("已取消未完成項目，已完成資料保留。")
    if d.button("重新排入失敗人物"):
        def retry():
            for id in ids:
                if rt.db.rows("SELECT 1 FROM task_items WHERE task_id=? AND status='failed'", (id,)):
                    rt.db.retry_failed(id)
            st.success("失敗人物已重新排入；按執行 / 繼續。")
        guarded(retry)
    experiment_status(rt, exp)
    with st.expander("預算及即時用量"):
        selected = st.selectbox("任務組別", ids, format_func=lambda id: next(c.label for c in exp.cells if c.task_id == id))
        budget_controls(rt, selected)
    rows = service.answer_rows(exp)
    if rows:
        frame = pd.DataFrame(rows)
        qmap = {q.id: q for q in exp.questionnaire.questions}
        question_id = st.selectbox("比較題目", list(qmap), index=next((i for i,q in enumerate(qmap.values()) if q.trait == "purchase_intention"), 0), format_func=lambda id: qmap[id].title)
        subset = frame[(frame["question_id"] == question_id) & ~frame["驗證"].isin(["skipped","error"])]
        counts = subset.groupby(["組別","答案文字"]).size().reset_index(name="回答數")
        if not counts.empty:
            st.plotly_chart(px.bar(counts, x="答案文字", y="回答數", color="組別", barmode="group", title="各組答案分布"), width="stretch")
        numeric = subset[subset["答案"].map(lambda v: type(v) in {int,float})]
        if not numeric.empty:
            st.plotly_chart(px.box(numeric, x="組別", y="答案", points="all", hover_data=["人物"], title="同人物在各組的量表回答"), width="stretch")
            means = numeric.groupby("組別")["答案"].agg(["mean","count"]).reset_index().rename(columns={"mean":"平均分數","count":"有效回答數"})
            st.dataframe(means, hide_index=True, width="stretch")
        st.dataframe(subset[["組別","人物","答案文字","決策依據","驗證"]], hide_index=True, width="stretch")
        differences = service.differences(exp)
        if differences:
            st.subheader("同人物配對差異")
            diff = pd.DataFrame(differences)
            st.dataframe(diff[diff["question_id"] == question_id], hide_index=True, width="stretch")
    with st.expander("完整實驗設定與人物快照"):
        st.json(exp.model_dump(mode="json"))
    download_report(service.report(exp), "experiment-" + exp.id)


def model_comparison_page(rt):
    st.caption("以相同人物、問卷及種子比較不同模型設定。完成率、格式錯誤及一致性不等於對真人的預測準確率。")
    create_tab, history_tab = st.tabs(["建立模型實驗", "查看比較結果"])
    with create_tab:
        name = st.text_input("實驗名稱", "多模型比較")
        q, people, seed, mode, variability, interval, budget = experiment_inputs(rt, "model_exp")
        profiles = {c.id: c for c in rt.db.list("provider")}
        selected = st.multiselect("比較模型設定檔（至少兩個）", list(profiles), format_func=lambda id: profiles[id].name + " / " + profiles[id].model)
        cells = [ExperimentCell(label=f"{profiles[id].name} · {id[:6]}", provider=profiles[id]) for id in selected]
        if q and people and cells:
            st.dataframe(pd.DataFrame([{"組別": cell.label, **task_estimate(TaskSpec(questionnaire=q, personas=people, provider=cell.provider))} for cell in cells]), hide_index=True, width="stretch")
        if st.button("保存模型比較實驗", type="primary", disabled=not q or not q.confirmed or not people or len(cells) < 2):
            exp = guarded(lambda: ExperimentService(rt.db).create(Experiment(name=name, kind="model", questionnaire=q, personas=people, cells=cells, seed=seed, mode=mode), interval, budget, variability))
            if exp:
                st.success("實驗與所有任務已保存。到查看比較結果按執行。")
    with history_tab:
        exp = select_entity("模型實驗", [x for x in rt.db.list("experiment") if x.kind == "model"])
        if exp:
            view_experiment(rt, exp)


def scenario_page(rt):
    st.caption("相同人設在不同產品 / 服務情境下回答；資料是模型建構情境，不代表市場需求或因果效果。")
    create_tab, history_tab = st.tabs(["建立情境實驗", "查看情境結果"])
    with create_tab:
        name = st.text_input("實驗名稱", "產品自由度情境比較")
        q, people, seed, mode, variability, interval, budget = experiment_inputs(rt, "scenario_exp")
        provider = select_entity("固定 AI 模型", rt.db.list("provider"), "scenario_provider")
        table = st.data_editor(pd.DataFrame({"名稱": ["A 基本款","B 部分客製化","C 高度客製化"],
            "情境敘述": ["選擇固定樣式，符合基本需求。","可調整部分樣式及外觀。","可自由組合設計及個人風格。"],
            "價格": [200.,500.,1000.], "客製化程度": [0.,.5,1.]}), hide_index=True, num_rows="dynamic", key="scenario_table")
        st.caption("價格與人物預算使用相同單位；客製化程度 0–1。一般服務情境可自行修改名稱與敘述。")
        if st.button("保存情境實驗", type="primary", disabled=not q or not q.confirmed or not people or not provider or len(table) < 2):
            def create():
                from .errors import AppError
                if any(table["價格"] < 0) or any((table["客製化程度"] < 0) | (table["客製化程度"] > 1)):
                    raise AppError("情境價格不可負數，客製化程度需 0–1。")
                cells = [ExperimentCell(label=row["名稱"], provider=provider, scenario=Scenario(name=row["名稱"], description=row["情境敘述"], attributes={"price": float(row["價格"]), "customization": float(row["客製化程度"])})) for _, row in table.iterrows()]
                return ExperimentService(rt.db).create(Experiment(name=name, kind="scenario", questionnaire=q, personas=people, cells=cells, seed=seed, mode=mode), interval, budget, variability)
            exp = guarded(create)
            if exp:
                st.success("情境、固定人物及全部任務已保存。到查看情境結果按執行。")
    with history_tab:
        exp = select_entity("情境實驗", [x for x in rt.db.list("experiment") if x.kind == "scenario"])
        if exp:
            view_experiment(rt, exp)


def motivation_page(rt):
    st.caption("分類與比較 AI 生成的回答理由及文字。結果代表模型情境，不能當作真實受訪者的心理證據。")
    id = choose_task(rt, "motivation_task")
    if not id:
        return
    spec = TaskSpec.model_validate_json(rt.db.task(id)["spec"])
    qmap = {q.id: q for q in spec.questionnaire.questions if q.type.value in {"likert","linear_scale"}}
    target = st.selectbox("購買意願量表（沒有則選未指定）", [None] + list(qmap),
        index=next((i+1 for i,q in enumerate(qmap.values()) if q.trait == "purchase_intention"), 0), format_func=lambda q: "未指定" if q is None else qmap[q].title)
    mode = st.selectbox("分類方式", ["規則分類", "AI 輔助分類"])
    config = select_entity("分類模型", rt.db.list("provider"), "motivation_provider") if mode == "AI 輔助分類" else None
    if st.button("分析回答動機", type="primary"):
        from .models import uid
        analysis_id = "analysis-" + uid()
        report = guarded(lambda: motivation_report(rt.db, id, target, make_provider(config, rt.secrets.get(config.id, config.provider), rt.db, analysis_id) if config else None))
        if report:
            report["analysis_usage_id"] = analysis_id
            report["analysis_usage"] = usage_summary(rt.db, analysis_id)
            rt.set_setting("motivation_report_" + id, report)
            st.session_state["motivation_report"] = report
    report = st.session_state.get("motivation_report")
    if not report or report["task_id"] != id:
        report = rt.setting("motivation_report_" + id)
    if not report or report["task_id"] != id:
        return
    st.write(report["summary"])
    st.caption(report["method"] + "；多標籤片段次數與人物數分開呈現。")
    if report["themes"]:
        st.plotly_chart(px.bar(pd.DataFrame(report["themes"]), x="主題", y="理由片段數", hover_data=["人物數"], title="模擬理由的動機主題"), width="stretch")
        st.plotly_chart(px.bar(pd.DataFrame(report["by_persona_type"]), x="主題", y="每人平均片段數", color="人物類型", hover_data=["群體人物數","提及人物數"], barmode="group", title="不同人設的理由主題"), width="stretch")
        st.plotly_chart(px.bar(pd.DataFrame(report["by_intention"]), x="主題", y="每人平均片段數", color="購買意願群", hover_data=["群體人物數","提及人物數"], barmode="group", title="不同購買意願群體的理由"), width="stretch")
        st.caption("組間圖表按人物數換算平均片段數；分流造成的題目曝光差異仍需核對。")
    st.subheader("低意願群體明確提及的拒絕考量")
    if report.get("refusal_summary"):
        st.plotly_chart(px.bar(pd.DataFrame(report["refusal_summary"]), x="拒絕考量", y="人物數", title="低意願群體的明確拒絕訊號"), width="stretch")
    record_table(report["refusal_reasons"], "目前原文沒有明確拒絕訊號；不以低分推定理由。")
    with st.expander("逐段文字與分類，可核對原文"):
        st.dataframe(pd.DataFrame(report["segments"]).astype(str), hide_index=True, width="stretch")
    download_report(report, "motivations-" + id)


@st.fragment(run_every="2s")
def live_usage(rt, task_id):
    summary = usage_summary(rt.db, task_id)
    st.json({"已回報輸入Token": summary["input_tokens"], "已回報輸出Token": summary["output_tokens"],
             "已知估算費用": summary["known_cost"], "未知費用請求": summary["unknown_cost_requests"], "未知Token請求": summary["unknown_token_requests"]})


def budget_controls(rt, task_id):
    live_usage(rt, task_id)
    spec = TaskSpec.model_validate_json(rt.db.task(task_id)["spec"])
    enabled = st.checkbox("此任務啟用預算上限", value=spec.budget_limit is not None, key="budget_enabled_" + task_id)
    limit = st.number_input("任務上限（" + spec.provider.rate_currency + "）", min_value=0., value=float(spec.budget_limit if spec.budget_limit is not None else 10.), key="budget_limit_" + task_id)
    if st.button("保存任務預算調整", key="budget_save_" + task_id):
        if guarded(lambda: rt.db.update_budget(task_id, limit if enabled else None) or True):
            st.success("調整已保存並記錄事件；預算暫停時可按繼續。")
    st.caption("檢查在每次請求之前執行。服務端未知費用或截斷計數可能影響實際帳單，請搭配服務商硬額度。")
