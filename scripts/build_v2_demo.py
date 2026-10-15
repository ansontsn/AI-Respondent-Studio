"""Build persistent Mock V2 experiments and exports in this local project."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from survey_sim.runtime import Runtime
from survey_sim.models import ProviderConfig, Scenario
from survey_sim.providers import make_provider
from survey_sim.conditional_personas import ConditionalPersonaGenerator, distribution_check
from survey_sim.v2_models import PersonaConditions, AgeBand, Experiment, ExperimentCell
from survey_sim.experiments import ExperimentService
from survey_sim.motivations import motivation_report
from survey_sim.quality import quality_report
from survey_sim.reports import report_exports


def main():
    path = ROOT / "data" / "simulator.sqlite3"
    if path.exists():
        with sqlite3.connect(path) as conn:
            if conn.execute("SELECT count(*) FROM tasks WHERE status='running'").fetchone()[0]:
                raise RuntimeError("There is an active task; pause it before building demonstration data.")
    rt = Runtime()
    c = rt.db.get("provider", "mock-default")
    other = ProviderConfig(id="mock-v2-comparison", name="Mock 比較設定 B", model="mock-v1-comparison")
    rt.db.save("provider", other)
    q = rt.db.get("questionnaire", "onlyframe-demo-v1")
    conditions = PersonaConditions(age_bands=[AgeBand(minimum=18,maximum=29,weight=1),AgeBand(minimum=30,maximum=55,weight=1)],
        genders={"女性":1,"男性":1},educations={"大學":2,"研究所":1},occupations={"工程師":1,"行政職員":1},
        income_range=(35000,70000),budget_range=(3000,8000), interests=["音樂","收藏"],
        trait_ranges={"personalization":(.5,.9)}, familiarity_range=(.3,.8))
    people = ConditionalPersonaGenerator(make_provider(c)).generate_batch(6,7000,q.topic,
        {"價格敏感型":1,"品質導向型":1,"高度興趣型":1},conditions,
        on_persona=lambda p,*_:rt.db.save("persona",p))
    service = ExperimentService(rt.db)
    model = service.create(Experiment(name="V2 示範｜兩個 Mock 設定",kind="model",questionnaire=q,personas=people,
        cells=[ExperimentCell(label="Mock 基準 A",provider=c),ExperimentCell(label="Mock 比較 B",provider=other)]),0)
    scenarios = [Scenario(name="A 基本款",description="固定樣式及基本保護，價格 200。",attributes={"price":200.,"customization":0.}),
                 Scenario(name="B 部分客製化",description="可調整外觀，價格 500。",attributes={"price":500.,"customization":.5}),
                 Scenario(name="C 高度客製化",description="可自由組合個人設計，價格 1000。",attributes={"price":1000.,"customization":1.})]
    scenario = service.create(Experiment(name="V2 示範｜三種產品情境",kind="scenario",questionnaire=q,personas=people,
        cells=[ExperimentCell(label=s.name,provider=c,scenario=s) for s in scenarios]),0)
    ids = [cell.task_id for exp in [model,scenario] for cell in exp.cells]
    rt.runner.start_group(ids)
    rt.runner.thread.join(timeout=60)
    if rt.runner.thread.is_alive() or not all(rt.db.task(id)["status"] in {"completed","completed_with_errors"} for id in ids):
        raise RuntimeError("V2 demonstration did not complete; inspect task errors.")
    folder = ROOT / "outputs" / "v2-demo"
    folder.mkdir(parents=True,exist_ok=True)
    (folder / "conditions.json").write_text(conditions.model_dump_json(indent=2),encoding="utf-8")
    (folder / "personas.json").write_text(json.dumps([p.model_dump() for p in people],ensure_ascii=False,indent=2),encoding="utf-8")
    reports = {"model-comparison":service.report(model),"scenario-comparison":service.report(scenario),
               "quality":quality_report(rt.db,ids[0]),"motivations":motivation_report(rt.db,ids[0],"Q12")}
    rt.set_setting("motivation_report_"+ids[0],reports["motivations"])
    for name,report in reports.items():
        for kind,data in report_exports(report).items():
            ext={"JSON":"json","CSV ZIP":"zip","Excel":"xlsx"}[kind]
            (folder/f"{name}.{ext}").write_bytes(data)
    manifest={"model_experiment_id":model.id,"scenario_experiment_id":scenario.id,"task_ids":ids,
        "generated_personas":len(people),"completed_responses":sum(len(rt.db.responses(id)) for id in ids),
        "conditions_distribution":distribution_check(people),"source":"Mock 功能示範；不是實際服務商或真人樣本"}
    (folder/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False))


if __name__ == "__main__":
    main()
