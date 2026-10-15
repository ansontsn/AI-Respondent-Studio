"""Live preview by default. --local-submit verifies ONLYFRAME's browser-local fallback.
Remote writes remain blocked; no form submission or paid AI call is performed.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from survey_sim.models import Persona, WebsiteWorkflow, TaskSpec
from survey_sim.storage import Database
from survey_sim.website_experience import WebsiteExperience, website_test_questionnaire, TEST_BINDINGS
from survey_sim.engine import AnswerEngine
from survey_sim.models import ProviderConfig
from survey_sim.providers import make_provider


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-submit", action="store_true", help="Verify isolated browser-local save; all remote POST writes remain blocked")
    args = parser.parse_args()
    if args.local_submit:
        from survey_sim.website_experience import detect_submission_endpoint
        if detect_submission_endpoint(WebsiteWorkflow()):
            raise SystemExit('公開網站已設定雲端後端，此腳本只驗證預覽與本機備援；請從 UI 核對雲端接收設定及測試授權。')
    folder = ROOT / "outputs/website-mode"
    folder.mkdir(parents=True, exist_ok=True)
    db = Database(folder / "verification.sqlite3")
    source_persona = ROOT / "outputs/website-pilot/live-pilot/persona.json"
    if source_persona.exists():
        persona = Persona.model_validate_json(source_persona.read_text(encoding="utf-8"))
    else:
        from survey_sim.personas import PersonaGenerator
        persona = PersonaGenerator(make_provider(ProviderConfig())).generate_one(7001, "高度興趣型", "ONLYFRAME 小卡框")
    workflow = WebsiteWorkflow(name="ONLYFRAME 重播驗證", plan_mode="recorded", mode="submit" if args.local_submit else "preview",
                               authorized_test=args.local_submit, contact_name="AI 平台功能測試", contact_email="ai-test@example.invalid")
    db.save("website_workflow", workflow);db.save("persona", persona)
    run = WebsiteExperience(db, folder / "runs").run(workflow, persona)
    q = website_test_questionnaire();q.confirmed=True
    spec = TaskSpec(questionnaire=q, personas=[persona], provider=ProviderConfig(),
                    website_workflow=workflow, compact_context=True, website_fact_bindings=TEST_BINDINGS)
    id = db.create_task(spec)
    metrics = {"requests":0,"input_characters":0,"output_characters":0}
    provider = make_provider(spec.provider)
    class Counter:
        def generate(self, operation, payload, system):
            metrics["requests"] += 1
            metrics["input_characters"] += len(json.dumps(payload, ensure_ascii=False)) + len(system)
            result = provider.generate(operation, payload, system)
            metrics["output_characters"] += len(json.dumps(result.data, ensure_ascii=False))
            return result
    response = AnswerEngine(Counter()).run(id, spec, persona, {"website_run":run.model_dump(mode="json")})
    db.save_response(response)
    report = {"source":"AI 網站功能測試", "workflow":workflow.model_dump(), "website_status":run.status,
        "website_run_id":run.id,"receipt_code":run.receipt_code,"receipt_id":run.receipt_id,"screenshots":run.screenshots,
        "elapsed_seconds":run.elapsed_seconds,"blocked_writes":run.blocked_writes,"answer_status":response.status,
        "answer_count":len(response.answers),"provider":"mock","paid_api_requests":0,"token_usage":None,
        "payload_measurements":metrics,"measurement_note":"字數不是 Token；Mock 不呼叫外部模型，不能推算真實模型品質或實際付費 Token。",
        "unverified":["真實 AI API Token／費用", "雲端 ONLYFRAME 接收 API", "BASIC／PREMIUM 操作"]}
    filename = "live-local-submit.json" if args.local_submit else "live-preview.json"
    (folder / filename).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:report[k] for k in ["website_status","receipt_code","elapsed_seconds","answer_status","answer_count","paid_api_requests","payload_measurements"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
