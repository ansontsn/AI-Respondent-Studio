"""Refresh exports of existing V2 demonstrations without creating new tasks."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from survey_sim.storage import Database
from survey_sim.experiments import ExperimentService
from survey_sim.quality import quality_report
from survey_sim.motivations import motivation_report
from survey_sim.reports import report_exports


def main():
    folder=ROOT/"outputs"/"v2-demo"
    manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    db=Database(ROOT/"data"/"simulator.sqlite3")
    service=ExperimentService(db)
    reports={"model-comparison":service.report(db.get("experiment",manifest["model_experiment_id"])),
        "scenario-comparison":service.report(db.get("experiment",manifest["scenario_experiment_id"])),
        "quality":quality_report(db,manifest["task_ids"][0]),"motivations":motivation_report(db,manifest["task_ids"][0],"Q12")}
    for name,report in reports.items():
        for kind,data in report_exports(report).items():
            ext={"JSON":"json","CSV ZIP":"zip","Excel":"xlsx"}[kind]
            (folder/f"{name}.{ext}").write_bytes(data)
    print("Refreshed four V2 reports; original tasks and responses preserved.")


if __name__=="__main__":
    main()
