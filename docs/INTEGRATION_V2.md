# AI 問卷自動填寫 V2 整合版：操作與驗收

交付日期：2026-10-14。沿用現有 Python、Streamlit、SQLite、AI Provider 與 Playwright，不新增套件。盤點及差異分析見 PROJECT_INVENTORY_V2.md。

## 使用方式

1. 開啟本機 http://127.0.0.1:8501，進入「問卷工作台」。
2. 選擇已保存問卷，或貼上 Google Forms 網址。網址輸入後自動唯讀解析，題目、題型、必填、頁面與跳題可在同頁預覽。公開解析有警告時，須先核對並確認，不默認草稿完整。
3. 選取既有人物，或設定生成人數、年齡、職業、所得、興趣及分布。多選、全選、取消、搜尋、篩選與常用群組可在人物資料庫和工作台操作。
4. 選取 AI 設定檔與批次參數；預設沿用已設定的目前模型。API 金鑰仍從原有工作階段、Windows 認證管理員或環境設定取得。
5. 按一次「開始批次處理」。人物生成、回答、驗證、保存、進度及最終 CSV ZIP / Excel / JSON 報告會依序完成，不需要逐人按下一步。

執行模式：

| 模式 | 行為 |
|---|---|
| 產生、驗證並匯出答案（預設） | 保存 AI 模擬資料，不執行外部填表 |
| 只建立或選取人物 | 保存新人物，或匯出所選人物；不生成問卷答案 |
| 批次填表 Dry Run | 答題、驗證後填表及保存預覽，不點最後提交 |
| 提交到已授權測試表單 | 必須確認表單授權及本次提交；未通過或需人工檢查的答案保存後略過提交 |

選「使用已驗證答案」可多選既有回答並批次 Dry Run / 提交，沿用原回答，不呼叫 AI 重新生成。必填、格式和跳題錯誤會阻擋提交；若只有 AI 自標的「不確定」提醒，已授權測試表單可繼續提交，原答案與提醒仍保留。Google 多頁翻頁會傳送當頁資料，所以 Dry Run 多頁仍須測試授權。

側欄只有「問卷工作台、人物資料庫、問卷管理、任務紀錄、AI 模型設定」。舊版單份填表、回答檢查、品質、分析、實驗、備份和網站體驗保留在「任務紀錄 → 檢視內容」。新工作台不需要先體驗 ONLYFRAME 或其他網站。

## 任務、失敗與恢復

- 工作台設定、生成紀錄、已產生人物與對應 task IDs 保存到 SQLite。重新整理可接續查看進度，已完成工作不會重新生成。
- 暫停及取消在當前 API 請求或頁面完成後生效；已完成資料保留。可以只重新執行失敗項目。
- 答案會在填表前保存。填表失敗後重試沿用已保存答案，不需要再次初始化 AI Client 或重新生成。
- 只對提交前的載入逾時或暫時連線錯誤作有限退避重試。題目對應錯誤、授權錯誤和可能已送達的提交不會盲目重試。
- 成功提交的相同 response ID / URL 不重送；unknown 紀錄保持禁止重送，須在舊版提交工具人工查證接收端後處理。
- 外部表單須填寫實際成功畫面的完整文字；成功畫面代表程式看到確認頁，表單後台回覆數仍須另行核對。已發出最後提交請求卻等不到確認頁記為「提交待查」；沒有發出最後提交請求記為「明確失敗」，並保存點擊後截圖與請求計數。報告的成功數只計本批次，不沿用舊批次的成功紀錄。
- 每批自動產生報告。整批生成失敗時仍產生失敗報告；暫停、取消或其他失敗也可匯出目前已保存結果。
- 回答保留 uncertainty、理由、驗證問題及人物／問卷／模型快照。資料來源明確標示 simulation。

## 資料庫變更與舊資料

Schema 3 → 4 只新增 workbench_jobs，保存批次規格、狀態、階段、checkpoint、錯誤與時間。遷移前備份位於 data/backups/before-v4.sqlite3，遷移採交易處理，可重複執行。

人物群組重用 entities 的 persona_group 類別。TaskSpec 的填表設定、Answer.uncertain 及 Response.dataset_kind 以既有 JSON 保存，缺少新欄位的舊資料採預設值。没有刪除舊資料表或改寫既有回答。

已逐筆核對原本 80 筆 entities、11 筆 tasks、82 筆 responses、1,655 筆 answers、16 筆 submissions、238 筆 usage，內容完整保留。其中包含 32 位人物、5 份問卷與 6 個模型設定。驗收新增的三份資料在獨立測試工作區，不加入原本資料庫。

本機原服務 PID 30348 保持不變，已顯示新版五個入口。更新 cached database / worker 時保留 SecretStore；工作階段金鑰保留行為也有自動化測試。

## 測試結果

| 驗證 | 結果 |
|---|---|
| 原版本基準完整測試 | 247 passed |
| 本次更新單元、整合、遷移、介面與本地瀏覽器測試 | 303 passed；0 failed；64 個 Streamlit / NumPy timedelta 廢棄提醒 |
| 執行時間 | 最新完整測試 226.43 秒 |
| 原服務桌面與 1024×768 平板 | 5 個入口全部可載入，無 JavaScript 錯誤 |
| 真正瀏覽器的一鍵完整流程 | 建立 3 位 Mock 人物、保存 3 份答案、取得 3 筆本地收件及 3 筆 success 提交紀錄 |
| 重新整理真實瀏覽器 | 仍為 1 批任務、3 份答案、3 筆收件，沒有重跑 |
| 完整流程報告下載 | 真正下載 JSON；CSV ZIP、Excel 自動產生 |
| 提交安全 | 已提交略過、不確定狀態禁止重送、未授權及 reference 問卷在 backend 阻擋 |
| 原有功能 | 以五個入口及舊工具入口調整測試；原有 API 協定、人物、題型、其他文字、矩陣、跳題、網站舊任務與匯出測試仍通過 |

證據檔位於專案 outputs：

- v2-workbench-full.xml：完整 JUnit 測試結果。
- v2-integration/browser-acceptance.json：真正的一鍵瀏覽器驗收。
- v2-integration/browser-simulation.json：由介面實際下載的模擬報告。
- v2-integration/one-click-completed.png：完成畫面。
- v2-integration/preservation-and-changes.json：逐筆保留核對及本次修改檔案清單。
- ui-v2/verification.json、01.png–05.png、tablet.png：目前服務的五頁與平板檢查。

這些測試不證明真實 AI 能預測真人。Google 解析涵蓋 metadata、官方 JSON 及 DOM fixtures；這次沒有向外部 Google Forms 提交，也沒有重複呼叫付費 API。真實服務連線、已授權 Google 表單現場提交、多人使用和大量負载仍需另行驗證。

## 修改位置

新增主要程式：

- survey_sim/workbench.py：持久工作台流程、人物生成恢復、接續原批次 worker、報告及匯出。
- survey_sim/ui_pipeline.py：單一設定頁、人物群組與篩選、任務紀錄與進度。

沿用並修改：

- models.py、v2_models.py：加入群組、工作台設定、填表設定與不確定标記。
- migrations.py、storage.py：schema 4、群組讀取、任務設定與填表前保存答案。
- batch.py、automation.py、errors.py：串行批次填表、載入退避、取消及防重送。
- engine.py、validator.py：不確定答案及禁止按預期研究結果选答案的指示；保留獨立驗證器。
- ui.py、ui_operations.py、ui_results.py：五個入口、cache 相容、狀態、回答篩選／比較及單筆重生。
- analysis.py：不確定标記與任務範圍的 JSON 匯出。
- .streamlit/config.toml：poll watcher、儲存後重新載入。
- scripts/verify_ui_browser.py、verify_integrated_workbench.py、package_source.py：目前介面、一鍵驗收與乾淨原始碼封裝。
- tests/test_workbench_pipeline.py、test_workbench_ui.py：整合、故障、安全與介面測試；既有測試同步調整導覽及 schema 版本。

完整逐檔清單見 outputs/v2-integration/preservation-and-changes.json。

## 啟動與重新驗證

Windows 雙擊「啟動系統.bat」，或在專案目錄執行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
.\.venv\Scripts\python.exe -m pytest --basetemp=.tmp/pytest -q
.\.venv\Scripts\python.exe scripts/package_source.py --v2
```

沒有 API Key 可使用 Mock。新電腦先安裝 Python 3.11 以上，啟動程式會安裝 requirements.txt。原始碼 ZIP 不包含金鑰、本機資料庫、虛擬環境、瀏覽器或測試輸出。

## 限制與下一版

批次可設定最多 5 位人物同時處理；網站體驗與預算限制任務固定依序執行，多人負載仍未驗證。驗證器能檢查格式、必填、矩陣、跳題、人設註記及已設定的跨題規則，不能保證所有自然語言語意都正确。公開 Google Forms 解析有格式變動、登入、驗證碼與特殊題型限制，警告須人工核對。

下一版建議先加入單份答案的人工核對與修訂紀錄，並依實際供應商 Rate Limit 驗證並行與多人負載。不要先增加更多獨立頁面。
