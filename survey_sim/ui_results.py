from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from .analysis import display_answer, export_csv_zip, export_excel, export_json, distribution, concentration, similarity_matrix
from .models import QuestionType
from .ui import guarded, record_table


def export_buttons(rt, task_id=None):
    # Generated only on request, then exposed as real downloads.
    key = f"exports_{task_id or 'all'}"
    if st.button("準備 CSV、Excel、JSON 匯出", key=f"export_prepare_{task_id}"):
        result = guarded(lambda: {"CSV ZIP": export_csv_zip(rt.db, task_id), "Excel": export_excel(rt.db, task_id), "JSON": export_json(rt.db, task_id)})
        if result:
            st.session_state[key] = result
    if key in st.session_state:
        cols = st.columns(3)
        for col, (label, data) in zip(cols, st.session_state[key].items()):
            ext, mime = {"CSV ZIP": ("zip", "application/zip"), "Excel": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), "JSON": ("json", "application/json")}[label]
            col.download_button(f"下載 {label}", data, file_name=f"questionnaire-{task_id or 'workspace'}.{ext}", mime=mime, key=f"download_{label}_{key}")
        st.caption("資料集來源、題目 ID 對照、人物、回答理由、驗證及執行紀錄一併匯出。新結果完成後請重新準備匯出。")


def review_page(rt):
    responses = rt.db.responses()
    if not responses:
        st.info("尚無回答。請先執行模擬任務。")
        return
    search = st.text_input("搜尋回答人物、職業或問卷", key="response_search")
    age = st.slider("回答人物年齡範圍", 18, 100, (18, 100), key="response_age")
    responses = [r for r in responses if age[0] <= r.persona_snapshot.background.age <= age[1] and
        search.casefold() in (r.persona_snapshot.name + r.persona_snapshot.background.occupation + r.questionnaire_snapshot.title).casefold()]
    if not responses:
        st.info("沒有符合篩選條件的回答。")
        return
    if st.checkbox("比較多位人物的回答", key="response_compare"):
        mapping = {r.id: r for r in responses}
        chosen = st.multiselect("比較回答", list(mapping), default=list(mapping)[:5],
            format_func=lambda i: mapping[i].persona_snapshot.name + " · " + i[:8])
        rows = []
        for response_id in chosen:
            response = mapping[response_id]
            questions = {q.id: q for q in response.questionnaire_snapshot.questions}
            rows.extend({"問卷": response.questionnaire_snapshot.title, "版本": response.questionnaire_snapshot.revision,
                "題目": questions[a.question_id].title, "人物": response.persona_snapshot.name + " · " + response.id[:8],
                "答案": display_answer(questions[a.question_id], a.value, a.other_text)} for a in response.answers)
        if rows:
            st.dataframe(pd.DataFrame(rows).pivot_table(index=["問卷", "版本", "題目"], columns="人物", values="答案", aggfunc="first"), width="stretch")
    ids = {r.id: r for r in responses}
    selected = st.selectbox("人物回答紀錄", list(ids), format_func=lambda v: f"{ids[v].persona_snapshot.name} · {ids[v].questionnaire_snapshot.title} · {ids[v].status} · {v[:8]}")
    r = ids[selected]
    st.caption(f"回答 ID：{r.id} · 模型：{r.provider_snapshot.provider} / {r.provider_snapshot.model} · 模式：{r.mode}")
    st.write("實際分流路徑：" + " → ".join(r.visited_pages))
    questions = {q.id: q for q in r.questionnaire_snapshot.questions}
    names = {"passed": "通過", "review": "需要人工檢查", "error": "明確錯誤", "skipped": "分流略過"}
    df = pd.DataFrame([{"題目 ID": a.question_id, "題目": questions[a.question_id].title, "答案": display_answer(questions[a.question_id], a.value, a.other_text), "其他補充文字": a.other_text,
                       "決策依據": a.rationale, "驗證": names[a.validation]} for a in r.answers])
    st.dataframe(df, hide_index=True, width="stretch", column_config={"決策依據": st.column_config.TextColumn(width="large")})
    st.caption("決策依據是模型輸出的模擬解釋，可用來檢查人設與情境，並非人類心理的觀察證據。")
    if r.issues:
        st.subheader("待檢查項目")
        record_table([i.model_dump() for i in r.issues])
    else:
        st.success("已檢查格式、有效選項、必填及分流，未發現需標記的問題。")
    if r.repair_history:
        st.subheader("自動修正歷程")
        record_table(r.repair_history)
    if r.website_run:
        with st.expander("實際網站操作與設計保存證據"):
            from .ui_website import show_run
            show_run(r.website_run)
    if r.form_result:
        st.info(r.form_result.get("message", ""))
        artifact = r.form_result.get("artifact")
        if artifact:
            from pathlib import Path
            if Path(artifact).is_file():
                with st.expander("分階段問卷完成畫面"):
                    st.image(artifact)
    with st.expander("人物與問卷快照"):
        st.json(r.persona_snapshot.model_dump())
        st.json(r.questionnaire_snapshot.model_dump(mode="json"))
    if st.button("重新生成此人物答案", key="regenerate_" + r.id):
        def regenerate_one():
            from .quality import regenerate
            task_id = regenerate(rt.db, [r.id])
            rt.runner.start(task_id)
            st.success("已建立單筆重新生成任務，原回答保留；進度可在 AI 模擬控制台查看。")
        guarded(regenerate_one)
    export_buttons(rt, r.task_id)


def analysis_page(rt):
    tasks = rt.db.rows("SELECT id,status,created_at FROM tasks ORDER BY created_at DESC")
    if not tasks:
        st.info("先執行一個模擬任務，便可分析其回答。")
        return
    tmap = {t["id"]: t for t in tasks}
    task_id = st.selectbox("分析任務", list(tmap), format_func=lambda v: f"{tmap[v]['created_at'][:19]} · {v[:8]}")
    responses = rt.db.responses(task_id)
    if not responses:
        st.info("此任務尚無完成回答。")
        return
    st.caption("此分析描述本任務的 AI 情境；題目平均分數及組間差異不能外推真實消費者。多選題以選取次數計算，分流未出現的題目不計入分母。")
    for col, (name, value) in zip(st.columns(3), concentration(responses).items()):
        col.metric(name, f"{value:.1%}" if isinstance(value, float) else value)
    qmap = {q.id: q for q in responses[0].questionnaire_snapshot.questions}
    question_id = st.selectbox("分析題目", list(qmap), index=next((i for i, q in enumerate(qmap.values()) if q.type in {QuestionType.LIKERT, QuestionType.LINEAR}), 0), format_func=lambda id: f"{id} · {qmap[id].title}")
    q = qmap[question_id]
    dist = distribution(responses, question_id)
    if not dist.empty:
        figure = px.bar(dist, x="選項", y="回答次數", color="人物類型", facet_col="列" if q.rows else None,
                        title=q.title + " — 回答分布", barmode="group")
        figure.update_layout(legend_title="人物類型", font_family="Microsoft JhengHei")
        st.plotly_chart(figure, width="stretch")
        st.dataframe(dist, hide_index=True, width="stretch")
    if q.type in {QuestionType.LIKERT, QuestionType.LINEAR}:
        numeric = []
        for r in responses:
            a = next(a for a in r.answers if a.question_id == question_id)
            if a.validation not in {"skipped", "error"} and type(a.value) is int:
                numeric.append({"分數": a.value, "年齡": r.persona_snapshot.background.age, "職業": r.persona_snapshot.background.occupation,
                                "人物類型": r.persona_snapshot.archetype, "預算": r.persona_snapshot.background.disposable_budget})
        if numeric:
            frame = pd.DataFrame(numeric)
            st.metric("有效回答平均量表分數", f"{frame['分數'].mean():.2f}（n={len(frame)}）")
            group = st.selectbox("背景比較欄位", ["人物類型", "職業"])
            grouped = frame.groupby(group)["分數"].agg(["mean", "count"]).reset_index().rename(columns={"mean": "平均分數", "count": "回答數"})
            st.plotly_chart(px.bar(grouped, x=group, y="平均分數", hover_data=["回答數"], title=f"{q.title} — {group}差異"), width="stretch")
            st.plotly_chart(px.scatter(frame, x="預算", y="分數", color="人物類型", hover_data=["年齡", "職業"], title="人物預算與量表回答"), width="stretch")
    a, b = st.columns(2)
    with a:
        st.subheader("邏輯異常與人工檢查")
        issues = pd.DataFrame([{"題目 ID": i.question_id, "等級": i.level, "問題": i.message} for r in responses for i in r.issues])
        if issues.empty:
            st.caption("尚無邏輯異常或待人工檢查的項目。")
        else:
            st.dataframe(issues, hide_index=True, width="stretch")
    with b:
        paths = pd.DataFrame([{"分流路徑": " → ".join(r.visited_pages)} for r in responses]).value_counts().reset_index(name="人數")
        st.plotly_chart(px.bar(paths, x="分流路徑", y="人數", title="問卷分流執行情況"), width="stretch")
    with st.expander("人物相似程度"):
        persons = [r.persona_snapshot for r in responses[:100]]
        st.caption("比較前 100 位完成人物；距離綜合人格、年齡及職業，0–1 越高越相似。此量尺為工程檢查，未經心理計量驗證。")
        st.plotly_chart(px.imshow(similarity_matrix(persons), x=[p.name for p in persons], y=[p.name for p in persons],
                                 zmin=0, zmax=1, title="人物相似程度", labels={"color": "相似度"}), width="stretch")
    export_buttons(rt, task_id)
