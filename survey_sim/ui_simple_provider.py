import streamlit as st

from .errors import AppError
from .models import ProviderConfig
from .providers import make_provider, test_connection
from .ui import guarded
from .ui_configuration import PROVIDERS


def simple_providers(rt):
    profiles = rt.db.list("provider")
    mapping = {p.id: p for p in profiles}
    selected = st.selectbox("設定檔", ["new"] + list(mapping), format_func=lambda id: "新增設定檔" if id == "new" else mapping[id].name)
    existing = mapping.get(selected)
    c = existing or ProviderConfig()
    provider = st.selectbox("AI 服務商", list(PROVIDERS), index=list(PROVIDERS).index(c.provider), format_func=PROVIDERS.get)
    with st.form("simple_provider"):
        name = st.text_input("設定檔名稱", c.name if existing else PROVIDERS[provider])
        model = st.text_input("模型名稱", c.model if existing else "mock-v1" if provider == "mock" else "")
        key = st.text_input("API Key（留白保留現有）", type="password")
        persistent = st.checkbox("使用 Windows 認證管理員保存")
        base = st.text_input("相容 API Base URL", c.base_url) if provider in {"compatible", "ollama"} else c.base_url if provider == c.provider else ""
        if st.form_submit_button("儲存模型設定", type="primary"):
            def save():
                if not model.strip():
                    raise AppError("請輸入模型名稱。")
                config = ProviderConfig.model_validate({**c.model_dump(), "name": name, "provider": provider, "model": model, "base_url": base})
                rt.db.save("provider", config)
                rt.set_setting("active_provider", config.id)
                if key:
                    rt.secrets.put(config.id, key, persistent)
                st.success("設定已保存。進階模式可調整溫度、Token、逾時及費率。")
            guarded(save)
    if existing and st.button("測試連線與 JSON 輸出"):
        result = guarded(lambda: test_connection(make_provider(existing, rt.secrets.get(existing.id, existing.provider), rt.db)))
        if result:
            st.success("連線與 JSON 測試通過。")
    st.info("需要溫度、Token、重試、成本或完整金鑰管理時，切換側欄的進階模式。")
