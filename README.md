# AI-Respondent-Studio V2 · AI 問卷情境模擬平台

## 2026-10-14 整合工作台

首頁「問卷工作台」可在同一頁選取或解析 Google Forms 問卷、選取既有人物或指定 AI 生成人數與分布、切換模型，一次開始人物生成、答題、驗證、保存及 CSV ZIP / Excel / JSON 匯出。預設只產生模擬資料。選擇 Dry Run 才批次填表；真正提交需要表單授權與本次明確確認。格式、必填與跳題錯誤會略過；只有「AI 不確定」提醒的答案可送到已授權測試表單，提醒仍保留。外部表單的成功畫面須與後台回覆數分開核對。

側欄整合為「問卷工作台、人物資料庫、問卷管理、任務紀錄、AI 模型設定」。人物資料庫可多選、搜尋、篩選、全選／取消及保存群組。舊版回答檢查、品質、分析、實驗、備份、單份填表與網站體驗工具保留在「任務紀錄 → 檢視內容」，新工作台不需要先操作其他網站。

工作台進度保存到 SQLite，可暫停、取消、接續及只重試失敗項目。填表失敗保留已生成答案；成功或狀態不明的提交不會自動重送。Google 公開解析仍需核對題目、頁面與跳題；登入、驗證碼、特殊題型或無法辨識的分流會停止並提供錯誤。

舊資料庫會先備份再遷移至 schema 4，只新增 workbench_jobs；不刪除人物、問卷、回答或模型設定。新工作區啟動：雙擊 `啟動系統.bat`。既有虛擬環境可執行 `.venv\Scripts\python.exe -m streamlit run app.py`。

本次盤點與差異分析見 [PROJECT_INVENTORY_V2.md](docs/PROJECT_INVENTORY_V2.md)，操作與驗收見 [INTEGRATION_V2.md](docs/INTEGRATION_V2.md)。下方保留原版本歷史說明；旧版操作順序與本機資料數量不適用於最新整合工作台。

可在 Windows 本機操作的 AI 虛擬受訪者、問卷模擬與授權表單測試工具。核心流程已實作：**建立人物 → 逐頁回答 → 邏輯驗證 → SQLite 儲存 → Playwright 填表與確認收件**。

2026-10-14 增加 ONLYFRAME 接續流程：**人物生成時由 AI 選定並保存方案 → 前兩階段問卷 → 同方案網站設計 → 回原問卷填體驗題 → 完成問卷**。在人物管理啟用固定方案，在網站體驗、模擬控制台或快速開始設定暫停頁與方案題。操作及驗證限制見 [分階段問卷操作說明](docs/STAGED_SURVEY_WORKFLOW.md)。

V2 沿用原架構，增加六步快速開始、問卷預覽與確認、人設條件分布、多模型比較、品質重生、動機分析、情境實驗及任務預算控制。原有管理、批次、分析、匯出及授權填表功能皆保留。本次版本先交付本機審閱，尚未更新 GitHub。

無 API Key 也能使用 Mock 完成整個流程。Mock 採情境相關的規則，供功能測試，不能代表大型語言模型的回答品質。人物比例、偏好及圖表均描述使用者設定的模型情境，不能推論真實人群。

![V2 首頁工作台](outputs/ui-v2/01.png)

## 本機 V2 審閱

在這台電腦開啟 **http://127.0.0.1:8501**，或雙擊 `start.bat` / `啟動系統.bat`。首頁可按「快速開始」，側欄可切換「簡易模式 / 進階模式」。所有原本頁面仍可直接進入。

本機資料庫保留原有 12 位人物與 12 份回答，另外已完成 6 位條件人物、兩組 Mock 模型設定及三組產品情境，共新增 30 份回答。可到「模型比較 → 查看比較結果」、「情境實驗 → 查看情境結果」直接檢視。

審閱包為 `outputs/AI-Respondent-Studio-V2-本機審閱.zip`，包含程式、測試、範例、操作文件、V2 截圖與示範報告；不含本機資料庫、金鑰、虛擬環境或瀏覽器。新電腦解壓縮後會建立新的資料庫；可匯入 `outputs/v2-demo/personas.json`，或依下方操作重新建立實驗。兩個 Mock 設定可能產生相同答案，這是比較流程測試，並非兩家真實模型的效能結果。

開發紀錄見 [V2 路線與驗收標準](docs/FEATURE_ROADMAP_V2.md)，實際結果與外部驗證限制見 [V2 驗收報告](docs/ACCEPTANCE_V2.md)。

## 從 GitHub 下載

目前 GitHub 仍是原先版本；以下是原通用安裝方式。本次 V2 請使用本機專案或審閱包，待使用者看過後再更新儲存庫。

1. 在 GitHub 儲存庫按 **Code → Download ZIP**，將檔案完整解壓縮。
2. 安裝 Python 3.11 或以上，雙擊資料夾中的 **`start.bat`** 或 **`啟動系統.bat`**。
3. 首次會安裝套件並建立本機資料庫，接著開啟網頁介面；沒有 API Key 也可使用 Mock。

GitHub 不含本機資料庫、API 金鑰及 `.venv`。範例人物可在人物管理匯入 `examples/personas.json`；已完成的 12 人示範匯出在 `outputs/demo/`。若要在新的本機資料庫重建完整示範，可執行 `.\.venv\Scripts\python.exe -m survey_sim.cli demo --count 12 --browser`。

## 初次啟動

1. 在這台已完成安裝的電腦，雙擊 **`start.bat`**（亦提供 `啟動系統.bat`）。
2. 等待本機網頁開啟，預設網址是 **http://127.0.0.1:8501**。
3. 第一次開啟會有 ONLYFRAME 及數位服務兩份可操作的測試問卷。交付的本機資料庫另包含已實際執行的 12 位示範人物及結果。
4. 保留啟動視窗；關閉它會停止服務。重新啟動後，資料仍在 `data/simulator.sqlite3`。

其他電腦需安裝 [Python 3.11 或以上](https://www.python.org/downloads/windows/)，勾選 Add Python to PATH，然後雙擊 `start.bat`。首次會建立獨立 `.venv` 並安裝 requirements。腳本會略過不可用的 WindowsApps Python 別名，也能使用 Python Launcher 或設定 `PYTHON_EXE`。

瀏覽器自動化優先使用已安裝的 Chrome / Edge；若沒有，雙擊 `install-browser.bat` / `安裝瀏覽器.bat` 安裝 Playwright Chromium。日常操作皆在網頁完成，不需修改 Python 程式。

若連接埠占用，可將 `.env.example` 複製為 `.env`，修改 `APP_PORT` 或 `MOCK_FORM_PORT`。`.env` 不加入版本控制，API Key 欄位可保持空白。

## 六步快速開始

1. 按首頁「快速開始」，選已確認問卷。新問卷可上傳 JSON / CSV，或按「建立或核對問卷」；先在問卷管理人工確認後再回來。
2. 選模型設定檔。先用 Mock 即可；要換服務商，可到「AI 模型設定」保存設定並測試連線。首頁顯示設定是否齊全，並不代替連線測試。
3. 選已保存的人物；也可展開「生成新人物」。進階分布請先到「虛擬人物管理」生成，再回精靈選取。
4. 設定本次人數、回答模式及 seed；進階模式另提供人物間隔與自訂變動。可選任務預算上限。
5. 按「執行一人預覽」。預覽會真正呼叫選定模型、保存結果，可能產生 API 費用；核對答案與理由後按「確認預覽，下一步」。改變問卷、人物、模型或參數後需要重新預覽。
6. 按「開始完整模擬」，查看進度、暫停、停止或繼續，下載資料或查看回答。「建立另一個模擬」重置精靈，不會刪除歷史結果。

預覽是一個獨立任務；完整批次會包含原本選取的所有人物，因此預覽人物在批次中會再次回答。結果以 `task_id / response_id` 區分。

## 原完整流程

Google Forms 的單選與複選題可保留「其他」自由輸入選項。選取結果仍保存為選項 ID，補充文字另存 `other_text`；勾選「其他」時必須填寫文字，未勾選時不可附帶文字。預覽會顯示補填欄位，回答檢查會顯示完整內容。CSV / Excel 的「回答」另有 `題目ID__other_text` 欄，「回答明細」及 JSON 同時保留選項與文字，選項分布仍將「其他」計為一個選項。舊資料庫首次啟動會自動備份並升級，歷史回答保留。先前匯入時已標成不支援的草稿，需要重新匯入或修正其題型與「其他文字選項 ID」。

1. **AI 模型設定**：先選 Mock 設定檔；可測試連線或建立其他廠商的設定檔。
2. **問卷管理**：選 ONLYFRAME 功能測試問卷，查看題目、頁面及分流。範例已確認；自行匯入的問卷需逐題核對後確認。
3. **虛擬人物管理**：選主題、人物數量、seed、人設類型或比例，按「生成並儲存人物」。可查看及編輯每位人物。
4. **AI 模擬控制台**：選問卷、人物與回答模式，先預覽人物，按「建立批次任務」，再按「開始 / 繼續」。
5. **回答檢查**：查看答案、每題簡短決策依據、跳題路徑與驗證結果。
6. **自動填表測試**：選已完成回答，建立本地 Mock Form；再從表單選單選取保存的本地表單。執行 Dry Run 觀察預覽，再執行授權測試提交。
7. **結果分析**：看選項分布、量表平均、人物分組、分流與人物相似度；按「準備 CSV、Excel、JSON 匯出」下載。

## 十四個操作頁面

| 頁面 | 可執行功能 |
|---|---|
| 儀表板 | 快速入口、最近問卷 / 任務、模型設定狀態、品質摘要；原統計在展開區 |
| 快速開始 | 六步精靈、單人實際預覽、設定變更檢查、批次與匯出 |
| AI 模型設定 | 多設定檔、切換 provider、Key、Base URL、模型、溫度、Token、逾時、重試、連線測試、手動費率 |
| 問卷管理 | 手動 / JSON / CSV / Google 公開資料 / 官方 Forms JSON 草稿、編輯、分流、網頁對應、語意分析、問卷預覽及人工確認 |
| 虛擬人物管理 | 原兩階段生成與管理；增加年齡 / 性別 / 教育 / 職業比例、預算、興趣、熟悉度、價值觀及人格區間 |
| AI 模擬控制台 | 任務快照、人物預覽、逐頁回答、即時進度、開始、暫停、停止、繼續、失敗項目重試、紀錄 |
| 回答檢查 | 最終答案、理由、格式驗證、分流略過、人工檢查、自動重試歷程 |
| 回答品質 | 重新驗證、異常分級、重複模式、失敗紀錄；以原快照建立重生任務並保留原回答 |
| 模型比較 | 固定人物及問卷、多設定檔實驗；完成率、格式、耗時、用量、費用、配對差異與報告 |
| 動機分析 | 理由 / 文字多標籤分類、人設及意願分組、明確拒絕訊號、逐段核對、三格式報告 |
| 情境實驗 | 固定人物與模型、可編輯情境、分組圖表、同人物差異、保存設定及報告 |
| 自動填表測試 | 本地表單、授權外部表單、精確 URL Allowlist、動作預覽、Dry Run、提交、成功標記確認、截圖、未知狀態人工查證 |
| 結果分析 | Plotly 圖表、量表平均、背景與人設分組、組合集中度、分流及人格相似度 |
| 系統設定 | 資料集來源、SQLite 備份、完整資料匯出、除錯日誌 |

## 人設與回答方式

生成人設先建立成年人物的背景與生活情境，再根據背景推導心理特徵、核心價值觀及行為。主題延伸資訊存於 `topic_attributes`；金融、服務、教育及產品問卷皆可使用，沒有固定成收藏者。

價格、品質、外觀、品牌、風險、衝動、理性、社群、個人化與新事物接受程度均為 0–1。Mock 使用相關的潛在生活因素及合理例外；真實 AI Adapter 將背景與完整 schema 交給模型產生並驗證，背景在第二階段不得改變。

人物比例以最大餘數法分配完整人數，再按 seed 打亂順序。生成時檢查近 100 位的人設相似度，高度相似會有限重生；分析頁提供前 100 位完成者的相似矩陣。相似度是工程檢查指標，不是心理計量量尺。無法保證大批人物永不相似或答案永不重複。

Mock 的同 seed / 設定可重現。真實 API 受服務、模型版本及抽樣影響，不保證完全重現；人物、問卷、模型及回答模式快照仍可追溯。人物修改會增加修訂版，歷史回答保留當時快照。

引擎每頁提供同一人物、整份問卷、語意註記與先前答案，採結構化輸出及本地驗證。高一致性、自然變動與自訂變動均保留合法選項，不以故意答錯製造自然感。對長問卷，逐頁保存 checkpoint，避免要求一次輸出過長的答案。

### 進階受訪者條件

到「虛擬人物管理 → 建立人物 → 進階受訪者條件與分布」，勾選啟用。年齡 / 性別可直接編輯比例表；教育及職業以每行 `名稱|比例` 輸入。比例不需加總 100，例如 `行政職員|2`、`工程師|1` 表示 2:1。按「預覽指定條件分布」檢查計畫，再生成並儲存。

可設定所得與可支配預算區間、興趣、核心價值觀、產品熟悉程度及人格特徵區間。各維度先按最大餘數分配人數，再以 seed 排序與共同處理背景；預算不得超過所得，退休 / 年齡不相容會提示調整。生成時先套用背景再推導行為，條件保存於人物的 `topic_attributes.generation_conditions`。數量較少時，實際比例會依完整人數四捨分配。

目前支援 18–100 歲成年人物；各欄位是獨立指定的邊際比例，並非任意多維聯合分布求解器。自然語言自訂背景會提供給模型並保留供核對，不保證能自動驗證所有領域的條件。相同人物可在不同問卷 / 模型 / 情境重用；實驗保存完整人物快照，後續編輯不改寫既有實驗。

## AI Provider 設定

| 服務商 | 實作協定 | Base URL 預設 |
|---|---|---|
| OpenAI | Chat Completions，Bearer，`max_completion_tokens` / 可切換 `max_tokens` | `https://api.openai.com/v1` |
| DeepSeek | 官方 OpenAI 相容 Chat Completions，`max_tokens` | `https://api.deepseek.com` |
| Gemini | 原生 `generateContent`、`systemInstruction`、`generationConfig`，`x-goog-api-key` | `https://generativelanguage.googleapis.com/v1beta` |
| Claude | 原生 Messages、獨立 `system`、`x-api-key`、`anthropic-version` | `https://api.anthropic.com` |
| Ollama | 原生 `/api/chat`、`stream=false`、`options`、`format=json` | `http://localhost:11434` |
| 相容 API | 可設定 Base URL 的 Chat Completions | 由使用者填寫 |

模型名稱手動填入帳戶可用名稱，不假定每家 API 或參數相同。Claude 採提示要求 JSON 並在本地驗證，不送 OpenAI 的 `response_format`。有些模型不接受溫度、JSON 模式或特定 Token 欄位；在介面停用 / 切換相關設定。收到 400 會顯示參數說明，不會暗中換模型。

401、403、402、404、429、5xx、Timeout、無效 JSON 及輸出截斷皆有可讀錯誤。網路、429 及 5xx 採有限退避；`Retry-After` 數字值上限 30 秒。格式不合法的頁面最多修復兩次，持續失敗後保存前面頁面並標記失敗人物。

API 請求設有最短間隔，人物之間另可設定間隔；批次可設定 1 至 5 位人物同時處理，網站體驗與預算限制任務固定依序執行。不同瀏覽器工作階段手動觸發的 API 操作不具全域服務商限速，仍需按帳戶配額合理設定。

金鑰預設只存在本次工作階段。可選 Windows 認證管理員保存；失敗會明確告知，不會退回明文檔。也可自行在 `.env` 設定官方環境變數。ProviderConfig、SQLite、匯出檔不含金鑰；日誌對已登記金鑰及認證標頭做遮罩。清除 UI 保存金鑰不會修改使用者的 `.env`。

API Token 使用量採服務回應計數；無計數時留空。費用必須同時填輸入 / 輸出單價、幣別及可查證來源 / 日期才估算；不內建未經核對的費率，亦非帳單總額。Mock 不產生虛構 Token 或費用。

### 簡易 / 進階 API 設定與預算

簡易模式可新增設定檔、選 provider、輸入模型 / Key / Base URL、測試連線及保存。溫度、JSON 模式、Token 欄位、逾時、有限重試、手動費率及金鑰管理在進階模式。兩種模式共用同一組設定，不會另建一套 Adapter。

控制台與模型比較會顯示任務費用規劃區間。其輸入部分以文字長度估算，輸出部分保留最大 Token；任務上界另計兩次格式修復及設定的網路重試。未填可靠費率顯示無法估價；Mock 顯示無 API 費用。此估算只涵蓋作答任務，不含另外的生成人物、語意分析或動機分類費用。

啟用預算後，在每次 HTTP 請求（含重試）之前檢查已知費用及本次保留額度。達警戒比例記錄警告；剩餘不足或已有未知費用的請求會暫停並保留頁面與完成回答。可在任務或實驗結果的預算區調高 / 取消上限，再按繼續。價格未知時，不會把費用當零繼續。請求前控制是本機規劃，無法取代服務商帳戶硬額度，也不保證實際帳單一定低於估算。

### HTTPS 連線錯誤

若瀏覽器能開啟服務，但程式回報 `CERTIFICATE_VERIFY_FAILED`，可能是 Python 使用的 CA 憑證與 Windows 已信任的憑證不同。程式已改用系統受信任 CA 加 HTTPX 的公開 CA bundle，保持憑證及主機名稱驗證；不修改機器憑證、不關閉 SSL 驗證。若使用 `SSL_CERT_FILE / SSL_CERT_DIR` 明確指定 CA，會遵守該設定，檔案錯誤會停止。

現在憑證失敗、請求逾時與其他連線失敗有不同訊息；憑證失敗不重複嘗試。只有真正逾時才考慮在進階模式增加 Timeout。API Key / 額度錯誤則需要帳戶端處理。連線測試必須在保存設定後選取該設定檔。

本機已以**不帶金鑰的 GET /models** 確認 DeepSeek HTTPS 可達，回傳 401 是預期的未認證結果；這不等於有效金鑰或模型作答已驗證。若截圖意外露出 Key，請先到供應商平台撤銷並建立新 Key，再於 UI 保存與測試，不要提供明文金鑰。

## 問卷匯入與結構

範例檔案在 `examples/`：

- `onlyframe_questionnaire.json`：17 題、三頁、條件顯示、多頁分流、全部支援題型。
- `general_questionnaire.json`：數位服務主題，展示正向與反向註記。
- `questions.csv`：最小可操作的 CSV 範例。
- `personas.json`：8 位完整、可編輯及匯入的人物。

**ONLYFRAME 範例僅為功能測試，並非使用者的正式研究問卷或經驗證研究量表。**真正問卷可另行匯入。

題型 ID：`single`、`multiple`、`dropdown`、`short_text`、`paragraph`、`linear_scale`、`likert`、`single_grid`、`checkbox_grid`。特殊題型用 `unsupported` 保留並顯示警告；修正前不可確認。

JSON 基本結構如下（完整欄位可直接下載範例，不需寫 Python）：

```json
{
  "id": "my-test",
  "title": "服務測試問卷",
  "topic": "數位服務",
  "purpose": "test",
  "pages": [{
    "id": "P1",
    "title": "第一頁",
    "questions": [{
      "id": "Q01",
      "title": "您是否使用此服務？",
      "type": "single",
      "required": true,
      "options": [{"id":"yes","label":"是"},{"id":"no","label":"否"}]
    }]
  }]
}
```

CSV 至少需 `id,title,type`。選填欄位包含 `required,options,rows,page_id,page_title,scale_min,scale_max,min_choices,max_choices,max_length,concept,trait,reverse,persona_field,display_if,routes,default_next,binding`。選項可以 `價格|品質|品牌`，或以 CSV 引號包住 JSON 陣列。方格列、條件、分流與對應欄位使用 JSON；以同頁第一列的 routes/default_next 定義頁面規則。

題目 ID 固定，選項及方格列亦使用 ID，畫面文字改變不會靠順序猜測。頁面條件按順序採第一個符合規則；`default_next` 空白則依頁序。跳頁僅允許向後頁面或 `END`，不支援循環問卷。條件運算有 `eq,ne,includes,gt,gte,lt,lte`，顯示條件全部成立才出現。

Google Forms 網址匯入先讀取公開頁面可辨識的 metadata，可解析已知結構的單 / 多選、下拉、文字、量表、方格、分頁及前向選項分流。這是 Google 未承諾穩定的公開頁面結構；結構改變時退回當前頁面 DOM 草稿，不自動當作完整問卷。無法辨識的題型、其他選項、循環 / 反向分流及特殊驗證會保存警告或未解析資訊，需手動修正。

也可上傳已經由有權限使用者取得的官方 `forms.get` JSON，依官方 schema 辨識上述欄位。**本版未實作 OAuth 登入或代取表單 API**。所有 Google 草稿均需人工確認；不因讀到文字就判定解析完成，不回答題目來探索分流，也不繞過登入、驗證碼或存取限制。後續已實讀使用者的一份公開正式問卷（5區段33題，4題「其他」待人工對應）；外部多頁填寫與提交尚未實測。

到「問卷管理 → 預覽與確認」核對所有頁面、題型、必填、選項及分流，閱讀解析資訊。需逐項勾選核對後保存確認。遇到 `unsupported` 先回編輯頁修正，未確認問卷不能建立批次或實驗；任何編輯會產生新修訂並取消確認。原編輯頁的確認操作亦保留。

介面提供題目 / 頁面 / 分流選單、選項編輯與完整 JSON 編輯。Google 自動化可使用題目標題或容器 CSS selector、選項文字覆寫及方格列 selector；必須人工核對與 Dry Run，網站結構改變時需更新對應。

## 邏輯驗證與批次恢復

驗證分為通過、人工檢查與明確錯誤。格式、必填、選項 ID、量表範圍、方格列、重複題目與分流外回答屬明確錯誤。明確註記的文字人物欄位（如年齡、職業）須一致。

人格與量表差距過大、缺少決策依據、主題預算超過每月可支配金額或指定跨題規則出現差異，標記人工檢查。喜歡個人化但不願多付費不直接視為矛盾。這版不宣稱能自動辨識任意領域所有心理矛盾；研究者應核對語意分析及人工檢查項目。

可在 JSON 的 `consistency_rules` 設定 `{left,right,relation,tolerance,explanation}`，relation 為 `same` 或 `reverse`；系統保留差異作人工檢查，不直接推定態度錯誤。

任務保存完整快照、逐人狀態、頁面 checkpoint、嘗試次數及事件。暫停 / 停止會讓目前 HTTP 請求在逾時設定內結束，保存完成頁面後停下；已完成人物不重新生成。重啟後中斷任務變為暫停，點繼續恢復。失敗重試只重排 `failed` 項目；有已保存的明確錯誤結果可調整問卷或人物後建立新任務。

同一資料庫請只開一個服務實例；不要在 UI 批次仍執行時對相同資料庫跑 CLI demo 或啟動第二份程式。

## V2 比較與分析操作

### 回答品質與重新生成

選任務後可看格式、必填、分流、人設及設定的跨題規則，並核對每條異常。排除人口背景 / 文字題後，同一任務至少 3 人、且至少 30% 出現相同答案模式會標記人工檢查；合理的重複或態度差異不會自動判成明確錯誤。

選問題回答並按「建立重新生成任務」。原答案保留，新回答使用原問卷、人物、模型及情境快照，延用變動程度、間隔與預算；可調整新 seed，並用 `supersedes_id` 關聯原回答。不同原任務的結果需分別重生。若另有任務執行中，先暫停 / 停止，再到控制台執行已保存的重生任務。

### 多模型比較

1. 先在 AI 模型設定建立至少兩個設定檔，逐一測試連線。
2. 「模型比較 → 建立模型實驗」選已確認問卷、固定人物、模型設定及相同 seed / 回答模式，保存實驗。
3. 「查看比較結果」選實驗，按「執行 / 繼續實驗」。各組以單 worker 依序執行，可暫停目前任務、取消未完成項目或重新排入失敗人物。
4. 查看完成與品質、耗時與 Token、費用設定、題目分布、量表及同人物配對差異；按「準備分析報告下載」。

完成率為保存回答數 / 預定人物數，需搭配錯誤與人工檢查比例。格式錯誤率計算格式被拒絕的頁面輸出 /（成功頁面輸出 + 格式拒絕輸出），涵蓋修復及最終失敗；認證或額度錯誤不計格式錯誤。耗時是人物實際執行時間；未知 Token / 費用另外列出，不當作已知零。不同幣別不可直接相加。

### 動機分析

選已完成任務及購買意願量表，使用「規則分類」即可離線分析；「AI 輔助分類」使用選定 Adapter，需另行支付 API 費用。輸出保留逐段原文與 response / question ID，可核對價格、需求、外觀、實用、個人化、品牌、情境及猶豫等多標籤主題。

意願群依選定量表上下界正規化，≤0.4 為低、≥0.6 為高，其他或缺答另列。分組圖以每人平均片段數呈現，仍受題目及分流曝光不同影響。拒絕原因只整理低意願群體原文明確拒絕訊號，不從低分推定原因。這是模型解釋的主題整理，未經真人資料或心理計量方法驗證。

### 情境實驗

「情境實驗 → 建立情境實驗」固定人物、問卷與模型，編輯各組名稱、情境敘述、價格及客製化程度，保存後執行。一般產品或服務可修改敘述，不限 ONLYFRAME。價格使用人物預算相同單位；客製化範圍 0–1。Mock 只有有限的價格 / 個人化情境規則，真正語意情境需模型理解且另行核對。

所有實驗保存問卷、人物、模型、情境及各任務完整參數。JSON、CSV ZIP、Excel 報告包含設定及配對差異；Excel 的過長設定文字依分段順序保存，避免單一儲存格截斷。相同 seed 能重現 Mock 設定，不保證外部模型逐字重現。結果只描述 AI 模擬情境，不能解釋為真人預測準確率、市場需求或因果效果。

## 授權表單測試

每個表單目標保存用途、問卷 ID、授權狀態與成功判定。正式研究參考問卷可以離線模擬，但禁止送入原正式表單；如需測試，使用獨立測試複本與測試 URL。

URL Allowlist 精確比對完整網址，不使用網域萬用字元。移除查詢參數及片段；Google 請使用展開的 `docs.google.com/forms/.../viewform`。Dry Run 填寫及保存截圖，不按提交；真實提交必須明確確認測試授權並設定提交後才出現的成功元素 / 文字。瀏覽器主頁導覽限制於指定頁面及 Google 該表單提交頁，不前往登入或其他未授權主頁。

本地表單涵蓋多頁、分流、必填、多選限制與兩種方格。伺服器在收件端重新檢查格式及路徑，成功會保存唯一收件編號。自動化不只按提交，還會核對畫面收件編號與 SQLite 紀錄。收件 token 具有冪等保護，同份回答送相同本地表單不增加第二筆收件。

外部表單不能保證伺服器冪等。SQLite 會阻擋已成功、正在送出或狀態不明的同回答 / URL 組合。按提交後未能確認成功會記錄 `unknown`，需要使用者查看接收端紀錄，再在網頁保存「已收到」或「確定未收到」；不自動重送。系統不規避驗證碼、繞過存取限制或偽裝真人。

## 儲存、備份及匯出

資料庫在 `data/simulator.sqlite3`。主要資料表：workspace、entities（人物 / 問卷 / Provider / 測試表單）、tasks、task_items、responses、answers、usage、events、submissions、local_receipts。

V2 的實驗亦存於 entities，品質重生關聯存於 quality_actions，遷移紀錄存於 schema_migrations。首次升級既有資料庫前，建立 `data/backups/before-v2.sqlite3` 一致備份，再以交易進行加法遷移；既有回答不覆寫。新欄位具有預設值，可讀取 V1 JSON；重啟不會重複遷移。

若需回復，先停止本專案服務，將整個 `data` 資料夾另存後，將升級前備份複製至新的資料夾內並命名 `simulator.sqlite3`，在 `.env` 的 `APP_DATA_DIR` 指向該資料夾。避免將舊備份與目前的 WAL / SHM 檔混用；不要在服務仍寫入時直接覆蓋資料庫。以 V2 開啟 V1 備份會再次安全升級，若要回到原介面需另外使用原 V1 程式。

資料集來源只在工作區 / 匯出層級記錄，不在每題反覆加標籤，也不要求 `synthetic=true`。本系統沒有匯入真實受訪者回答的功能，因此正式研究樣本需存於其他工作區或系統。

CSV ZIP、Excel、JSON 包含來源、人物、每份回答、每題理由、題目對照、執行紀錄、驗證、API 用量與提交紀錄。`persona_id`、`questionnaire_id`、`question_id`、`task_id`、`response_id` 及修訂資訊可關聯。工作區人物匯出包含歷史人物版本，以免刪除 / 修改人物後失去對照。多任務同一人物可以有多列回答，靠 task/response ID 區分。

CSV 採 UTF-8 BOM，Excel 有標題樣式、凍結列與篩選。多選 / 方格使用 JSON 保留 ID 結構。為避免開啟外部匯入文字時觸發試算表公式，`=,+,-,@` 起始字串在 CSV / Excel 加前置單引號；JSON 保留原始文字（已登記金鑰仍會遮罩）。

除錯日誌在 `data/logs/debug.log`，採大小輪替；截圖在 `data/artifacts/`。可在系統設定建立一致的 SQLite 備份。不要只在程式執行中複製主 `.sqlite3` 而漏掉 WAL；請使用備份按鈕，或關閉服務後複製整個 data 資料夾。

## 開發與測試

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp=.tmp\pytest
.\.venv\Scripts\python.exe -m survey_sim.cli examples
.\.venv\Scripts\python.exe -m survey_sim.cli demo --count 12 --browser
```

也可雙擊 `test.bat`。一般單元測試及介面測試不呼叫真實 API；Provider 使用 HTTP MockTransport 驗證各家 endpoint、標頭、payload、回應與用量。browser 標記的測試真的啟動 Chrome / Edge / Chromium 操作本地 HTTP 表單，沒有 Google 或第三方提交。

架構：`models` 資料契約、`providers` 廠商 Adapter、`mock_ai` 測試規則、`personas` 兩階段人物、`parsers` 匯入、`engine` 逐頁回答、`validator` 獨立驗證、`batch` 任務 worker、`storage` SQLite、`mock_form` 本地收件端、`automation` Playwright、`analysis` 統計及匯出、`ui_*` 繁中管理頁面。

V2 模組：`workflow / ui_workbench` 操作精靈、`google_import / questionnaire_review` 匯入確認、`v2_models / conditional_personas` 條件、`experiments` 模型及情境、`quality` 品質重生、`motivations` 主題分析、`costs` 預算、`reports` 分析匯出、`migrations` 安全升級。仍由既有 engine、batch、storage、providers 驅動核心流程。

V2 驗收請見 **`docs/ACCEPTANCE_V2.md`**；機器報告為 `outputs/v2-pytest-results.xml`，真實 Chrome 14 頁截圖為 `outputs/ui-v2/`，完整示範報告為 `outputs/v2-demo/`。原 `ACCEPTANCE.md` 與 `outputs/pytest-results.xml` 保留 V1 驗收證據。

可執行以下 V2 工程驗證（需先啟動網頁；一般使用不需執行）：

```powershell
.\.venv\Scripts\python.exe scripts\verify_ui_browser.py --v2
.\.venv\Scripts\python.exe scripts\refresh_v2_reports.py
.\.venv\Scripts\python.exe scripts\verify_v2_delivery.py
.\.venv\Scripts\python.exe scripts\package_source.py --v2
```

`scripts/build_v2_demo.py` 可在沒有執行中任務時重建 Mock 示範；會新增實驗任務及結果，請勿把它當成只讀檢查。`verify_v2_delivery.py` 針對本次保留 V1 備份與既有示範資料驗證，新空資料庫沒有這些前置資料。

## 網站操作與設計提交（新增）

2026-10-14 提交修正：接收 API 空白時在送出前提示；被攔截的新增請求顯示「未送出」，已放行但結果不明仍禁止重送。相容新版 Supabase 無資料列成功回覆、數字或字母數字尾碼編號。兩筆被攔截的紀錄已修正；後續一筆使用者原 CUSTOM 請求已有 HTTP 201，更正先前編號格式造成的誤判，修正未重送。該證據是 API 新增回應，單筆讀回沒有成功；不外推其他方案雲端驗證。詳見操作文件新增章節。

2026-10-14：生成人物時一併建立中文姓名，之後網站與問卷沿用。側欄「網站體驗模擬」支援 BASIC、CUSTOM、PREMIUM；可填三方案人數並預覽人物分配。各方案依權限實際選框色、加入文字或背景貼飾，預設不提交，瀏覽器操作不呼叫 AI；精簡操作紀錄由原本多 Provider 回答引擎使用。

要提交時選「提交設計並核對保存紀錄」、確認測試授權、填測試聯絡資料並儲存，再按執行。平台區分瀏覽器本機保存與雲端接收，會備份設計、保存每步紀錄並阻擋相同人物同設計重送。API 失敗與回答重新生成可重用已完成的網站操作。

**2026-10-14 網站已設定 Supabase，與前一天的本機備援版本不同。** 本輪三個方案的真實預覽及 Mock 答題成功；提交試跑因禁止遠端寫入被攔截，沒有雲端成功紀錄。三方案具姓名提交在本機表單通過；真實雲端接收與付費模型仍未實測。UI 提供唯讀接收網址偵測、明確設定及測試授權；不提交正式 Google 問卷，也沒有修改 ONLYFRAME 網站。

操作說明見 [docs/WEBSITE_WORKFLOW.md](docs/WEBSITE_WORKFLOW.md)。最新測試與全套報告為 `outputs/website-tiers-pytest-results.xml`、`outputs/website-tiers-full-pytest-results.xml`；真實三方案重播證據在 `outputs/website-three-tiers/`。資料庫沿用通用實體表，原資料保留並備份 `backups/before-three-tiers.sqlite3`；先前單方案證據仍在 `outputs/website-mode/`。

## 官方實作參考

以下文件在開發時查閱，廠商能力仍應按所選模型確認：

- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [DeepSeek 官方 API 入口](https://api-docs.deepseek.com/)
- [Gemini generateContent](https://ai.google.dev/api/generate-content)
- [Claude Messages](https://platform.claude.com/docs/en/api/messages/create)
- [Ollama Chat](https://docs.ollama.com/api/chat)
- [Google Forms 官方讀取 API 與授權](https://developers.google.com/workspace/forms/api/guides/retrieve-forms-responses)
- [Google Forms 官方 form schema](https://developers.google.com/workspace/forms/api/reference/rest/v1/forms)
- [Playwright Python 安裝與瀏覽器](https://playwright.dev/python/docs/intro)
- [Streamlit fragment](https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment)
