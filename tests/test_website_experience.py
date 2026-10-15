from conftest import navigate
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from survey_sim.analysis import export_json, export_csv_zip, export_excel
from survey_sim.batch import BatchRunner
from survey_sim.engine import AnswerEngine
from survey_sim.errors import AutomationError, ProviderError
from survey_sim.models import TaskSpec, WebsiteWorkflow, WebsiteRun
from survey_sim.providers import make_provider
from survey_sim.security import SecretStore
from survey_sim.website_experience import (WebsiteExperience, make_plan, check_workflow,
    require_usable, compact_facts, website_test_questionnaire, TEST_BINDINGS)


HTML = '''<!DOCTYPE html><meta charset="utf-8"><body><button onclick="start()">開始設計</button>
<script>
const body=document.body;let color='',font='',txt='';
function start(){body.innerHTML='<button onclick="editor()">選擇此方案 (CUSTOM)</button>'}
function editor(){body.innerHTML=`<h1>CUSTOM｜文字客製</h1>
<button onclick="color='冰川冷藍'">冰川冷藍</button><button>客製文字</button>
<label>文字內容<input id="text" oninput="txt=this.value"></label>
<button onclick="document.querySelector('[type=range]').value=99">底部中央銘牌</button>
<button onclick="font='韓系潮流'">韓系潮流</button>
<label>文字垂直位置<input type="range" min="0" max="115" step="0.5" value="99"></label>
<button title="曜石黑">文字色</button><button onclick="preview()">成品預覽</button>`}
function preview(){body.innerHTML='<button onclick="finished()">完成設計 ‧ 查看成品</button>'}
function finished(){body.innerHTML=`<h1>設計已完成 · DESIGN COMPLETED</h1>CUSTOM ${txt}
<button onclick="dialog()">送出我的專屬設計 ➔</button>`}
function dialog(){body.innerHTML+=`<form onsubmit="event.preventDefault();sendDesign()">
<input placeholder="例如：王小明"><input type="email" placeholder="例如：student@university.edu.tw">
<button type="submit">確認送出設計 ➔</button></form>`}
async function sendDesign(){
let r={id:'receipt-1',submission_code:'DES-20261013-1234',plan:'CUSTOM',custom_text:txt,
customer_name:document.querySelector('form input').value,customer_email:document.querySelector('[type=email]').value};
if(location.search.includes('cloud')){let result=await fetch('/rest/v1/design_submissions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify([r])});r=(await result.json())[0]}
else if(!location.search.includes('unknown'))localStorage.setItem('onlyframe_mock_submissions',JSON.stringify([r]));
body.innerHTML='<h1>你的設計已成功送出！</h1><p>OFFICIAL SUBMISSION CODE</p><b>DES-20261013-1234</b>';
}
</script></body>'''


@pytest.fixture
def site():
    state = {"posts": [], "mode": "local"}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            content = HTML
            if state["mode"] in {"cloud", "minimal", "rejected"}:
                content = content.replace("location.search.includes('cloud')", "true")
            if state["mode"] == "minimal":
                content = content.replace("r=(await result.json())[0]", "if(!result.ok)throw new Error('insert failed')")
            if state["mode"] == "rejected":
                content = content.replace("r=(await result.json())[0]", "if(!result.ok){alert('insert rejected');return;}")
            if state["mode"] == "unknown":
                content = content.replace("!location.search.includes('unknown')", "false")
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
            self.wfile.write(content.encode())
        def do_POST(self):
            rows=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['posts'].append(rows)
            if state['mode']=='minimal':
                self.send_response(state.get('success_status',204));self.send_header('Preference-Applied','return=minimal');self.end_headers();return
            if state['mode']=='rejected':
                self.send_response(403);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(b'{"message":"insert permission denied"}');return
            self.send_response(201);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps(rows).encode())
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    state['url']=f'http://127.0.0.1:{server.server_port}/'
    yield state
    server.shutdown();server.server_close();thread.join()


def workflow(site, **kwargs):
    return WebsiteWorkflow(url=site['url'], allowlist=[site['url']], plan_mode='recorded',timeout_seconds=3,**kwargs)


def test_policy_and_reproducible_persona_plans(persona):
    w=WebsiteWorkflow()
    assert make_plan(w,persona,100)==make_plan(w,persona,100)
    assert w.mode=='preview' and not w.authorized_test
    for bad in [WebsiteWorkflow(url='https://example.com/'), WebsiteWorkflow(mode='submit'),
        WebsiteWorkflow(mode='submit',authorized_test=True,contact_email='bad'),
        WebsiteWorkflow(submission_endpoint='https://example.com/rest/v1/design_submissions'),
        WebsiteWorkflow(require_server_receipt=True)]:
        with pytest.raises(AutomationError):check_workflow(bad)


def test_browser_preview_never_submits(db,persona,site):
    run=WebsiteExperience(db).run(workflow(site),persona)
    assert run.status=='preview_completed' and not run.submission_started
    assert len(run.screenshots)==2 and not site['posts']
    assert not db.rows("SELECT * FROM entities WHERE kind='website_submit_guard'")


def test_preview_blocks_unsolicited_writes(db,persona,site):
    global HTML
    original = HTML
    try:
        HTML = original.replace('const body=document.body;', "fetch('/rest/v1/design_submissions',{method:'POST',body:'[]'}).catch(()=>{});const body=document.body;")
        run=WebsiteExperience(db).run(workflow(site),persona)
    finally:
        HTML = original
    assert run.status=='preview_completed' and run.blocked_writes==1 and not site['posts']


def test_changed_page_saves_failure_without_submitting(db,persona,site):
    global HTML
    original = HTML
    try:
        HTML = original.replace('button>客製文字', 'button>changed-text-control')
        with pytest.raises(AutomationError):WebsiteExperience(db).run(workflow(site),persona)
    finally:
        HTML = original
    run=db.list('website_run')[0]
    assert run.status=='failed' and not run.submission_started and run.steps[-1]=='選擇框色：冰川冷藍'


def test_pause_stops_before_submission_and_preserves_steps(db,persona,site):
    from survey_sim.engine import Interrupted
    checks=[]
    def continue_running():
        checks.append(1)
        return len(checks)<4
    with pytest.raises(Interrupted):
        WebsiteExperience(db).run(workflow(site,mode='submit',authorized_test=True),persona,should_continue=continue_running)
    run=db.list('website_run')[0]
    assert run.status=='interrupted' and len(run.steps)==3 and not site['posts']


def test_regenerate_answers_reuses_submission_snapshot(db,persona,config):
    from survey_sim.quality import regenerate
    q=website_test_questionnaire();q.confirmed=True;w=WebsiteWorkflow(mode='submit',authorized_test=True)
    run=WebsiteRun(workflow_id=w.id,persona_id=persona.id,url=w.url,plan=make_plan(w,persona),mode='submit',status='local_saved',submission_started=True,receipt_code='DES-20261013-1234')
    spec=TaskSpec(questionnaire=q,personas=[persona],provider=config,website_workflow=w,website_fact_bindings=TEST_BINDINGS,interval_seconds=0)
    id=db.create_task(spec);response=AnswerEngine(make_provider(config)).run(id,spec,persona,{'website_run':run.model_dump()});db.save_response(response)
    second=regenerate(db,[response.id])
    runner=BatchRunner(db,SecretStore());runner.start(second);runner.thread.join(10)
    assert db.responses(second)[0].website_run==run
    assert not db.rows("SELECT * FROM entities WHERE kind='website_submit_guard'")


def test_browser_local_submission_is_backed_up_and_duplicate_blocked(db,persona,site):
    w=workflow(site,mode='submit',authorized_test=True)
    service=WebsiteExperience(db)
    run=service.run(w,persona)
    assert run.status=='local_saved' and run.receipt_code=='DES-20261013-1234'
    assert json.loads(open(run.receipt_file,encoding='utf-8').read())['custom_text']=='MUSIC 2026'
    assert not site['posts']
    from survey_sim.storage import Database
    with pytest.raises(AutomationError,match='已嘗試提交'):
        WebsiteExperience(Database(db.path)).run(w,persona)
    assert len(db.rows("SELECT * FROM entities WHERE kind='website_submit_guard'"))==1


def test_browser_cloud_receipt_requires_matching_backend_record(db,persona,site):
    site['mode']='cloud'
    w=workflow(site,mode='submit',authorized_test=True,submission_endpoint=site['url']+'rest/v1/design_submissions',require_server_receipt=True)
    run=WebsiteExperience(db).run(w,persona)
    assert run.status=='server_confirmed' and len(site['posts'])==1
    require_usable(run,w)


@pytest.mark.parametrize('status',[201,204])
def test_cloud_minimal_success_matches_sent_record_and_screen(db,persona,site,status):
    site['mode']='minimal'
    site['success_status']=status
    w=workflow(site,mode='submit',authorized_test=True,submission_endpoint=site['url']+'rest/v1/design_submissions')
    run=WebsiteExperience(db).run(w,persona)
    assert run.status=='server_confirmed' and run.receipt_source=='insert_http_ack'
    assert run.insert_sent is True and run.receipt_code=='DES-20261013-1234'
    assert any(e.get('status')==status for e in run.network_events)
    assert len(site['posts'])==1


def test_cloud_alphanumeric_receipt_matches_actual_sent_record(db,persona,site):
    global HTML
    original=HTML
    site['mode']='minimal';site['success_status']=201
    HTML=original.replace('DES-20261013-1234','DES-20261013-D386853890A7')
    try:
        w=workflow(site,mode='submit',authorized_test=True,submission_endpoint=site['url']+'rest/v1/design_submissions')
        run=WebsiteExperience(db).run(w,persona)
    finally:HTML=original
    assert run.status=='server_confirmed' and run.receipt_code=='DES-20261013-D386853890A7'
    assert run.receipt_source=='insert_http_ack' and len(site['posts'])==1


def test_missing_backend_blocks_before_submit_without_reservation(db,persona,site,monkeypatch):
    from survey_sim.website_experience import SubmissionBlocked
    monkeypatch.setattr('survey_sim.website_experience.detect_submission_endpoint',lambda w:site['url']+'rest/v1/design_submissions')
    with pytest.raises(SubmissionBlocked,match='尚未設定'):
        WebsiteExperience(db).run(workflow(site,mode='submit',authorized_test=True),persona)
    run=db.list('website_run')[0]
    assert run.status=='blocked' and run.insert_sent is False and not run.submission_started
    assert not db.rows("SELECT * FROM entities WHERE kind='website_submit_guard'") and not site['posts']


def test_cloud_permission_error_is_not_success_and_never_unlocked(db,persona,site):
    from survey_sim.website_experience import release_blocked_submission
    site['mode']='rejected'
    with pytest.raises(AutomationError,match='HTTP 403'):
        WebsiteExperience(db).run(workflow(site,mode='submit',authorized_test=True,submission_endpoint=site['url']+'rest/v1/design_submissions'),persona)
    run=db.list('website_run')[0]
    assert run.status=='unknown' and run.insert_sent is True
    with pytest.raises(AutomationError,match='未送出'):release_blocked_submission(db,run.id)


def test_blocked_guard_unlock_preserves_history_and_checks_owner(db,persona):
    from survey_sim.website_experience import release_blocked_submission,submission_key
    w=WebsiteWorkflow()
    run=WebsiteRun(workflow_id=w.id,persona_id=persona.id,url=w.url,plan=make_plan(w,persona),mode='submit',status='blocked',insert_sent=False)
    db.save('website_run',run)
    key=submission_key(w.url,persona.id,run.plan)
    db.execute("INSERT INTO entities VALUES('website_submit_guard',?,?,?)",(key,json.dumps({'run_id':run.id}),run.created_at))
    release_blocked_submission(db,run.id)
    assert not db.rows("SELECT * FROM entities WHERE kind='website_submit_guard'")
    assert db.get('website_run',run.id).network_events[-1]['kind']=='retry_unlocked'
    db.execute("INSERT INTO entities VALUES('website_submit_guard',?,?,?)",(key,json.dumps({'run_id':'another-run'}),run.created_at))
    with pytest.raises(AutomationError,match='其他提交'):release_blocked_submission(db,run.id)


def test_unlock_clears_only_matching_nonrunning_checkpoint(db,spec,persona):
    from survey_sim.website_experience import release_blocked_submission
    w=WebsiteWorkflow()
    run=WebsiteRun(workflow_id=w.id,persona_id=persona.id,url=w.url,plan=make_plan(w,persona),mode='submit',status='blocked',insert_sent=False)
    db.save('website_run',run);task=db.create_task(spec)
    db.checkpoint(task,persona.id,{'website_run':run.model_dump(),'answers':[],'visited':['preserved-page']})
    release_blocked_submission(db,run.id)
    checkpoint=json.loads(db.rows('SELECT checkpoint FROM task_items WHERE task_id=?',(task,))[0]['checkpoint'])
    assert checkpoint=={'answers':[],'visited':['preserved-page']}


def test_success_screen_without_receipt_is_unknown_and_never_resent(db,persona,site):
    site['mode']='unknown';w=workflow(site,mode='submit',authorized_test=True)
    with pytest.raises(AutomationError,match='尚無相符'):
        WebsiteExperience(db).run(w,persona)
    run=db.list('website_run')[0]
    assert run.status=='unknown' and run.submission_started
    with pytest.raises(AutomationError,match='已嘗試提交'):
        WebsiteExperience(db).run(w,persona)


def test_server_requirement_rejects_local_save(persona):
    w=WebsiteWorkflow(mode='submit',authorized_test=True,submission_endpoint='https://testing.supabase.co/rest/v1/design_submissions',require_server_receipt=True)
    run=WebsiteRun(workflow_id=w.id,persona_id=persona.id,url=w.url,plan=make_plan(w,persona),mode='submit',status='local_saved',submission_started=True)
    with pytest.raises(AutomationError,match='尚無雲端'):require_usable(run,w)


@pytest.mark.parametrize('tier',['BASIC','CUSTOM','PREMIUM'])
def test_each_tier_submits_generated_persona_name_and_allowed_features(db,persona,site,tier):
    global HTML
    original=HTML
    enhanced=original.replace("let color='',font='',txt='';", "let color='',font='',txt='',chosenTier='CUSTOM',bg='';")
    enhanced=enhanced.replace("function start(){body.innerHTML='<button onclick=\"editor()\">選擇此方案 (CUSTOM)</button>'}",
        "function start(){body.innerHTML='<button onclick=\"selectTier(\\\'BASIC\\\')\">選擇此方案 (BASIC)</button><button onclick=\"selectTier(\\\'CUSTOM\\\')\">選擇此方案 (CUSTOM)</button><button onclick=\"selectTier(\\\'PREMIUM\\\')\">選擇此方案 (PREMIUM)</button>'} function selectTier(t){if(t==='BASIC'&&!confirm('切換至 BASIC｜簡易客製 將移除文字，確定切換方案嗎？'))return;chosenTier=t;editor();}")
    enhanced=enhanced.replace('<h1>CUSTOM｜文字客製</h1>','<h1>${chosenTier}｜方案</h1>')
    enhanced=enhanced.replace('<button title="曜石黑">文字色</button>',
        '<button title="曜石黑">文字色</button><button>主題背景</button><button onclick="bg=\'晨光微曦漸層\'">晨光微曦漸層</button><button>裝飾貼飾</button><button aria-label="加入水晶四芒星" onclick="this.innerText=\'1 枚\'">貼飾</button>')
    enhanced=enhanced.replace('CUSTOM ${txt}', '${chosenTier} ${txt} ${bg}')
    enhanced=enhanced.replace("plan:'CUSTOM',custom_text:txt", "plan:chosenTier,custom_text:txt||'(未設定文字)'")
    HTML=enhanced
    try:
        run=WebsiteExperience(db).run(workflow(site,tier=tier,mode='submit',authorized_test=True),persona)
    finally:HTML=original
    assert run.status=='local_saved' and run.plan.tier==tier
    receipt=json.loads(open(run.receipt_file,encoding='utf-8').read())
    assert receipt['customer_name']==persona.name and receipt['plan']==tier
    assert run.contact_name==persona.name and run.persona_name==persona.name
    if tier=='BASIC':assert not run.plan.text and '開啟客製文字' not in run.steps
    if tier=='PREMIUM':assert '加入貼飾：水晶四芒星' in run.steps and run.plan.background


def test_answering_uses_facts_compact_payload_and_exports(db,persona,config):
    q=website_test_questionnaire();q.confirmed=True;w=WebsiteWorkflow()
    run=WebsiteRun(workflow_id=w.id,persona_id=persona.id,url=w.url,plan=make_plan(w,persona),mode='preview',status='preview_completed')
    spec=TaskSpec(questionnaire=q,personas=[persona],provider=config,website_workflow=w,compact_context=True,website_fact_bindings=TEST_BINDINGS)
    id=db.create_task(spec);observed=[];provider=make_provider(config)
    class Spy:
        def generate(self,operation,payload,instruction):
            observed.append(payload)
            return provider.generate(operation,payload,instruction)
    result=AnswerEngine(Spy()).run(id,spec,persona,{'website_run':run.model_dump()})
    assert result.status=='passed' and result.website_run==run
    answers={a.question_id:a.value for a in result.answers}
    assert answers['site_storage']=='preview_completed' and answers['site_features']==['frame','text']
    assert len(observed)==1 and observed[0]['website_experience']==compact_facts(run)
    assert 'import_diagnostics' not in observed[0]['questionnaire']
    assert 'binding' not in observed[0]['page']['questions'][0]
    db.save_response(result);db.save('website_run',run)
    for exported in [export_json(db,id),export_csv_zip(db,id),export_excel(db,id)]:assert exported


def test_failed_ai_resume_reuses_browser_checkpoint(db,persona,config,monkeypatch):
    q=website_test_questionnaire();q.confirmed=True;w=WebsiteWorkflow()
    spec=TaskSpec(questionnaire=q,personas=[persona],provider=config,website_workflow=w,website_fact_bindings=TEST_BINDINGS,interval_seconds=0)
    calls=[]
    def fake_run(self,w,p,seed,keep,on_saved):
        calls.append(p.id)
        run=WebsiteRun(workflow_id=w.id,persona_id=p.id,url=w.url,plan=make_plan(w,p),mode='preview',status='preview_completed')
        self.db.save('website_run',run);on_saved(run);return run
    monkeypatch.setattr(WebsiteExperience,'run',fake_run)
    original=AnswerEngine.run
    monkeypatch.setattr(AnswerEngine,'run',lambda *args,**kwargs: (_ for _ in ()).throw(ProviderError('額度不足',kind='quota')))
    runner=BatchRunner(db,SecretStore());id=db.create_task(spec);runner.start(id);runner.thread.join(10)
    assert db.task(id)['status']=='completed_with_errors' and len(calls)==1
    checkpoint=json.loads(db.rows('SELECT checkpoint FROM task_items WHERE task_id=?',(id,))[0]['checkpoint'])
    assert checkpoint['website_run']['status']=='preview_completed'
    monkeypatch.setattr(AnswerEngine,'run',original)
    db.retry_failed(id);runner.start(id);runner.thread.join(10)
    assert db.task(id)['status']=='completed' and len(calls)==1 and len(db.responses(id))==1


def test_reference_questionnaire_is_not_a_research_execution(db,spec):
    spec.website_workflow=WebsiteWorkflow();spec.website_fact_bindings={'missing':'tier'}
    with pytest.raises(Exception,match='不存在的題目 ID'):db.create_task(spec)
    spec.website_fact_bindings={}
    spec.website_workflow=WebsiteWorkflow();spec.questionnaire.purpose='reference'
    with pytest.raises(Exception,match='獨立測試問卷'):db.create_task(spec)


def test_ui_website_page_saves_flow_and_separate_questionnaire(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from survey_sim.ui import runtime
    monkeypatch.setenv('APP_DATA_DIR',str(tmp_path/'ui'));runtime.clear()
    app=AppTest.from_file(Path.cwd()/'app.py',default_timeout=30).run()
    navigate(app, '網站體驗模擬')
    assert not app.exception and not app.error
    next(b for b in app.button if b.label=='儲存網站流程').click().run()
    rt=runtime();w=rt.db.list('website_workflow')[0]
    next(s for s in app.selectbox if s.label=='網站操作設定').set_value(w.id).run()
    next(b for b in app.button if b.label=='建立獨立的網站操作測試問卷').click().run()
    assert not app.exception and not app.error
    assert not rt.db.get('questionnaire','onlyframe-website-test-v2').confirmed
    assert w.mode=='preview' and not rt.db.responses()
    runtime.clear()
