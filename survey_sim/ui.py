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


def friendly_error(exc):
    """Readable Chinese text for the UI; Python / pydantic internals stay in the debug log."""
    import json
    if isinstance(exc, ValidationError):
        from .personas import validation_details
        return "資料格式不符合要求：" + validation_details(exc)
    if isinstance(exc, json.JSONDecodeError):
        return f"JSON 格式錯誤：第 {exc.lineno} 行第 {exc.colno} 個字附近，請檢查括號、引號與逗號。"
    if isinstance(exc, AppError):
        return str(exc)
    text = str(exc)
    # Built-in ValueError messages are English; our own ValueErrors are Chinese.
    if not any("一" <= ch <= "鿿" for ch in text):
        return "輸入值格式不正確，請檢查剛才輸入的數字、清單或 JSON。"
    return text


def guarded(action):
    try:
        return action()
    except (AppError, ValidationError, ValueError) as exc:
        logging.getLogger("survey_sim.ui").exception("UI action failed")
        st.error(redact(friendly_error(exc)))
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
    from .batch import BatchRunner
    from .storage import Database
    if type(rt.db) is not Database or not hasattr(rt.runner, "_fill_response"):
        if rt.runner.thread and rt.runner.thread.is_alive():
            st.warning("現有批次仍在執行；完成或暫停後再載入新版介面。已完成資料會保留。")
            return
        rt.db = Database(rt.db.path)
        rt.runner = BatchRunner(rt.db, rt.secrets)
        if rt.mock_server:
            rt.mock_server.db = rt.db
    from .ui_configuration import providers_page
    from .ui_questionnaires import questionnaires_page
    from .ui_simple_provider import simple_providers
    from .ui_pipeline import workbench_page, people_library, history_page
    pages = {"問卷工作台": workbench_page, "人物資料庫": people_library, "問卷管理": questionnaires_page,
             "任務紀錄": history_page, "AI 模型設定": simple_providers}
    old_section = st.session_state.get("nav")
    if old_section and old_section not in pages:
        st.session_state["nav"] = "人物資料庫" if old_section == "虛擬人物管理" else "任務紀錄"
        if old_section == "虛擬人物管理":
            st.session_state["people_view"] = "建立與編輯"
        else:
            st.session_state["history_view"] = old_section
            from .ui_pipeline import CORE_TOOLS
            if old_section not in CORE_TOOLS:
                st.session_state["ui_mode"] = "進階模式"  # older tools live in advanced mode
    with st.sidebar:
        st.title("◈ 問卷工作台")
        st.caption("AI 問卷模擬平台 · V2")
        section = st.radio("功能導覽", list(pages), label_visibility="collapsed", key="nav")
        mode = st.radio("操作模式", ["簡易模式", "進階模式"], key="ui_mode")
        st.divider()
        st.caption("資料來源：AI 虛擬人物與問卷測試。此工作區與正式研究樣本分開，分析描述模型情境。")
        st.caption("Mock 為規則測試模式，回答品質未代表大型語言模型。")
    st.title(section)
    if mode == "進階模式":
        pages["AI 模型設定"] = providers_page
    guarded(lambda: pages[section](rt))
