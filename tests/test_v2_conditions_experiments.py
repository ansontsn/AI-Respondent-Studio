import json

import pytest
from pydantic import ValidationError

from survey_sim.conditional_personas import ConditionalPersonaGenerator, condition_plan, distribution_check
from survey_sim.errors import AppError
from survey_sim.experiments import ExperimentService
from survey_sim.models import ProviderConfig, Scenario
from survey_sim.providers import make_provider
from survey_sim.security import SecretStore
from survey_sim.batch import BatchRunner
from survey_sim.v2_models import PersonaConditions, AgeBand, Experiment, ExperimentCell


def test_controlled_marginals_traits_budget_and_reproducibility(config):
    conditions = PersonaConditions(age_bands=[AgeBand(minimum=18,maximum=24,weight=7),AgeBand(minimum=40,maximum=55,weight=3)],
        genders={"女性":6,"男性":4}, occupations={"行政職員":7,"工程師":3}, income_range=(30000,60000),budget_range=(1000,4000),
        interests=["閱讀","運動"], core_values=["節制消費"], trait_ranges={"rationality":(.7,.9)},familiarity_range=(.2,.4))
    generator = ConditionalPersonaGenerator(make_provider(config))
    a = generator.generate_batch(10,100,"數位服務",{"AI 自動混合":1},conditions)
    b = generator.generate_batch(10,100,"數位服務",{"AI 自動混合":1},conditions)
    assert a == b
    assert sum(p.background.age <= 24 for p in a) == 7
    assert sum(p.background.gender == "女性" for p in a) == 6
    assert sum(p.background.occupation == "工程師" for p in a) == 3
    assert all(.7 <= p.traits.rationality <= .9 for p in a)
    assert all(1000 <= p.background.disposable_budget <= 4000 <= p.background.monthly_income for p in a)
    assert all(.2 <= p.topic_attributes["product_familiarity"] <= .4 for p in a)
    assert all(p.core_values == ["節制消費"] for p in a)
    assert distribution_check(a)["gender"]["女性"] == 6


def test_incoherent_conditions_rejected_and_retirement_marginals_preserved():
    with pytest.raises(ValidationError): PersonaConditions(income_range=(1000,2000),budget_range=(3000,4000))
    with pytest.raises(ValidationError): PersonaConditions(genders={"女性":-1})
    with pytest.raises(ValidationError): PersonaConditions(trait_ranges={"unknown":(.1,.2)})
    invalid = PersonaConditions(age_bands=[AgeBand(minimum=18,maximum=24)],occupations={"退休人士":1})
    with pytest.raises(AppError,match="退休"): condition_plan(invalid,10,42)
    valid = PersonaConditions(age_bands=[AgeBand(minimum=18,maximum=24,weight=1),AgeBand(minimum=50,maximum=65,weight=1)],occupations={"退休人士":1,"行政職員":1})
    plan = condition_plan(valid,10,42)
    assert sum(r["age"] <=24 for r in plan) == 5
    assert all(r["age"] >=40 for r in plan if r["occupation"]=="退休人士")


def test_model_experiment_runs_same_snapshots_and_reports_pairing(db, questionnaire, persona, config):
    other = ProviderConfig(id="mock-other",name="第二個 Mock",model="mock-other")
    exp = Experiment(name="測試模型",kind="model",questionnaire=questionnaire,personas=[persona],
        cells=[ExperimentCell(label="A",provider=config),ExperimentCell(label="B",provider=other)])
    service = ExperimentService(db)
    saved = service.create(exp, interval_seconds=0)
    runner = BatchRunner(db,SecretStore())
    runner.start_group([c.task_id for c in saved.cells])
    runner.thread.join(timeout=10)
    report = service.report(saved)
    assert all(r["完成率"]==1 for r in report["summary"])
    assert report["paired_differences"] and not any(r["不同"] for r in report["paired_differences"])
    assert all(db.responses(c.task_id)[0].persona_snapshot==persona for c in saved.cells)
    assert all(db.responses(c.task_id)[0].seed==42 for c in saved.cells)
    assert service.summary(saved)[0]["輸入Token"] is None
    assert db.get("experiment",saved.id)==saved


def test_scenario_differences_preserve_persona(db,questionnaire,persona,config):
    # Choose a controlled, interested persona. A low-interest person's two low
    # scores can legitimately stay identical across scenarios.
    persona.topic_attributes["topic_interest"] = .95
    persona.behavior.spending_budget = 3000
    persona.traits.quality_focus = .8
    persona.traits.personalization = .9
    a = Scenario(name="便宜固定款",description="基本功能",attributes={"price":10,"customization":0})
    b = Scenario(name="昂貴客製款",description="自由設計",attributes={"price":100000,"customization":1})
    exp = Experiment(name="情境測試",kind="scenario",mode="consistent",questionnaire=questionnaire,personas=[persona],cells=[
        ExperimentCell(label="A",provider=config,scenario=a),ExperimentCell(label="B",provider=config,scenario=b)])
    saved = ExperimentService(db).create(exp,interval_seconds=0)
    runner = BatchRunner(db,SecretStore())
    runner.start_group([c.task_id for c in saved.cells]);runner.thread.join(timeout=10)
    rs = [db.responses(c.task_id)[0] for c in saved.cells]
    assert rs[0].persona_snapshot==rs[1].persona_snapshot==persona
    assert rs[0].scenario==a and rs[1].scenario==b
    assert next(x.value for x in rs[0].answers if x.question_id=="Q12") > next(x.value for x in rs[1].answers if x.question_id=="Q12")
    assert all(r.elapsed_seconds is not None for r in rs)


def test_experiment_validation_is_atomic(db,questionnaire,persona,config):
    exp = Experiment(name="bad",kind="model",questionnaire=questionnaire,personas=[persona],cells=[ExperimentCell(label="A",provider=config)])
    with pytest.raises(AppError): ExperimentService(db).create(exp)
    assert not db.rows("SELECT * FROM tasks")


def test_experiment_report_preserves_execution_parameters(db,questionnaire,persona,config):
    service = ExperimentService(db)
    exp = service.create(Experiment(name="完整設定",kind="model",questionnaire=questionnaire,personas=[persona],mode="custom",seed=97,
        cells=[ExperimentCell(label="A",provider=config),ExperimentCell(label="B",provider=config)]),
        interval_seconds=2.5,budget_limit=3.,variability=.35)
    db.update_budget(exp.cells[0].task_id,4.)
    report = service.report(exp)
    for cell in exp.cells:
        saved = report["task_settings"][cell.task_id]
        assert saved["seed"] == 97 and saved["variability"] == .35
        assert saved["interval_seconds"] == 2.5
        assert saved["personas"][0]["id"] == persona.id
        assert saved["questionnaire"]["id"] == questionnaire.id
    assert report["task_settings"][exp.cells[0].task_id]["budget_limit"] == 4.
    assert report["task_settings"][exp.cells[1].task_id]["budget_limit"] == 3.


@pytest.mark.parametrize("value",[float("nan"),float("inf"),float("-inf")])
def test_nonfinite_condition_weights_are_rejected(value):
    with pytest.raises(ValidationError): PersonaConditions(genders={"女性":value})


@pytest.mark.parametrize("key,value",[("price",float("nan")),("price",float("inf")),("price",-1.),("customization",float("nan")),("customization",1.1)])
def test_invalid_scenario_attributes_are_rejected(key,value):
    with pytest.raises(ValidationError): Scenario(name="測試",description="情境",attributes={key:value})


def test_blank_scenario_name_is_rejected():
    with pytest.raises(ValidationError): Scenario(name=" ",description="情境")
