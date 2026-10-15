import importlib
import sys


def refresh_project_modules():
    """Resolve mixed module versions without clearing cached user resources."""
    models = sys.modules.get("survey_sim.models")
    workflow = sys.modules.get("survey_sim.workflow")
    automation = sys.modules.get("survey_sim.automation")
    operations = sys.modules.get("survey_sim.ui_operations")
    if models is None:
        return
    stale = not hasattr(models.TaskSpec, "reload_safe_snapshots") or "form_target" not in models.TaskSpec.model_fields or "onlyframe_tier" not in models.Persona.model_fields or "concurrency" not in models.TaskSpec.model_fields
    mixed = workflow is not None and workflow.TaskSpec is not models.TaskSpec
    if automation is not None:
        stale = stale or not hasattr(automation.FormAutomation, "advance_page")
        mixed = mixed or (operations is not None and operations.FormAutomation is not automation.FormAutomation)
    if stale or mixed:
        for name in list(sys.modules):
            if name == "survey_sim" or name.startswith("survey_sim."):
                sys.modules.pop(name, None)
        importlib.invalidate_caches()


refresh_project_modules()
from survey_sim.ui import main

if __name__ == "__main__":
    main()
