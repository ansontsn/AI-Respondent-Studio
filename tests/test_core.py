import copy
import json

import pytest
from pydantic import ValidationError

from survey_sim.engine import AnswerEngine, Interrupted
from survey_sim.errors import AppError
from survey_sim.models import Answer, Condition, Option, Question, QuestionType, Traits
from survey_sim.mock_ai import MockProvider
from survey_sim.personas import PersonaGenerator, similarity
from survey_sim.providers import Completion, make_provider
from survey_sim.validator import AnswerValidator, value_errors


def test_seed_correlated_personas_and_exact_scenario_ratios(config):
    gen = PersonaGenerator(make_provider(config))
    ratios = {"價格敏感型": 3, "品質導向型": 2, "低度興趣型": 1}
    a = gen.generate_batch(30, 42, "金融服務", ratios)
    b = gen.generate_batch(30, 42, "金融服務", ratios)
    assert a == b
    assert len({p.id for p in a}) == 30
    assert sum(p.archetype == "價格敏感型" for p in a) == 15
    assert sum(p.archetype == "品質導向型" for p in a) == 10
    assert all(p.behavior.spending_budget <= p.background.disposable_budget for p in a)
    assert all("investment_experience_years" in p.topic_attributes for p in a)
    assert not any("collection_experience" in p.topic_attributes for p in a)
    assert len({p.background.occupation for p in a}) > 4
    assert any(similarity(a[0], p) < .85 for p in a[1:])


def test_full_questionnaire_keeps_persona_and_has_varied_neutral_answers(config, questionnaire):
    from survey_sim.models import TaskSpec
    people = PersonaGenerator(make_provider(config)).generate_batch(30, 200, questionnaire.topic,
        {"價格敏感型": 1, "高度興趣型": 1, "低度興趣型": 1})
    spec = TaskSpec(questionnaire=questionnaire, personas=people, provider=config)
    responses = [AnswerEngine(make_provider(config)).run("test", spec, p) for p in people]
    assert all(r.persona_snapshot == p and r.status != "error" for r, p in zip(responses, people))
    combinations = {json.dumps([a.value for a in r.answers], sort_keys=True) for r in responses}
    assert len(combinations) >= 25
    assert any(a.value == 3 for r in responses for a in r.answers if a.question_id in {"Q08", "Q09", "Q10", "Q11", "Q12"})
    assert any(r.visited_pages == ["P1", "P3"] for r in responses)
    assert any(r.visited_pages == ["P1", "P2", "P3"] for r in responses)


def test_hidden_questions_skipped(spec, persona, config):
    class NoCollector(MockProvider):
        def generate(self, operation, payload, system):
            result = super().generate(operation, payload, system)
            if operation in {"answer_page", "repair_page"}:
                for a in result.data["answers"]:
                    if a["question_id"] == "Q03": a["value"] = "no"
                    if a["question_id"] == "Q13": a["value"] = "low"
            return result
    r = AnswerEngine(NoCollector(config)).run("branch", spec, persona)
    assert r.visited_pages == ["P1", "P3"]
    assert all(a.validation == "skipped" and a.value is None for a in r.answers if a.question_id in {"Q05", "Q06", "Q07", "Q14"})


def test_repair_rejects_invalid_option(spec, persona, config):
    class Malformed(MockProvider):
        calls = 0
        def generate(self, operation, payload, system):
            result = super().generate(operation, payload, system)
            if operation == "answer_page" and self.calls == 0:
                self.calls += 1
                result.data["answers"][2]["value"] = "not-an-option"
            return result
    r = AnswerEngine(Malformed(config)).run("repair", spec, persona)
    assert r.status != "error"
    assert r.repair_history[0]["attempt"] == 1
    assert "Q03" in r.repair_history[0]["issue"]


def test_checkpoint_resume_does_not_repeat_completed_page(spec, persona, config):
    checkpoints = []
    engine = AnswerEngine(make_provider(config))
    with pytest.raises(Interrupted):
        engine.run("resume", spec, persona, on_checkpoint=checkpoints.append, should_continue=lambda: not checkpoints)
    class Tracking(MockProvider):
        pages = []
        def generate(self, operation, payload, system):
            self.pages.append(payload["page"]["id"])
            return super().generate(operation, payload, system)
    provider = Tracking(config)
    resumed = AnswerEngine(provider).run("resume", spec, persona, checkpoint=checkpoints[-1])
    original = engine.run("resume", spec, persona)
    assert resumed.answers == original.answers
    assert "P1" not in provider.pages


@pytest.mark.parametrize("kind,value,options,rows", [
    ("single", "bad", [Option(id="ok", label="OK")], []),
    ("single", ["ok"], [Option(id="ok", label="OK")], []),
    ("multiple", ["ok", "ok"], [Option(id="ok", label="OK")], []),
    ("multiple", "ok", [Option(id="ok", label="OK")], []),
    ("likert", True, [], []), ("likert", 6, [], []), ("likert", 2.2, [], []),
    ("short_text", 42, [], []), ("paragraph", [], [], []),
    ("single_grid", {"r": "bad"}, [Option(id="ok", label="OK")], [Option(id="r", label="Row")]),
    ("checkbox_grid", {"r": []}, [Option(id="ok", label="OK")], [Option(id="r", label="Row")]),
    ("unsupported", "anything", [], [])])
def test_invalid_values(kind, value, options, rows):
    assert value_errors(Question(id="Q", title="Q", type=kind, options=options, rows=rows), value)


def test_optional_blank_and_grid_and_choice_limits():
    assert not value_errors(Question(id="T", title="T", type="short_text", required=False), None)
    q = Question(id="M", title="M", type="multiple", options=[Option(id="a", label="A"), Option(id="b", label="B")], min_choices=2)
    assert value_errors(q, ["a"])
    assert not value_errors(q, ["a", "b"])
    grid = Question(id="G", title="G", type="checkbox_grid", options=q.options, rows=[Option(id="r", label="R")])
    assert not value_errors(grid, {"r": ["a", "b"]})


def test_attitude_difference_is_not_error(spec, persona, config):
    r = AnswerEngine(make_provider(config)).run("valid", spec, persona)
    next(a for a in r.answers if a.question_id == "Q10").value = 5
    next(a for a in r.answers if a.question_id == "Q11").value = 1
    _, issues, _, _ = AnswerValidator().validate(spec.questionnaire, persona, r.answers)
    assert not any(i.level == "error" for i in issues)


def test_missing_required_unknown_ids_and_branch_error(spec, persona, config):
    r = AnswerEngine(make_provider(config)).run("valid", spec, persona)
    r.answers = [a for a in r.answers if a.question_id != "Q01"]
    r.answers.append(Answer(question_id="unknown", value="oops"))
    _, issues, _, status = AnswerValidator().validate(spec.questionnaire, persona, r.answers)
    assert status == "error"
    assert {i.code for i in issues} >= {"missing", "id"}


def test_model_rejects_duplicate_ids_and_cyclic_routes(questionnaire):
    data = questionnaire.model_dump()
    data["pages"][0]["questions"][1]["id"] = "Q01"
    with pytest.raises(ValidationError): type(questionnaire).model_validate(data)
    data = questionnaire.model_dump()
    data["pages"][0]["routes"][0]["target"] = "P1"
    with pytest.raises(ValidationError): type(questionnaire).model_validate(data)
    with pytest.raises(ValidationError): Traits(price_sensitivity=1.1)


@pytest.mark.parametrize("operator,value,result", [("eq", "yes", True), ("ne", "no", True), ("includes", "yes", True), ("gt", 10, False)])
def test_conditions(operator, value, result):
    assert Condition(question_id="Q", operator=operator, value=value).matches({"Q": "yes"}) is result
    assert not Condition(question_id="Q", operator=operator, value=value).matches({})
