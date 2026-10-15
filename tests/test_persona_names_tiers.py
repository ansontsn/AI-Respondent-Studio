from conftest import navigate
import json

import pytest

from survey_sim.models import WebsiteWorkflow, WebsiteRun, TaskSpec
from survey_sim.personas import PersonaGenerator
from survey_sim.persona_names import name_for_id, is_placeholder, ensure_name
from survey_sim.providers import make_provider
from survey_sim.website_experience import make_plan, assign_tiers, workflow_for_person, TIERS, submission_key, website_test_questionnaire, TEST_BINDINGS


def test_names_are_generated_stable_and_distinct(config):
    g=PersonaGenerator(make_provider(config))
    a=g.generate_batch(50,5700,'生活',{'AI 自動混合':1})
    b=g.generate_batch(50,5700,'生活',{'AI 自動混合':1})
    assert a==b
    assert len({p.name for p in a})==50
    assert all(len(p.name)==3 and not is_placeholder(p.name) for p in a)
    assert len({p.id for p in a})==50


def test_existing_custom_name_is_preserved_and_collisions_resolved(persona):
    p=persona.model_copy(deep=True);p.name='林思妤'
    assert ensure_name(p).name=='林思妤'
    p.name='虛擬人物 42';ensure_name(p)
    previous=p.name;ensure_name(p,[previous]);assert p.name!=previous
    assert name_for_id('fixed-id')==name_for_id('fixed-id')


def test_thousands_of_name_choices_are_unique():
    names=set()
    for index in range(10000):
        name=name_for_id(str(index),names)
        assert len(name)==3 and name not in names
        names.add(name)


def test_tier_counts_reproducible_without_persona_mutation(config):
    people=PersonaGenerator(make_provider(config)).generate_batch(9,8100,'收藏',{'高度興趣型':1})
    original=[p.model_dump_json() for p in people]
    counts={'BASIC':2,'CUSTOM':3,'PREMIUM':4}
    allocation=assign_tiers(people,counts,42)
    assert allocation==assign_tiers(list(reversed(people)),counts,42)
    assert {t:list(allocation.values()).count(t) for t in TIERS}==counts
    assert original==[p.model_dump_json() for p in people]
    with pytest.raises(Exception,match='合計'):assign_tiers(people,{'BASIC':1,'CUSTOM':1,'PREMIUM':1})


def test_plans_follow_permissions_and_legacy_submission_key(persona):
    plans=[make_plan(WebsiteWorkflow(tier=t,plan_mode='recorded'),persona) for t in TIERS]
    assert not plans[0].text and not plans[0].background and not plans[0].sticker
    assert plans[1].text and not plans[1].background and not plans[1].sticker
    assert plans[2].text and plans[2].background and plans[2].sticker
    import hashlib
    legacy=plans[1].model_dump(exclude={'background','sticker'})
    assert submission_key('https://www.onlyframe.online/',persona.id,plans[1])==hashlib.sha256(json.dumps(['https://www.onlyframe.online/',persona.id,legacy],sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def test_batch_applies_each_person_tier_and_retains_names(db,config,monkeypatch):
    from survey_sim.website_experience import WebsiteExperience
    from survey_sim.batch import BatchRunner
    from survey_sim.security import SecretStore
    from survey_sim.quality import regenerate
    people=PersonaGenerator(make_provider(config)).generate_batch(3,6200,'收藏',{'高度興趣型':1})
    q=website_test_questionnaire();q.confirmed=True
    allocation=assign_tiers(people,dict.fromkeys(TIERS,1))
    spec=TaskSpec(questionnaire=q,personas=people,provider=config,website_workflow=WebsiteWorkflow(),website_tier_assignments=allocation,website_fact_bindings=TEST_BINDINGS,interval_seconds=0)
    calls=[]
    def fake_run(self,w,p,seed,keep,on_saved):
        calls.append((p.name,w.tier))
        run=WebsiteRun(workflow_id=w.id,persona_id=p.id,persona_name=p.name,url=w.url,plan=make_plan(w,p,seed),mode=w.mode,status='preview_completed')
        self.db.save('website_run',run);on_saved(run);return run
    monkeypatch.setattr(WebsiteExperience,'run',fake_run)
    id=db.create_task(spec);runner=BatchRunner(db,SecretStore());runner.start(id);runner.thread.join(10)
    results=db.responses(id)
    assert len(results)==3 and {r.website_run.plan.tier for r in results}==set(TIERS)
    for r in results:
        assert r.website_run.persona_name==r.persona_snapshot.name
        assert next(a.value for a in r.answers if a.question_id=='site_tier')==allocation[r.persona_id]
    repaired=regenerate(db,[results[0].id]);runner.start(repaired);runner.thread.join(10)
    assert len(calls)==3 and db.responses(repaired)[0].website_run==results[0].website_run


def test_old_custom_questionnaire_rejected_before_basic_submission(db,persona,config):
    q=website_test_questionnaire();q.confirmed=True
    q.pages[0].questions[0].options=q.pages[0].questions[0].options[1:2]
    spec=TaskSpec(questionnaire=q,personas=[persona],provider=config,website_workflow=WebsiteWorkflow(tier='BASIC',mode='submit',authorized_test=True),website_fact_bindings=TEST_BINDINGS)
    with pytest.raises(Exception,match='不相容'):db.create_task(spec)
    assert not db.rows("SELECT * FROM entities WHERE kind='website_submit_guard'")


def test_public_backend_detection_is_read_only_without_key_output(monkeypatch):
    import httpx
    from survey_sim.website_experience import detect_submission_endpoint
    original=httpx.Client
    requests=[]
    def handler(request):
        requests.append((request.method,str(request.url)))
        return httpx.Response(200,text='<script src="/assets/main.js"></script>' if request.url.path=='/' else 'const publicUrl="https://sample.supabase.co"; const publicKey="not-exported";')
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    endpoint=detect_submission_endpoint(WebsiteWorkflow())
    assert endpoint=='https://sample.supabase.co/rest/v1/design_submissions'
    assert requests==[('GET','https://www.onlyframe.online'),('GET','https://www.onlyframe.online/assets/main.js')]


def test_ui_allocates_three_named_personas_without_running_browser(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    from survey_sim.ui import runtime
    monkeypatch.setenv('APP_DATA_DIR',str(tmp_path/'ui'));runtime.clear()
    rt=runtime();c=rt.db.get('provider','mock-default')
    people=PersonaGenerator(make_provider(c)).generate_batch(3,15770,'生活',{'AI 自動混合':1})
    for p in people:rt.db.save('persona',p)
    w=WebsiteWorkflow();rt.db.save('website_workflow',w)
    q=website_test_questionnaire();q.confirmed=True;rt.db.save('questionnaire',q)
    app=AppTest.from_file(Path.cwd()/'app.py',default_timeout=30).run()
    navigate(app, '網站體驗模擬')
    next(m for m in app.multiselect if m.label=='網站操作人物').set_value([p.id for p in people]).run()
    assert all(next(n for n in app.number_input if n.label==tier+' 人數').value==1 for tier in TIERS)
    next(b for b in app.button if b.label=='建立網站操作與答題任務').click().run()
    assert not app.exception and not app.error
    spec=TaskSpec.model_validate_json(rt.db.rows('SELECT spec FROM tasks')[0]['spec'])
    assert set(spec.website_tier_assignments.values())==set(TIERS) and spec.website_workflow.use_persona_name
    assert {p.id:p.name for p in spec.personas}=={p.id:p.name for p in people}
    assert not rt.db.list('website_run')
    runtime.clear()
