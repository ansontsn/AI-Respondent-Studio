# V2 本機驗收與交付紀錄

## 最新：使用者提交錯誤修正（2026-10-14）

最終全套 **134 passed、21 項上游警告、82.51 秒**，報告 `outputs/website-submit-fix-full-pytest-results.xml`。新增測試核對接收位置缺漏在點擊前停止、HTTP 201／204 空本文與實際請求資料、字母數字編號、API 403、不確定提交不得解鎖、解除只清除匹配的非執行中 checkpoint。Chrome 本地畫面驗證更正後狀態與說明通過，證據 `outputs/submission-fix-ui/`。

截圖那筆吳秉喬 CUSTOM 與一筆江柏喬 BASIC 的流程接收 URL 空白、設定保存時間早於操作且未更動，原策略禁止全部遠端寫入且各有攔截紀錄。备份後保留原始紀錄，更正為 blocked／新增未送出，只解除這兩筆的防重複鎖並補入唯讀核對到的網站接收 URL；修正没有重送。證據 `outputs/website-submit-fix-audit.json`。

後續使用者本人新一筆鄭庭言 CUSTOM 原新增 POST 已取得 **HTTP 201**，但網站改用字母數字尾碼 `DES-20261013-D386853890A7`，舊純數字匹配誤標 unknown。已相容兩種尾碼，以原實際請求與成功回應更正為 server_confirmed／insert_http_ack，保留防重複鎖、無新增雲端寫入；證據 `outputs/website-alphanumeric-receipt-fix.json`。以公開前端身分單筆唯讀核查回應 HTTP 401，沒有宣稱讀回資料成功、不使用私人或管理員金鑰。這是一筆既有使用者請求的 API 成功確認，不表示全部三方案已驗證雲端。

修改 models、website_experience、ui_website、ui_operations、提交測試、來源包脚本、.gitignore、README、操作／路線文件；舊資料及ONLYFRAME網站不改寫。錯誤訊息由通用逾時改為設定缺漏、阻擋原因或 API 狀態；真實未確認回應仍維持 unknown，不自動重送。GitHub 未更新。

## 最新增量：生成姓名與三方案（2026-10-14）

最新完整回歸 **127 passed、21 項上游警告、93.70 秒**，證據 `outputs/website-tiers-full-pytest-results.xml`。相關測試 **26 passed、1 項警告、40.45 秒**，證據 `outputs/website-tiers-pytest-results.xml`。Chrome 15 個管理頁面及桌面／平板畫面通過，無 JavaScript 錯誤。

- 人物生成即有穩定中文姓名，50 人重現及 10,000 個可用姓名不重複測試通過；真實模型生成提示要求姓名，但未用真實 API 驗證。姓名依 ID 本機生成不增加 API 請求，同批處理重複，UI 重跑保留使用者已修改姓名。
- 三方案實際操作不同：BASIC 框色；CUSTOM 框色與文字；PREMIUM 再加背景與貼飾。處理 BASIC 特定的正常確認視窗，不修改 ONLYFRAME 網站或私有 React 狀態。
- 實際公開網站三人預覽與各 8 題 Mock 通過：吳秉喬 BASIC 3.515 秒、江柏喬 CUSTOM 4.078 秒、鄭庭言 PREMIUM 4.468 秒。付費模型請求及遠端設計 POST 均為 0；已匯入本平台三位人物與三份預覽回答，原資料仍保留，備份 `backups/before-three-tiers.sqlite3`。
- 按人數與 Seed 分配三方案，UI 預覽姓名／ID／方案、合計人數檢查、任務快照、事實题校正與品質重新生成沿用原方案通過。姓名提交預設沿用人物姓名，BASIC／CUSTOM／PREMIUM 的本機 HTTP 實際 Chrome 提交均通過。
- **網站已變動**：2026-10-14 公開腳本讀到 Supabase 設定，與前一天本機備援版本不同。本輪提交仍禁止遠端寫入，因此三次被攔截，紀錄為 unknown／failed，不當成提交成功，也不重試。實際雲端接收仍未驗證。提供唯讀接收網址偵測，不保存／輸出 Key；腳本發現雲端設定時停止本機提交驗證。

新增 `persona_names.py`、`verify_three_tiers.py`、`test_persona_names_tiers.py`，擴充 models、personas、conditional_personas、website_experience、batch、storage、quality、ui_people、ui_website 及本機網站測試，更新 README、WEBSITE_WORKFLOW、路線圖與來源包腳本。新增欄位有預設值，舊 CUSTOM 模型／防重複提交鍵保留相容，資料库不重建。`.gitignore` 排除資料庫、備份及完整設計紀錄。

尚未實際驗證：真實 AI API 名稱與回答／Token／費用、實際 Supabase 設計接收、正式 Google 問卷提交。真實預覽成功與本機提交成功均不能宣稱真實消费者心理或雲端研究端已收到。證據 `outputs/website-three-tiers/live-preview.json`、`live-submit.json` 及截圖；本機已更新，GitHub 未 commit／push。

## 後續：網站操作重播與設計提交（2026-10-13）

最新回歸：**115 passed、20 項上游警告、73.33 秒**，報告 `outputs/website-full-pytest-results.xml`。新功能相關 **14 passed、26.37 秒**，報告 `outputs/website-pytest-results.xml`。既有 101 項與新增 14 項均通過；真實 Chrome 管理頁面驗證由 14 頁增加為 **15 頁**，含網站體驗頁、桌面／平板截圖，無 JavaScript 錯誤，證據 `outputs/ui-v2/verification.json`。

| 驗收 | 結果 |
|---|---|
| 真實 ONLYFRAME CUSTOM 重播 | 完成，3.640 秒，原有 UI 的框色、文字、字體、位置與最終預覽有截圖 |
| 真實網站設計提交 | 點擊原網站確認送出，11.203 秒，取得 DES-20261013-6440，核對相符的瀏覽器本機紀錄並備份完整設計 |
| 雲端接收區分 | 實際公開網站走本機備援；雲端沒有實測。接收 API 的回傳紀錄匹配只在本機 HTTP 測試驗證 |
| 提交結果不明與重複防護 | 通過；成功畫面但無相符紀錄判為 unknown，相同人物同設計跨資料庫重新開啟仍禁止自動重送 |
| Dry Run 與非預期寫入 | 通過；預覽不提交，攔截未允許 POST；服務工作者停用 |
| 網頁改變與中斷 | 通過；找不到控制項會保存失敗；暫停在提交前停止，已完成步驟保存 |
| 網站 → 答題 → 驗證 → 匯出 | 真實預覽及本機保存紀錄各接 8 題 Mock，均通過；單頁 1 次 Mock 呼叫，外部 AI API 0 次 |
| API 失敗後恢復 | 通過；網站 checkpoint 保留，重試不重跑已完成瀏覽器流程；品質重新生成重用提交紀錄 |
| 事實題與主觀題 | 內建測試問卷的方案／功能／保存狀態／編號按實際紀錄校正並保存歷程；滿意、購買意願仍為人物推估 |
| 原資料與來源 | 備份 before-website-mode.sqlite3；匯入兩筆網站證據前後人物、回答、任務數量不變，仍是獨立 AI 測試工作區 |

新增檔案：`survey_sim/website_experience.py`、`survey_sim/ui_website.py`、`scripts/verify_website_workflow.py`、`tests/test_website_experience.py`、`docs/WEBSITE_WORKFLOW.md`。整合修改：models、storage、batch、engine、quality、analysis、ui、ui_results，另更新 GUI 驗證腳本、來源包腳本、V2 UI 測試、README 及路線圖。模型增加帶預設值的可選欄位，沿用 schema 2 的通用實體表，不做破壞性遷移。

實際證據：`outputs/website-mode/live-preview.json`、`live-local-submit.json`、`runs/`；平台已匯入兩筆網站紀錄及預設不提交的重播設定，可從網站體驗頁查看。完整已保存設計與測試資料庫不打包為公開原始碼。原逐步助手試跑及其 Token 計數保留，與本次可重跑流程分開。

**尚未實際驗證**：真實 AI 模型回答／Token／費用、ONLYFRAME 雲端保存、BASIC／PREMIUM、正式 Google 問卷填答／提交。沒有修改 ONLYFRAME 原始碼或更新 GitHub。感受題是模擬推估，不是實際人類體驗或研究樣本；本機設計成功不可當成研究端收件證據。操作教學見 `WEBSITE_WORKFLOW.md`。

日期：2026-10-13；版本：2.0.0；Windows / Python 3.12.14。專案沿用原目錄與架構，未修改其他專案或 ONLYFRAME 網站。依使用者要求，V2 尚未 commit / push / 更新 GitHub。

## 實際測試結果

| 驗證 | 結果 | 證據 |
|---|---|---|
| 修改前 V1 回歸 | 61 passed，37.66 秒 | 本次升級前實際執行；原 V1 驗收另保留於 ACCEPTANCE.md |
| V2 初次交付全套 pytest | **96 passed，45.09 秒**；原 61 項 + V2 35 項；零失敗 | outputs/v2-pytest-results.xml |
| HTTPS 修正後全套 pytest | **101 passed，45.45 秒**；另增 5 項 TLS 測試；零失敗 | outputs/tls-full-pytest-results.xml |
| Streamlit 操作 | 六步精靈實際保存單人預覽及三人批次；條件 UI 真正生成十人；簡易模型保存；全部 14 頁與進階設定可操作 | tests/test_v2_ui.py |
| 真實 Chrome | 14 個頁面、1440×1050 桌面及 1024×768 平板；無 JavaScript 錯誤；動機 Excel 真正下載 | outputs/ui-v2/verification.json、01–14.png、tablet.png、motivation-browser.xlsx |
| 原核心與自動填表 | 原 61 項仍通過，包含頁面 / 方格 / 分流 / 必填、本地 Dry Run、授權提交及收件確認 | tests/test_browser.py 等原測試，完整 pytest 報告 |
| 持久化示範 | 新增六位條件人物、兩個 Mock 設定組及三個情境組，共五任務、30 份保存回答，全部完成 | outputs/v2-demo/manifest.json；本機 SQLite |
| 三格式報告 | 模型比較 / 情境 / 品質 / 動機各有 JSON、CSV ZIP、Excel；ZIP 完整、JSON 一致、Excel 可讀且無公式；大於儲存格上限的設定分段完整保留 | outputs/v2-demo/；tests/test_v2_quality_costs_reports.py |
| 安全遷移 | schema_version=2；升級前一致備份存在；原 entities、responses、answers 逐筆比較完全不變 | data/backups/before-v2.sqlite3；outputs/v2-delivery-verification.json |

完整 pytest 有 **20 項上游 DeprecationWarning**，來自 Streamlit `time_util` 對 NumPy / Pandas timedelta 的用法；不屬於測試失敗。瀏覽器關閉時 Windows 服務有連線重設訊息，未造成 UI 操作失敗。

最終指令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.tmp\v2-delivery-snapshot-final --junitxml=outputs\v2-pytest-results.xml
.\.venv\Scripts\python.exe scripts\verify_ui_browser.py --v2
.\.venv\Scripts\python.exe scripts\refresh_v2_reports.py
.\.venv\Scripts\python.exe scripts\verify_v2_delivery.py
.\.venv\Scripts\python.exe scripts\package_source.py --v2
```

瀏覽器與交付檢查需要本機服務及這次的示範 / 備份存在；pytest 使用獨立暫存資料庫，不污染本機示範。

## 功能驗收與適用範圍

| 功能 | 已交付的可執行行為 | 測試範圍與限制 |
|---|---|---|
| A 首頁 / 操作流程 | 最近問卷及任務、模型設定狀態、品質摘要；六步精靈；設定指紋變動後重新預覽；簡易 / 進階共用設定；原頁面保留 | AppTest 真正執行精靈，Chrome 檢視全部頁面。設定齊全不代表外部 API 已連通 |
| B Google 匯入 / 確認 | 已知公開頁面 metadata 與 DOM 退回；單 / 多選、文字、下拉、量表、方格、分頁及前向選項分流；官方 Forms JSON；警告、未解析資訊、編輯與預覽確認 | 樣本通過；後續一份公開正式問卷已實讀5區段33題，4題「其他」待映射。OAuth取回、區段描述完整保留、特殊驗證、循環／回跳仍需完善或人工處理；外部多頁填答／提交未驗證 |
| C 進階人設 | 年齡 / 性別 / 教育 / 職業比例、所得 / 預算、興趣、價值、熟悉度、人格區間；預覽分布、保存條件、固定人物快照 | 最大餘數、seed、退休 / 年齡與預算衝突測試通過；成年 18–100 歲；任意背景敘述不保證機器判定 |
| D 模型比較 | 固定問卷 / 人物、多設定檔、序列任務；完成率、格式拒絕率、邏輯檢查、耗時、Token / 費用、答案分布及同人物配對差異 | 兩個 Mock 設定流程與快照通過；原六服務商 Adapter 用 HTTP MockTransport 測試；無真實模型比較結果 |
| E 回答品質 | 重跑獨立驗證、分流與未完成紀錄、重複模式檢查；新任務重生、supersedes 關聯及保留原回答 | 已測未知題目 / 格式、人設、重複 review、重生不覆寫；任意領域的心理矛盾辨識不宣稱完整 |
| F 動機分析 | 原文關聯、多標籤主題、人物類型 / 購買意願群比較、明確拒絕訊號、文字摘要、可匯出報告；規則或 AI Adapter 分類 | 規則及 Mock AI 分類通過，Chrome 實際下載；真人心理效度、真實 API 分類品質尚未驗證 |
| G 情境實驗 | 固定人設與模型、可編輯情境、價格 / 個人化屬性、合法輸入、組間量表與理由、配對差異、完整任務設定匯出 | 三組 Mock 任務及受控對照測試通過；不強迫每個人的答案不同；未驗證外部模型情境理解 |
| H 用量 / 預算 | 簡易 / 進階 API、費用區間、即時回報用量、請求 / 重試前預算檢查、警告、暫停 / 繼續 / 取消 / 失敗重試與事件 | HTTP MockTransport 測試零預算阻擋、未知費用暫停、調整後續跑、認證錯誤不當格式修復；實際帳單與配額尚未驗證 |

完成率 = 保存回答數 / 預定人物數；包含保存後需 review / error 的回答，搭配品質欄位一起判讀。格式錯誤率 = 格式被拒絕的頁面輸出 /（成功頁面輸出 + 格式拒絕輸出），包含已修復與最終失敗，不把 API 401 / 額度問題計為格式錯誤。兩組 Mock 設定可能完全相同，驗證的是比較流程，不是服務商差異。

人物耗時累計實際執行（含頁面重試與執行中檢查），不含人工暫停時間。Token 以服務端回報為準；未知請求數另外列出。費用僅依有來源的手填費率推估，不自動引用未查證的價格，不混加不同幣別。預算控制在請求邊界執行，無法取代供應商硬額度；人物生成及另行分析費用不算入作答任務的預算。

## 示範與資料保存

原有資料：12 位人物、12 份回答；升級後：18 位人物、42 份回答。原人物、問卷、設定、回答及逐題資料保持不變，workspace 來源保留並增加版本資訊。

新增條件示範為六位成年人，18–29 / 30–55 歲各三人，女性 / 男性各三人，大學四人 / 研究所兩人，工程師 / 行政各三人，所得 35,000–70,000、可支配預算 3,000–8,000。條件、人物、ID 及實驗保存於 outputs/v2-demo；比例是測試情境。

| 實驗 | 設定 | 保存回答 |
|---|---|---|
| 模型流程示範 | Mock 基準 A / Mock 比較 B；同六位人物、同問卷與 seed | 12 |
| 情境流程示範 | 基本款 200 / 部分客製化 500 / 高度客製化 1,000；同六位人物、同問卷與模型 | 18 |

四類報告可直接打開；本機 UI 可以查看已保存任務，不需提供金鑰。審閱 ZIP 包含完整來源、測試、範例及上述匯出 / 截圖，不含 `.git`、`.venv`、`.env`、`data`、暫存或瀏覽器。新的安裝不會自動擁有這台電腦的歷史資料庫。

## 修改檔案與模組

| 範圍 | 新增檔案 | 延用 / 修改檔案 |
|---|---|---|
| 工作台 / 精靈 / 模式 | survey_sim/workflow.py、ui_workbench.py、ui_simple_provider.py | survey_sim/ui.py、__init__.py |
| 匯入 / 預覽確認 | survey_sim/google_import.py、questionnaire_review.py | survey_sim/parsers.py、ui_questionnaires.py |
| 條件人物 | survey_sim/v2_models.py、conditional_personas.py、ui_conditions.py | survey_sim/personas.py、mock_ai.py、ui_people.py |
| 比較 / 情境 / 品質 | survey_sim/experiments.py、quality.py、ui_v2_analysis.py | survey_sim/models.py、engine.py、batch.py、storage.py |
| 動機 / 匯出 / 成本 | survey_sim/motivations.py、reports.py、costs.py | survey_sim/analysis.py、providers.py、errors.py、ui_operations.py |
| 遷移 | survey_sim/migrations.py | survey_sim/storage.py |
| 自動化檢查與交付 | scripts/build_v2_demo.py、refresh_v2_reports.py、verify_v2_delivery.py | scripts/verify_ui_browser.py、package_source.py |
| 測試 | tests/test_v2_import_workflow.py、test_v2_conditions_experiments.py、test_v2_quality_costs_reports.py、test_v2_ui.py | 原測試不刪除、不改寫 |
| 文件 / 證據 | docs/FEATURE_ROADMAP_V2.md、docs/ACCEPTANCE_V2.md、outputs/ui-v2/、outputs/v2-demo/、outputs/v2-pytest-results.xml、outputs/v2-delivery-verification.json | README.md；V1 ACCEPTANCE.md / outputs/pytest-results.xml 保留 |

requirements.txt、requirements-tested.txt、.env.example、Windows 啟動腳本及原 Playwright 安全機制均延用，沒有新增必要套件。資料 schema 加法遷移，有升級前備份，不刪除舊表或改寫舊答案。

## 尚未實際驗證 / 未實作

- **真實 OpenAI、DeepSeek、Gemini、Claude、相容 API 與 Ollama：尚未實際驗證。**缺少真實 Key / 可用本地服務。要驗收，需在 UI 設定可用服務、連線測試，再執行單人預覽與小批次；目前協定檢查以原 HTTP MockTransport 完成。
- **外部表單多頁填寫與授權提交：尚未實際驗證。**後續已實讀使用者提供的公開Google正式問卷（5區段33題，4題「其他」待人工對應），但沒有填答／提交，也未取得獨立測試複本。提供測試複本後，需逐題核對頁面、分流、對應與成功標記，先Dry Run再驗證提交。既有本地填表真的跑過。
- **Google OAuth/API 代取、所有特殊題型 / 驗證與回跳分流：未實作完整自動化。**已實作已取得官方 JSON 匯入、可辨識公開資料與人工修正流程，不宣稱官方完整抓取。
- **真人基準、心理分類效度、真實需求預測與因果推論：未提供這些功能或證據。**工作區與報告保存 simulation 來源；正式樣本需用獨立系統 / 資料集，外部提交預設 Dry Run 且保留原授權與 allowlist。
- **高併發排程與供應商帳戶硬額度：未實作。**維持單 worker、有間隔、持久化恢復與任務預算控制，適合本機測試及小批次；沒有假裝提供帳戶級費用保證。
- **其他電腦全新安裝：尚未實際驗證。**本機既有虛擬環境已通過；Windows 一鍵腳本延用原已驗證版本。其他電腦需 Python、套件及可用瀏覽器。
- **GitHub：依要求尚未更新。**本次只準備本機可審閱版本與 ZIP。

初次操作、備份與回復、分析指標及 API 設定見 [README](../README.md)。原始需求與開發順序見 [FEATURE_ROADMAP_V2.md](FEATURE_ROADMAP_V2.md)。

## 2026-10-13 HTTPS 連線修正

使用者測試 DeepSeek 時，UI 原本顯示通用「連線逾時或無法連線」。本機日誌確認真正原因為 `CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`。不帶金鑰的只讀探測重現：HTTPX 預設 CA 失敗，系統 CA 加 certifi 可成功驗證並取得 HTTP 401；驗證後的憑證簽發者為 **Avast Web/Mail Shield Root**，用途為本機防毒 HTTPS 掃描。

修正 survey_sim/providers.py，新增 survey_sim/tls.py，使用 Python 安全 SSL context 讀取系統已信任 CA 及公開 CA bundle；明確設定 SSL_CERT_FILE / SSL_CERT_DIR 時遵守自訂信任範圍，失敗不退回或停用驗證。主機名稱與憑證驗證保持啟用，不修改 Windows 憑證或防毒設定。憑證錯誤不重試，並與 Timeout / 其他 TransportError 分開顯示。

新增 tests/test_tls.py：驗證開啟、明確 CA 設定、無效 CA 停止、憑證錯誤不重試 / 不誤標逾時、其他網路錯誤的有限重試。相關 Provider / 預算 / 報告測試 **32 passed**；全套 **101 passed、20 項上游警告、45.45 秒**。測試曾受沙箱對 Avast SSL 管道的存取限制，改用一般本機權限後通過，未改動防毒或關閉 SSL。

證據：outputs/tls-verification.json、tls-pytest-results.xml、tls-full-pytest-results.xml。README 已加入排錯說明，審閱 ZIP 包含修正與上述證據。本機服務已重新啟動，健康檢查為 ok，GitHub 仍未更新。

**HTTP 401 探測不代表金鑰或模型作答成功**，因為沒有送金鑰、也沒有呼叫付費生成。截圖中露出的金鑰未用於測試；需使用者在供應商平台撤銷並替換後，再由 UI 保存及測試。真實 API 作答品質、Token / 費用仍未驗證。

## 2026-10-13 網站操作預覽試跑

已用使用者提供的網站與公開正式問卷，完成一位既有人物（31歲、高度興趣型、持續收藏）在CUSTOM方案的真實瀏覽器操作：框色改冰川冷藍、加入MUSIC 2026、選Outfit字型、調整Y至106mm及黑字，查看最後預覽，確認背景功能受限。使用網站原有示範卡，未上傳圖片，尚未確認是否與研究團隊指定示範圖一致。

未點作品／問卷送出；遠端POST預覽保護攔截14個Google遙測請求，沒有額外DeepSeek呼叫。沒有修改ONLYFRAME網站或平台核心，也沒有把候選回答存入平台正式任務。這是本次助手逐步操作的可行性試跑，尚非新批次模組。

Google公開metadata實際讀到5區段33題，4題含「其他」尚需人工映射；區段操作／願付金額說明另行唯讀取回，現有匯入模型尚未完整保留區段描述。只核對公開結構與第一頁DOM，沒有填答或逐頁測分流，草稿confirmed=false、purpose=reference。

Q9要求成功提交，試跑只完成預覽，因此不通過正式成功分支；其兩個選項亦未精確涵蓋本次預覽限制。33題候選中的操作後回答另外列為預覽示範，感受與意願為人設推估、部分背景為補充假設，均不當作真實受訪者紀錄或完整有效問卷。

證據為outputs/website-pilot/live-pilot：30張操作／觀察截圖、browser-events.json、form-context-notes.json、未確認問卷草稿、人設快照、33題JSON／CSV與PILOT_REPORT.md。REVIEW.html為可離線篩選的報告，Chrome驗證33列、4列操作證據、2列受限、搜尋與內嵌圖通過，無JavaScript錯誤；壓縮包ONLYFRAME-網站操作試跑.zip完整性檢查通過。GitHub仍未更新。
