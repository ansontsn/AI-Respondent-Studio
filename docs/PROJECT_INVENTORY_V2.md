# V2 整合改版：專案盤點與差異分析

依現有程式入口、資料模型、資料庫 DDL、模組與呼叫關係盤點；保留既有架構。新工作台重用人物生成器、AnswerEngine、AnswerValidator、BatchRunner、FormAutomation、SecretStore 和三格式匯出。

## 功能差異

| 項目 | 原有狀態 | 本次整合 |
|---|---|---|
| AI 服務切換、Token、費率與金鑰 | 已有 7 種服務協定及 Mock | 沿用，工作台選擇設定快照 |
| 人物生成、背景條件與分布、編輯 | 已有 | 加入共用多選、全選、搜尋、篩選及持久群組 |
| 問卷解析、版本與跳題 | 已有公開 metadata / DOM、官方 JSON、CSV | 工作台內解析與核對；不默認公開 DOM 完整 |
| 批次答案、獨立驗證、checkpoint | 已有 | 工作台串接，人物生成也保存進度 |
| Playwright 多題型填寫 | 已有單份入口 | 同一 worker 串行批次；保留載入重試及防重送 |
| 全自動工作台、最終報告 | 缺少整合入口 | 新增 WorkbenchService 與整合介面 |
| 15 項側欄導覽 | 操作分散 | 改為 5 項；舊工具移至任務紀錄 |
| 必須先操作 ONLYFRAME 網站 | 只在舊分階段功能存在 | 新工作台沒有這個要求；舊模組保留供舊任務重用 |

## 資料庫

原 schema 以 entities 分別存人物、問卷、模型、表單與實驗；tasks / task_items 保存執行佇列，responses 保留人物、問卷、模型快照，answers 保存題目答案，events、usage、submissions 保存執行及提交證據。

本次 migration 3 → 4 新增 workbench_jobs，沒有刪除舊表、舊欄位或旧紀錄。persona_group 重用 entities。Answer.uncertain、Response.dataset_kind 及 TaskSpec 的填表設定保存在既有 JSON，舊資料缺欄位時採預設值。

```sql
CREATE TABLE answers (
                response_id TEXT NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
                question_id TEXT NOT NULL, value TEXT, rationale TEXT NOT NULL,
                validation TEXT NOT NULL, other_text TEXT NOT NULL DEFAULT '', PRIMARY KEY(response_id,question_id))

CREATE TABLE entities (
                kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY(kind,id))

CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                level TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL)

CREATE TABLE local_receipts (id TEXT PRIMARY KEY,questionnaire_id TEXT NOT NULL,token TEXT NOT NULL,answers TEXT NOT NULL,created_at TEXT NOT NULL, other_text TEXT NOT NULL DEFAULT '{}',UNIQUE(questionnaire_id,token))

CREATE TABLE quality_actions(id TEXT PRIMARY KEY,response_id TEXT NOT NULL,new_task_id TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL)

CREATE TABLE responses (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, persona_id TEXT NOT NULL,
                questionnaire_id TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(task_id,persona_id))

CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)

CREATE TABLE submissions (
                id TEXT PRIMARY KEY, response_id TEXT NOT NULL, target_id TEXT NOT NULL,
                url TEXT NOT NULL, dry_run INTEGER NOT NULL, status TEXT NOT NULL,
                message TEXT NOT NULL, artifact TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)

CREATE TABLE task_items (
                task_id TEXT NOT NULL REFERENCES tasks(id), persona_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '',
                attempts INTEGER NOT NULL DEFAULT 0, checkpoint TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(task_id,persona_id))

CREATE TABLE tasks (
                id TEXT PRIMARY KEY, spec TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)

CREATE TABLE usage (
                id TEXT PRIMARY KEY, config_id TEXT NOT NULL, task_id TEXT NOT NULL,
                provider TEXT NOT NULL, model TEXT NOT NULL, operation TEXT NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER, cost REAL, currency TEXT,
                rate_source TEXT, duration REAL, status TEXT, created_at TEXT NOT NULL)

CREATE TABLE workbench_jobs(id TEXT PRIMARY KEY,spec TEXT NOT NULL,status TEXT NOT NULL,phase TEXT NOT NULL,checkpoint TEXT NOT NULL DEFAULT '{}',error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL)

CREATE TABLE workspace (
                id INTEGER PRIMARY KEY CHECK(id=1), metadata TEXT NOT NULL)
```

## 模組清單與依賴

| 檔案 | 行數 | 類別與函式 | 專案內依賴 |
|---|---:|---|---|
| `survey_sim/__init__.py` | 2 |  |  |
| `survey_sim/analysis.py` | 187 | display_answer, safe_cell, tables, export_csv_zip, export_excel, frames_excel, export_json, distribution, concentration, similarity_matrix | .models, .personas, .security |
| `survey_sim/automation.py` | 325 | launch_browser, browser_session, check_policy, FormNetworkGuard, FormAutomation | .engine, .errors, .models, .security, .validator |
| `survey_sim/batch.py` | 178 | BatchRunner | .automation, .costs, .engine, .errors, .models, .providers, .security, .staged_survey, .validator, .website_experience |
| `survey_sim/cli.py` | 84 | write_examples, main | .analysis, .automation, .engine, .examples, .models, .personas, .providers, .runtime |
| `survey_sim/conditional_personas.py` | 100 | allocate, condition_plan, ConditionalPersonaGenerator, distribution_check | .errors, .persona_names, .personas, .v2_models |
| `survey_sim/costs.py` | 87 | BudgetExceeded, has_rates, request_estimate, task_estimate, usage_summary, BudgetedProvider | .errors, .models |
| `survey_sim/engine.py` | 150 | Interrupted, AnswerEngine | .errors, .mock_ai, .models, .validator, .website_experience |
| `survey_sim/errors.py` | 14 | AppError, ProviderError, AutomationError |  |
| `survey_sim/examples.py` | 51 | opts, onlyframe_example, general_example | .models |
| `survey_sim/experiments.py` | 112 | ExperimentService | .analysis, .errors, .models, .storage, .v2_models, .workflow |
| `survey_sim/google_import.py` | 183 | get, stable_option, apply_routes, parse_public_metadata, parse_official_form | .errors, .models |
| `survey_sim/launcher.py` | 29 | main | .runtime |
| `survey_sim/migrations.py` | 46 | migrate | .errors |
| `survey_sim/mock_ai.py` | 127 | field_value, answer_question, MockProvider | .models, .motivations, .personas, .providers |
| `survey_sim/mock_form.py` | 130 | MockFormServer | .models, .storage, .validator |
| `survey_sim/models.py` | 459 | uid, now, Model, Traits, Background, Behavior, Persona, WebsiteTierChoice, QuestionType, Option, Condition, Binding, Question, Route, Page, ConsistencyRule, Questionnaire, ProviderConfig, Answer, Issue, Scenario, WebsiteWorkflow, WebsitePlan, WebsiteRun, Response, FormTarget, WebsiteSurveyFlow, TaskSpec |  |
| `survey_sim/motivations.py` | 95 | segments, motivation_report | .errors |
| `survey_sim/parsers.py` | 177 | import_json, import_csv, analyze_questionnaire, parse_google_dom, import_google | .automation, .errors, .google_import, .models |
| `survey_sim/persona_names.py` | 34 | is_placeholder, name_for_id, ensure_name | .errors |
| `survey_sim/personas.py` | 220 | validation_details, clamp, mock_background, mock_persona, similarity, PersonaGenerator | .errors, .models, .persona_names |
| `survey_sim/providers.py` | 245 | Completion, Provider, parse_json, HTTPProvider, usage_recorder, make_provider, test_connection | .errors, .mock_ai, .models, .security, .tls |
| `survey_sim/quality.py` | 96 | canonical, quality_report, regenerate | .errors, .models, .validator |
| `survey_sim/questionnaire_review.py` | 51 | review_report, confirm_questionnaire, preview | .errors, .models |
| `survey_sim/reports.py` | 35 | report_tables, report_exports | .analysis, .security |
| `survey_sim/runtime.py` | 56 | Runtime | .batch, .errors, .examples, .mock_form, .models, .security, .storage |
| `survey_sim/security.py` | 113 | register_secret, redact, RedactingFormatter, setup_logging, SecretStore, clean_url, clean_form_url | .errors |
| `survey_sim/staged_survey.py` | 256 | survey_workflow, validate_survey_flow, local_form_available, FormSession, StagedSurveyRunner | .automation, .engine, .errors, .mock_form, .models, .security, .validator, .website_experience |
| `survey_sim/storage.py` | 265 | dump, Database | .automation, .errors, .migrations, .models, .security, .staged_survey, .v2_models, .website_experience |
| `survey_sim/tls.py` | 38 | create_tls_context, certificate_failure | .errors |
| `survey_sim/ui.py` | 99 | runtime, guarded, select_entity, record_table, main | .batch, .errors, .runtime, .security, .storage, .ui_configuration, .ui_operations, .ui_pipeline, .ui_questionnaires, .ui_simple_provider |
| `survey_sim/ui_conditions.py` | 51 | weights_from_text, conditions_editor | .errors, .personas |
| `survey_sim/ui_configuration.py` | 101 | providers_page, settings_page | .errors, .models, .providers, .security, .ui, .ui_results |
| `survey_sim/ui_operations.py` | 184 | progress_view, console_page, automation_page | .automation, .costs, .models, .security, .ui, .ui_people, .ui_staged_survey, .ui_v2_analysis |
| `survey_sim/ui_people.py` | 158 | active_provider, people_page | .conditional_personas, .models, .persona_names, .personas, .providers, .ui, .ui_conditions, .v2_models |
| `survey_sim/ui_pipeline.py` | 297 | people_selector, people_library, form_settings, workbench_page, job_controls, job_progress, history_page | .models, .parsers, .personas, .questionnaire_review, .ui, .ui_conditions, .ui_configuration, .ui_operations, .ui_people, .ui_questionnaires, .ui_results, .ui_v2_analysis, .ui_website, .ui_workbench, .v2_models, .workbench |
| `survey_sim/ui_questionnaires.py` | 259 | options_from_text, save_revision, questionnaires_page | .errors, .models, .parsers, .providers, .questionnaire_review, .ui |
| `survey_sim/ui_results.py` | 150 | export_buttons, review_page, analysis_page | .analysis, .models, .quality, .ui, .ui_website |
| `survey_sim/ui_simple_provider.py` | 38 | simple_providers | .errors, .models, .providers, .ui, .ui_configuration |
| `survey_sim/ui_staged_survey.py` | 126 | guessed_tier, survey_options, prepare_survey_form | .models, .website_experience |
| `survey_sim/ui_v2_analysis.py` | 267 | download_report, choose_task, quality_page, experiment_inputs, experiment_status, view_experiment, model_comparison_page, scenario_page, motivation_page, live_usage, budget_controls | .costs, .errors, .experiments, .models, .motivations, .providers, .quality, .reports, .ui, .ui_operations, .v2_models |
| `survey_sim/ui_website.py` | 217 | show_run, website_page | .models, .ui, .ui_operations, .ui_people, .ui_staged_survey, .website_experience |
| `survey_sim/ui_workbench.py` | 213 | navigate, workbench, current_plan, preview_panel, wizard | .analysis, .errors, .models, .parsers, .personas, .providers, .ui, .ui_operations, .ui_results, .ui_staged_survey, .workflow |
| `survey_sim/v2_models.py` | 116 | AgeBand, PersonaConditions, ExperimentCell, Experiment, PersonaGroup, WorkbenchSpec | .models |
| `survey_sim/validator.py` | 128 | visible, value_errors, AnswerValidator | .mock_ai, .models |
| `survey_sim/website_experience.py` | 496 | SubmissionBlocked, release_blocked_submission, detect_submission_endpoint, check_workflow, make_plan, workflow_for_person, assign_tiers, submission_key, compact_facts, WebsiteExperience, require_usable, compact_payload, factual_values, website_test_questionnaire, staged_test_questionnaire | .automation, .engine, .errors, .models, .security, .tls, .validator |
| `survey_sim/workbench.py` | 289 | WorkbenchService | .analysis, .automation, .conditional_personas, .errors, .models, .persona_names, .personas, .providers, .reports, .security, .storage, .v2_models, .validator |
| `survey_sim/workflow.py` | 34 | provider_ready, fingerprint, validated_plan | .errors, .models, .storage |

## 主要風險與處理

- 既有資料與設定：遷移先備份，欄位使用預設值；部署前後逐筆核對原紀錄。
- Streamlit 新舊類別：偵測版本差異；在 worker 空閒時更新 cached database / runner，保留 SecretStore。
- 頁面重新整理：按鈕僅啟動一次，完成狀態、人物及 task IDs 在 SQLite；恢復時跳過完成工作。
- 提交逾時：unknown 仍禁止重送；僅提交前的載入暫時錯誤可有限退避。
- 正式研究問卷：reference / research 類型在 backend 阻擋自動填表；真正提交需本次確認及表單授權。
- 自然語言邏輯：驗證器檢查格式、跳題、人設註記及已設定跨題規則，無法證明所有語意都正確；不確定與 review 需人工核對。

## 依賴版本

本次不新增套件。

```text
# Primary versions actually verified on Windows / Python 3.12.
streamlit==1.65.0
pydantic==2.14.1
pandas==2.3.3
plotly==6.9.0
playwright==1.63.0
python-dotenv==1.2.4
httpx==0.28.1
openpyxl==3.1.5
beautifulsoup4==4.15.0
pytest==9.1.1
keyring==25.7.0

```
