from __future__ import annotations

import logging

import streamlit as st
from pydantic import ValidationError

from .errors import AppError
from .runtime import Runtime
from .security import redact


@st.cache_resource
def runtime():
    return Runtime()


def guarded(action):
    try:
        return action()
    except (AppError, ValidationError, ValueError) as exc:
        logging.getLogger("survey_sim.ui").exception("UI action failed")
        st.error(redact(str(exc)))
    except Exception:
        logging.getLogger("survey_sim.ui").exception("Unexpected UI failure")
        st.error("操作未完成，請檢查設定；詳細原因已保存到除錯日誌。")
    return None


def select_entity(label, items, key=None):
    if not items:
        st.info(f"目前沒有可選的{label}。")
        return None
    by_id = {x.id: x for x in items}
    selected = st.selectbox(label, list(by_id), format_func=lambda id: getattr(by_id[id], "name", getattr(by_id[id], "title", id)), key=key)
    return by_id[selected]


def record_table(rows, empty_message="尚無紀錄。"):
    import pandas as pd
    if not rows:
        st.caption(empty_message)
        return
    from .ui_operations import STATUSES
    df = pd.DataFrame(rows)
    if "status" in df:
        df["status"] = df["status"].map(lambda v: STATUSES.get(v, v))
    names = {"id": "紀錄 ID", "status": "狀態", "created_at": "時間（UTC）", "updated_at": "更新時間（UTC）",
             "provider": "服務商", "model": "模型", "operation": "操作", "input_tokens": "輸入 Token", "output_tokens": "輸出 Token",
             "cost": "估算費用", "currency": "幣別", "url": "網址", "dry_run": "僅預覽", "message": "結果說明",
             "question_id": "題目 ID", "level": "等級", "code": "問題代碼", "resolution": "處理方式", "attempt": "嘗試次數",
             "page_id": "頁面 ID", "issue": "問題", "response_id": "回答 ID"}
    st.dataframe(df.rename(columns=names), hide_index=True, width="stretch")


def main():
    st.set_page_config(page_title="AI 問卷自動填寫", page_icon="◈", layout="wide", initial_sidebar_state="expanded")
    st.markdown('''<style>
    .stApp{background:#f6f8fc}section[data-testid="stSidebar"]{background:#eef2fa;border-right:1px solid #e0e6f2}
    [data-testid="stMetric"]{background:white;border:1px solid #e1e7f1;border-radius:12px;padding:18px}
    h1,h2,h3{color:#1d2a48}div.stButton>button[kind="primary"]{background:#3159d9;border-color:#3159d9}
    .block-container{padding-top:2rem;padding-bottom:3rem;max-width:1500px}
    </style>''', unsafe_allow_html=True)
    rt = runtime()
    with st.sidebar:
        st.title("◈ 問卷工作台")
        st.caption("AI問卷自動填寫 · v1.0")
        section = st.radio("功能導覽", ["儀表板", "AI 模型設定", "問卷管理", "虛擬人物管理", "AI 模擬控制台", "回答檢查", "自動填表測試", "結果分析", "系統設定"], label_visibility="collapsed", key="nav")
        st.divider()
        st.caption("資料來源：AI 虛擬人物與問卷測試。此工作區與正式研究樣本分開，分析描述模型情境。")
        st.caption("Mock 為規則測試模式，回答品質未代表大型語言模型。")
    st.title(section)
    from .ui_configuration import dashboard, providers_page, settings_page
    from .ui_questionnaires import questionnaires_page
    from .ui_people import people_page
    from .ui_operations import console_page, automation_page
    from .ui_results import review_page, analysis_page
    pages = {"儀表板": dashboard, "AI 模型設定": providers_page, "問卷管理": questionnaires_page,
             "虛擬人物管理": people_page, "AI 模擬控制台": console_page, "回答檢查": review_page,
             "自動填表測試": automation_page, "結果分析": analysis_page, "系統設定": settings_page}
    guarded(lambda: pages[section](rt))
