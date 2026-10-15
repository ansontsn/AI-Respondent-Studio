"""Three named personas, real ONLYFRAME UI, Mock answers, no remote POST."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from survey_sim.models import ProviderConfig, WebsiteWorkflow, TaskSpec
from survey_sim.personas import PersonaGenerator
from survey_sim.providers import make_provider
from survey_sim.storage import Database
from survey_sim.batch import BatchRunner
from survey_sim.security import SecretStore
from survey_sim.website_experience import TIERS, assign_tiers, website_test_questionnaire, TEST_BINDINGS, detect_submission_endpoint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--local-submit',action='store_true')
    args=parser.parse_args()
    if args.local_submit and detect_submission_endpoint(WebsiteWorkflow()):
        raise SystemExit('網站目前已設定雲端後端；此驗證腳本不允許遠端寫入。請從 UI 核對接收位置與測試授權後操作，不會自動重試之前狀態不明的提交。')
    folder=ROOT/'outputs/website-three-tiers';folder.mkdir(parents=True,exist_ok=True)
    db=Database(folder/'verification.sqlite3')
    config=ProviderConfig(id='mock-three-tiers')
    people=PersonaGenerator(make_provider(config)).generate_batch(3,14330,'ONLYFRAME 三方案測試',{'價格敏感型':1,'品質導向型':1,'高度興趣型':1})
    q=website_test_questionnaire();q.confirmed=True
    workflow=WebsiteWorkflow(id='three-tiers-test',name='ONLYFRAME 三方案驗證',plan_mode='recorded',
                            mode='submit' if args.local_submit else 'preview',authorized_test=args.local_submit)
    for p in people:db.save('persona',p)
    db.save('questionnaire',q);db.save('website_workflow',workflow)
    allocation=assign_tiers(people,dict.fromkeys(TIERS,1),42)
    spec=TaskSpec(questionnaire=q,personas=people,provider=config,website_workflow=workflow,
        website_tier_assignments=allocation,website_fact_bindings=TEST_BINDINGS,compact_context=True,interval_seconds=0)
    task=db.create_task(spec)
    runner=BatchRunner(db,SecretStore());runner.start(task);runner.thread.join(timeout=240)
    results=db.responses(task)
    rows=[{'姓名':r.persona_snapshot.name,'人物ID':r.persona_id,'方案':r.website_run.plan.tier,
           '網站狀態':r.website_run.status,'設計編號':r.website_run.receipt_code,'提交姓名':r.website_run.contact_name,
           '回答狀態':r.status,'回答數':len(r.answers),'秒數':r.website_run.elapsed_seconds,'紀錄ID':r.website_run.id,
           '功能':next(a.value for a in r.answers if a.question_id=='site_features')} for r in results]
    errors=db.rows("SELECT persona_id,status,error FROM task_items WHERE task_id=? AND status!='completed'",(task,))
    report={'date':'2026-10-14','source':'AI 測試工作區','task_id':task,'mode':workflow.mode,
        'results':rows,'errors':errors,'paid_ai_calls':0,'remote_design_posts':0,
        'notes':['真實 ONLYFRAME 瀏覽器操作，問卷為獨立 8 題 Mock 測試，未送出 Google 問卷','local_saved 僅證明瀏覽器本機保存與平台備份，未實測雲端接收']}
    (folder/('live-submit.json' if args.local_submit else 'live-preview.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    if runner.thread.is_alive() or errors or len(results)!=3:raise SystemExit(1)


if __name__=='__main__':main()
