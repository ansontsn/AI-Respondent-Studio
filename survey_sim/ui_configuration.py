from __future__ import annotations

import streamlit as st

from .models import ProviderConfig
from .providers import DEFAULT_URLS, make_provider, test_connection
from .ui import guarded, record_table

PROVIDERS = {"mock": "Mock 功能測試", "openai": "OpenAI", "deepseek": "DeepSeek", "gemini": "Google Gemini",
             "anthropic": "Anthropic Claude", "ollama": "Ollama 本地模型", "compatible": "其他 OpenAI 相容 API"}


def providers_page(rt):
    items = rt.db.list("provider")
    labels = {x.id: x.name for x in items}
    chosen = st.selectbox("設定檔", ["new"] + list(labels), format_func=lambda v: "建立新設定檔" if v == "new" else labels[v])
    existing = next((x for x in items if x.id == chosen), None)
    c = existing or ProviderConfig()
    provider = st.selectbox("AI 服務商", list(PROVIDERS), index=list(PROVIDERS).index(c.provider), format_func=PROVIDERS.get)
    with st.form("provider_config"):
        name = st.text_input("設定檔名稱", value=c.name if existing else PROVIDERS[provider])
        api_key = st.text_input("API Key（留白保留現有金鑰）", type="password")
        persistent = st.checkbox("使用 Windows 認證管理員保存金鑰", value=False)
        col1, col2 = st.columns(2)
        base = col1.text_input("API Base URL", value=c.base_url if existing and provider == c.provider else DEFAULT_URLS.get(provider, ""))
        model = col2.text_input("模型名稱（依服務帳戶可用模型填寫）", value=c.model if existing and provider == c.provider else "mock-v1" if provider == "mock" else "")
        col1, col2, col3 = st.columns(3)
        enable_temp = col1.checkbox("送出溫度參數", value=c.temperature is not None)
        temp = col1.number_input("溫度", min_value=0., max_value=2., value=c.temperature or .6, step=.1)
        max_tokens = col2.number_input("最大輸出 Token", min_value=128, max_value=131072, value=c.max_tokens, step=128)
        timeout = col3.number_input("Timeout 秒數", min_value=1., max_value=600., value=c.timeout)
        retries = col2.number_input("重試次數（網路 / 429 / 5xx）", min_value=0, max_value=8, value=c.retries)
        request_interval = col2.number_input("每次 API 請求最短間隔（秒）", min_value=0., max_value=60., value=c.request_interval)
        json_mode = col3.checkbox("要求 JSON 模式（Claude 採提示與本地驗證）", value=c.json_mode)
        token_parameter = st.selectbox("OpenAI / 相容 API Token 參數", ["max_completion_tokens", "max_tokens"], index=0 if c.token_parameter == "max_completion_tokens" else 1)
        st.caption("若模型不支援溫度或 JSON 模式，停用該參數。系統會顯示錯誤，不會假定所有模型格式相同。")
        with st.expander("可靠費率設定（選填，手動依官方資料）"):
            enabled_cost = st.checkbox("啟用成本估算", value=c.input_price_per_million is not None)
            input_price = st.number_input("每百萬輸入 Token 費用", min_value=0., value=c.input_price_per_million or 0.)
            output_price = st.number_input("每百萬輸出 Token 費用", min_value=0., value=c.output_price_per_million or 0.)
            rate_source = st.text_input("費率來源 URL 與查核日期", value=c.rate_source)
            currency = st.text_input("幣別", value=c.rate_currency)
        save = st.form_submit_button("儲存設定", type="primary")
    if save:
        def save_config():
            from .errors import AppError
            from .security import clean_url
            if provider != "mock" and not model.strip():
                raise AppError("請輸入模型名稱。")
            if base:
                clean_url(base, api=True)
            if enabled_cost and not rate_source.strip():
                raise AppError("啟用費用估算需填寫可靠費率來源及日期。")
            updated = ProviderConfig(id=c.id, name=name, provider=provider, base_url=base.strip(), model=model.strip(),
                temperature=temp if enable_temp else None, max_tokens=max_tokens, timeout=timeout, retries=retries, request_interval=request_interval,
                json_mode=json_mode, token_parameter=token_parameter, input_price_per_million=input_price if enabled_cost else None,
                output_price_per_million=output_price if enabled_cost else None, rate_source=rate_source, rate_currency=currency)
            # Save the profile first so a credential-store failure cannot discard it.
            rt.db.save("provider", updated)
            rt.set_setting("active_provider", updated.id)
            if api_key:
                rt.secrets.put(updated.id, api_key, persistent)
            st.success("模型設定已保存。金鑰不會寫入 SQLite 或匯出檔。")
        guarded(save_config)
    if existing:
        st.caption(f"目前金鑰：{'已設定' if rt.secrets.get(existing.id, existing.provider) else '未設定（Mock / 本機無須金鑰）'}")
        a, b, d = st.columns(3)
        if a.button("測試 API 連線"):
            result = guarded(lambda: test_connection(make_provider(existing, rt.secrets.get(existing.id, existing.provider), rt.db)))
            if result:
                st.success("已通過連線及 JSON 回應測試。")
        if b.button("設為目前模型"):
            rt.set_setting("active_provider", existing.id)
            st.success("目前模型已切換。")
        if d.button("清除保存的金鑰"):
            rt.secrets.delete(existing.id)
            st.success("工作階段與認證管理員金鑰已清除（.env 仍依使用者設定）。")
        st.subheader("此設定檔的 API 使用紀錄")
        record_table(rt.db.rows("SELECT operation,input_tokens,output_tokens,cost,currency,status,created_at FROM usage WHERE config_id=? ORDER BY created_at DESC LIMIT 100", (existing.id,)))


def settings_page(rt):
    st.subheader("資料與工作區")
    st.json(rt.db.metadata())
    st.code(str(rt.db.path.resolve()), language=None)
    st.caption("API 金鑰只存在工作階段、Windows 認證管理員或使用者自設 .env。備份不含金鑰。")
    if st.button("建立 SQLite 完整備份"):
        from .models import now
        filename = "backup-" + now().replace(":", "-") + ".sqlite3"
        path = rt.data_dir / "backups" / filename
        guarded(lambda: rt.db.backup(path))
        if path.exists():
            st.download_button("下載資料庫備份", path.read_bytes(), file_name=filename, mime="application/octet-stream")
    st.subheader("匯出完整工作區")
    from .ui_results import export_buttons
    export_buttons(rt)
    st.subheader("系統紀錄")
    logfile = rt.data_dir / "logs" / "debug.log"
    if st.button("查看近期除錯日誌"):
        text = logfile.read_text(encoding="utf-8")[-20000:] if logfile.exists() else "尚無紀錄"
        from .security import redact
        st.code(redact(text), language=None)
