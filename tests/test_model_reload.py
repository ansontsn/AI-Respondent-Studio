import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from survey_sim import storage
from survey_sim.engine import AnswerEngine
from survey_sim.models import TaskSpec, Questionnaire, Persona, ProviderConfig, Scenario, WebsiteWorkflow, Response
from survey_sim.mock_ai import MockProvider
from survey_sim.workflow import validated_plan


@pytest.fixture
def previous_models(monkeypatch):
    path = Path(storage.__file__).with_name("models.py")
    spec = importlib.util.spec_from_file_location("previous_survey_models", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_task_accepts_previous_class_versions_without_losing_data(previous_models, questionnaire, persona, config):
    old = previous_models
    q = old.Questionnaire.model_validate_json(questionnaire.model_dump_json())
    p = old.Persona.model_validate_json(persona.model_dump_json())
    provider = old.ProviderConfig.model_validate_json(config.model_dump_json())
    assert not isinstance(q, Questionnaire) and not isinstance(p, Persona)
    people = [p.model_copy(update={"id": f"p{i}"}) for i in range(10)]
    spec = validated_plan(q, people, provider, scenario=old.Scenario(name="原情境", description="保留情境"),
                          website_workflow=old.WebsiteWorkflow(name="原網站設定"))
    assert isinstance(spec.questionnaire, Questionnaire)
    assert all(isinstance(p, Persona) for p in spec.personas)
    assert isinstance(spec.provider, ProviderConfig)
    assert isinstance(spec.scenario, Scenario) and isinstance(spec.website_workflow, WebsiteWorkflow)
    assert spec.questionnaire.model_dump() == q.model_dump()
    assert [p.model_dump() for p in spec.personas] == [p.model_dump() for p in people]
    assert spec.provider.model_dump() == provider.model_dump()


def test_old_cached_database_reads_current_models(db, saved_response, previous_models, monkeypatch):
    for name in ["Persona", "Questionnaire", "ProviderConfig", "Response"]:
        monkeypatch.setattr(storage, name, getattr(previous_models, name))
    assert isinstance(db.get("questionnaire", saved_response.questionnaire_id), Questionnaire)
    assert isinstance(db.get("persona", saved_response.persona_id), Persona)
    assert isinstance(db.responses()[0], Response)
    assert db.responses()[0] == saved_response


def test_stale_objects_can_complete_preview_and_be_saved(db, previous_models, questionnaire, persona, config):
    old = previous_models
    q = old.Questionnaire.model_validate_json(questionnaire.model_dump_json())
    p = old.Persona.model_validate_json(persona.model_dump_json())
    provider = old.ProviderConfig.model_validate_json(config.model_dump_json())
    spec = validated_plan(q, [p], provider)
    task_id = db.create_task(spec)
    response = AnswerEngine(MockProvider(config)).run(task_id, spec, spec.personas[0])
    db.save_response(response)
    assert response.status != "error"
    assert db.responses(task_id)[0] == response


def test_reloaded_snapshot_still_rejects_invalid_data(previous_models, questionnaire, persona, config):
    invalid = previous_models.Persona.model_validate_json(persona.model_dump_json())
    invalid.background.__dict__["age"] = 10
    with pytest.raises(ValidationError) as error:
        TaskSpec(questionnaire=questionnaire, personas=[invalid], provider=config)
    assert any(e["loc"] == ("personas", 0, "background", "age") for e in error.value.errors())


def test_snapshot_keeps_required_questionnaire_confirmation(previous_models, questionnaire, persona, config):
    q = previous_models.Questionnaire.model_validate_json(questionnaire.model_dump_json())
    q.confirmed = False
    from survey_sim.errors import AppError
    with pytest.raises(AppError, match="尚未人工確認"):
        validated_plan(q, [persona], config)


def test_workflow_passes_plain_data_even_to_a_cached_constructor(questionnaire, persona, config, monkeypatch):
    from survey_sim import workflow
    def cached_constructor(**data):
        assert isinstance(data["questionnaire"], dict)
        assert isinstance(data["provider"], dict)
        assert all(isinstance(p, dict) for p in data["personas"])
        assert isinstance(data["scenario"], dict)
        return TaskSpec(**data)
    monkeypatch.setattr(workflow, "TaskSpec", cached_constructor)
    spec = workflow.validated_plan(questionnaire, [persona], config, scenario=Scenario(name="情境", description="原設定"))
    assert spec.questionnaire == questionnaire and spec.personas == [persona]


@pytest.mark.parametrize("state", ["stable", "mixed", "stale", "stale_persona", "stale_automation", "mixed_automation"])
def test_app_refresh_preserves_cached_resources_and_reloads_only_when_needed(state):
    import ast
    from types import SimpleNamespace
    from unittest.mock import Mock
    app_path = Path(storage.__file__).parents[1] / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "refresh_project_modules")
    model_class = type("TaskSpec", (), {} if state == "stale" else {"reload_safe_snapshots": lambda _: None, "model_fields": {"form_target": None, "concurrency": None}})
    persona_class = SimpleNamespace(model_fields={} if state == "stale_persona" else {"onlyframe_tier": None})
    automation_class = type("FormAutomation", (), {} if state == "stale_automation" else {"advance_page": lambda _: None})
    resource = SimpleNamespace(session={"test_profile": "test_session_key"})
    modules = {"survey_sim": object(), "survey_sim.models": SimpleNamespace(TaskSpec=model_class, Persona=persona_class),
               "survey_sim.workflow": SimpleNamespace(TaskSpec=object() if state == "mixed" else model_class),
               "survey_sim.automation": SimpleNamespace(FormAutomation=automation_class),
               "survey_sim.ui_operations": SimpleNamespace(FormAutomation=object() if state == "mixed_automation" else automation_class),
               "streamlit.runtime.caching": resource}
    invalidate = Mock()
    namespace = {"sys": SimpleNamespace(modules=modules), "importlib": SimpleNamespace(invalidate_caches=invalidate)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(app_path), "exec"), namespace)
    namespace["refresh_project_modules"]()
    assert modules["streamlit.runtime.caching"] is resource
    assert resource.session["test_profile"] == "test_session_key"
    if state == "stable":
        assert "survey_sim.models" in modules
        invalidate.assert_not_called()
    else:
        assert not any(name == "survey_sim" or name.startswith("survey_sim.") for name in modules)
        invalidate.assert_called_once()
