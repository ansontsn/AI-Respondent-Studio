from conftest import navigate
import copy
import html
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest

from survey_sim.automation import FormAutomation, FormNetworkGuard, browser_session, check_policy
from survey_sim.engine import AnswerEngine
from survey_sim.errors import AppError, AutomationError
from survey_sim.mock_ai import MockProvider
from survey_sim.models import FormTarget, Page, Question, QuestionType, Option, Questionnaire, TaskSpec, WebsiteSurveyFlow, WebsiteWorkflow, WebsiteRun


@pytest.mark.browser
def test_all_eleven_real_google_headings_match_without_aria_required_label(tmp_path):
    folder = Path(__file__).parent / 'fixtures'
    qpage = Page.model_validate(json.loads((folder / 'google_first_page_questions_20261014.json').read_text(encoding='utf-8'))['page'])
    with browser_session() as browser:
        page = browser.new_page()
        page.route('**/*', lambda route: route.abort())
        page.set_content((folder / 'google_first_page_20261014.html').read_text(encoding='utf-8'))
        automation = FormAutomation(None, tmp_path)
        assert len(qpage.questions) == 11
        for question in qpage.questions:
            box = automation._container(page, question, 'google')
            assert box.count() == 1 and box.is_visible(), question.id
        first = qpage.questions[0]
        # The old accessible-name matcher omitted the required aria-label.
        assert not page.get_by_role('heading', name=first.title + ' *', exact=True).count()


@pytest.mark.browser
def test_heading_whitespace_duplicate_titles_and_explicit_mapping(tmp_path):
    q = Question(id='Q', title='  請選擇\n使用方案  ', type=QuestionType.SHORT)
    with browser_session() as browser:
        page = browser.new_page()
        page.set_content('<div role="listitem"><div role="heading">請選擇<br>使用方案<span aria-label="required"> *</span></div><input></div>')
        automation = FormAutomation(None, tmp_path)
        assert automation._container(page, q, 'google').count() == 1
        automation._fill(page, q, '測試', 'google')
        page.set_content('<div role="listitem" id="one"><div role="heading">請選擇使用方案 *</div><input></div><div role="listitem"><div role="heading">請選擇使用方案 *</div><input></div>')
        with pytest.raises(AutomationError, match='無法唯一對應'):
            automation._fill(page, q, '測試', 'google')
        q.binding.container_selector = '#one'
        automation._fill(page, q, '測試', 'google')
        assert page.locator('#one input').input_value() == '測試'


def stub_route(page, url, data='', method='POST', navigation=True):
    request = SimpleNamespace(url=url, post_data=data, method=method, frame=page.main_frame,
                              is_navigation_request=lambda: navigation)
    route = SimpleNamespace(request=request, result=None)
    route.abort = lambda: setattr(route, 'result', 'blocked')
    route.continue_ = lambda: setattr(route, 'result', 'allowed')
    return route


@pytest.mark.parametrize('data,arm,authorized,expected', [
    ('continue=1&pageHistory=0', True, True, 'allowed'),
    ('continue=1&pageHistory=0', False, True, 'blocked'),
    ('continue=1&pageHistory=0', True, False, 'blocked'),
    ('submit=1&pageHistory=0', True, True, 'blocked'),
    ('continue=1&submit=1', True, True, 'blocked'),
    ('continue=1&continue=1', True, True, 'blocked'),
    ('continue=0', True, True, 'blocked'),
])
def test_continue_post_is_distinct_from_final_submit(data, arm, authorized, expected):
    url = 'https://docs.google.com/forms/d/e/LOCAL_TEST/viewform'
    page = SimpleNamespace(main_frame=object())
    target = FormTarget(name='測試',url=url,questionnaire_id='Q',kind='google',authorized=authorized)
    guard = FormNetworkGuard(page,target,url); guard.allow_next = arm
    route = stub_route(page,url.replace('/viewform','/formResponse'),data)
    guard(route)
    assert route.result == expected and guard.submission_posts == 0
    if expected == 'allowed':
        assert guard.navigation_posts == 1 and not guard.allow_next
        second = stub_route(page,route.request.url,data); guard(second)
        assert second.result == 'blocked'


def test_submit_is_allowed_only_after_final_click_and_only_once():
    url = 'https://docs.google.com/forms/d/e/LOCAL_TEST/viewform'
    page = SimpleNamespace(main_frame=object())
    guard = FormNetworkGuard(page,FormTarget(name='測試',url=url,questionnaire_id='Q',kind='google',authorized=True),url)
    endpoint = url.replace('/viewform','/formResponse')
    first = stub_route(page,endpoint,'submit=1'); guard(first)
    assert first.result == 'blocked'
    guard.allow_submit = True
    second = stub_route(page,endpoint,'submit=1'); guard(second)
    assert second.result == 'allowed' and guard.submission_posts == 1
    third = stub_route(page,endpoint,'submit=1'); guard(third)
    assert third.result == 'blocked'
    wrong = stub_route(page,endpoint.replace('LOCAL_TEST','OTHER'),'continue=1');guard.allow_next=True;guard(wrong)
    assert wrong.result == 'blocked'


def test_multi_page_google_dryrun_requires_existing_test_authorization(saved_response):
    target = FormTarget(name='測試',url='https://docs.google.com/forms/d/e/LOCAL_TEST/viewform',questionnaire_id=saved_response.questionnaire_id,kind='google')
    with pytest.raises(AppError, match='翻頁會傳送當頁答案'):
        check_policy(target,saved_response,[target.url],dry_run=True)


@pytest.fixture
def google_like_server():
    state = {'navigation_posts':0,'submission_posts':0,'values':{}}
    titles = ['操作前偏好', '體驗後方案', '最後的意見']
    def render(index):
        title = titles[index]
        if index < 2:
            control = f'''<input type="hidden" name="entry.Q{index+1}" id="answer" value="">
            <div role="radio" tabindex="0" aria-label="是" aria-checked="false" onclick="this.setAttribute('aria-checked','true');document.querySelector('#answer').value='yes'">是</div>'''
        else:
            control = '<input type="text" name="entry.Q3">'
        button = '<button name="continue" value="1">繼續</button>' if index < 2 else '<button name="submit" value="1">送出</button>'
        return f'''<!doctype html><meta charset="utf-8"><form method="POST" action="/forms/d/e/LOCAL_TEST/formResponse">
        <input type="hidden" name="pageHistory" value="{index}">
        <div role="listitem"><div role="heading"><span>{title}</span><span aria-label="將這個問題設為必填"> *</span></div>{control}</div>{button}</form>'''
    class Handler(BaseHTTPRequestHandler):
        def send_html(self, content):
            self.send_response(200);self.send_header('Content-Type','text/html;charset=utf-8');self.end_headers();self.wfile.write(content.encode())
        def do_GET(self): self.send_html(render(0))
        def do_POST(self):
            fields = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode(),keep_blank_values=True)
            state['values'].update({key:value[0] for key,value in fields.items() if key.startswith('entry.')})
            if fields.get('continue') == ['1']:
                state['navigation_posts'] += 1
                self.send_html(render(int(fields['pageHistory'][0])+1))
            else:
                state['submission_posts'] += 1
                self.send_html('<div id="success">本機測試收件成功</div>')
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    state['url']=f'http://127.0.0.1:{server.server_port}/forms/d/e/LOCAL_TEST/viewform'
    yield state
    server.shutdown();server.server_close();thread.join()


@pytest.mark.browser
def test_google_like_actual_post_navigation_reaches_last_page_without_submission(db, persona, config, google_like_server, tmp_path, monkeypatch):
    from survey_sim import automation as module
    # Only the Google host check is substituted for this strictly local replica.
    original = module.check_policy
    monkeypatch.setattr(module,'check_policy',lambda target,response,allowlist,dry_run: original(target.model_copy(update={'kind':'custom'}),response,allowlist,dry_run))
    q=Questionnaire(id='google-like',title='本機 Google 結構複現',confirmed=True,pages=[
        Page(id='P1',title='前段',questions=[Question(id='Q1',title='操作前偏好',type=QuestionType.SINGLE,options=[Option(id='yes',label='是')])]),
        Page(id='P2',title='體驗',questions=[Question(id='Q2',title='體驗後方案',type=QuestionType.SINGLE,options=[Option(id='yes',label='是')])]),
        Page(id='P3',title='最後',questions=[Question(id='Q3',title='最後的意見',type=QuestionType.SHORT,persona_field='name')])])
    spec=TaskSpec(questionnaire=q,personas=[persona],provider=config)
    task=db.create_task(spec)
    response=AnswerEngine(MockProvider(config)).run(task,spec,persona);db.save_response(response)
    target=FormTarget(name='本機複現',url=google_like_server['url'],questionnaire_id=q.id,kind='google',authorized=True,success_selector='#success')
    tool=FormAutomation(db,tmp_path)
    dry=tool.run(target,response,[target.url],True)
    assert dry['status']=='dry_run' and dry['navigation_posts']==2 and dry['submission_posts']==0
    assert google_like_server['navigation_posts']==2 and google_like_server['submission_posts']==0
    assert google_like_server['values']=={'entry.Q1':'yes','entry.Q2':'yes'}
    sent=tool.run(target,response,[target.url],False)
    assert sent['status']=='success' and google_like_server['submission_posts']==1
    assert google_like_server['values']['entry.Q3']==persona.name


@pytest.mark.browser
def test_staged_survey_preserves_google_like_page_across_website_then_continues(db, persona, config, google_like_server, monkeypatch):
    from survey_sim import automation as module, staged_survey as staged
    from survey_sim.website_experience import WebsiteExperience, make_plan
    original = module.check_policy
    policy = lambda target,response,allowlist,dry_run: original(target.model_copy(update={'kind':'custom'}),response,allowlist,dry_run)
    monkeypatch.setattr(module,'check_policy',policy);monkeypatch.setattr(staged,'check_policy',policy)
    person=persona.model_copy(update={'onlyframe_tier':'BASIC','onlyframe_tier_reason':'Mock 方案選擇'})
    q=Questionnaire(id='google-staged-local',title='Google 分段本機複現',confirmed=True,pages=[
        Page(id='P1',title='前段',questions=[Question(id='Q1',title='操作前偏好',type=QuestionType.SINGLE,options=[Option(id='yes',label='是')])]),
        Page(id='P2',title='體驗',questions=[Question(id='Q2',title='體驗後方案',type=QuestionType.SINGLE,options=[Option(id='yes',label='是')])]),
        Page(id='P3',title='最後',questions=[Question(id='Q3',title='最後的意見',type=QuestionType.SHORT,persona_field='name')])])
    target=FormTarget(name='本機複現',url=google_like_server['url'],questionnaire_id=q.id,kind='google',authorized=True)
    spec=TaskSpec(questionnaire=q,personas=[person],provider=config,website_workflow=WebsiteWorkflow(),
        website_survey=WebsiteSurveyFlow(after_page_id='P1',tier_question_id='Q2',tier_options={'yes':'BASIC'},form_target=target,form_allowlist=[target.url],dry_run=True))
    calls=[]
    def website(self, workflow, p, seed=42, should_continue=None, on_saved=None, browser=None):
        page=browser.contexts[0].pages[0]
        assert '體驗後方案' in page.get_by_role('heading').inner_text()
        assert google_like_server['navigation_posts']==1
        calls.append('website')
        run=WebsiteRun(workflow_id=workflow.id,persona_id=p.id,persona_name=p.name,url=workflow.url.rstrip('/'),plan=make_plan(workflow,p,seed),mode='preview',status='preview_completed')
        self.db.save('website_run',run);on_saved(run);return run
    monkeypatch.setattr(WebsiteExperience,'run',website)
    task=db.create_task(spec)
    result=staged.StagedSurveyRunner(db,AnswerEngine(MockProvider(config))).run(task,spec,person,{},lambda:True)
    assert result.status=='passed' and result.form_result['status']=='dry_run'
    assert calls==['website'] and google_like_server['navigation_posts']==2 and google_like_server['submission_posts']==0


def test_website_operation_section_is_experienced_before_submission_question(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from survey_sim.ui import runtime
    from survey_sim.website_experience import staged_test_questionnaire
    monkeypatch.setenv('APP_DATA_DIR',str(tmp_path/'operation-ui'));runtime.clear()
    rt=runtime()
    q=staged_test_questionnaire();q.pages[1].title='第二階段：ONLYFRAME 網站操作';q.confirmed=True
    rt.db.save('questionnaire',q);rt.db.save('website_workflow',WebsiteWorkflow())
    app=AppTest.from_file(Path.cwd()/'app.py',default_timeout=30).run()
    try:
        navigate(app, '網站體驗模擬')
        next(item for item in app.selectbox if item.key=='website_q').set_value(q.id).run()
        assert not app.exception and not app.error
        boundary=next(item for item in app.selectbox if str(item.key).startswith('website_survey_boundary_'))
        assert boundary.value=='background'
    finally:runtime.clear()
