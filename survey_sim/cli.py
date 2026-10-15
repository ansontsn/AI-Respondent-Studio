from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .analysis import export_csv_zip, export_excel, export_json
from .automation import FormAutomation
from .engine import AnswerEngine
from .examples import onlyframe_example, general_example
from .models import ProviderConfig, TaskSpec, FormTarget
from .personas import PersonaGenerator
from .providers import make_provider
from .runtime import Runtime, ROOT


def write_examples():
    folder = ROOT / "examples"
    folder.mkdir(exist_ok=True)
    for name, q in [("onlyframe_questionnaire.json", onlyframe_example()), ("general_questionnaire.json", general_example())]:
        (folder / name).write_text(q.model_dump_json(indent=2), encoding="utf-8")
    c = ProviderConfig()
    people = PersonaGenerator(make_provider(c)).generate_batch(8, 42, "一般消費與生活",
        {"價格敏感型": 1, "品質導向型": 1, "低度興趣型": 1, "高度興趣型": 1})
    (folder / "personas.json").write_text(json.dumps([p.model_dump() for p in people], ensure_ascii=False, indent=2), encoding="utf-8")
    with (folder / "questions.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "title", "type", "required", "options", "page_id", "trait"])
        writer.writeheader()
        writer.writerows([{"id": "C01", "title": "我會比較價格", "type": "likert", "required": "true", "page_id": "P1", "trait": "price_sensitivity"},
                         {"id": "C02", "title": "選擇服務時的考量", "type": "multiple", "options": "價格|品質|品牌|社群", "required": "true", "page_id": "P1"}])


def main():
    parser = argparse.ArgumentParser(description="本地 AI 問卷功能測試")
    parser.add_argument("command", choices=["examples", "demo"])
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    if args.command == "examples":
        write_examples()
        print("已建立 examples 範例人物、問卷及 CSV。")
        return
    rt = Runtime(args.data_dir)
    config = rt.db.get("provider", "mock-default")
    q = rt.db.get("questionnaire", "onlyframe-demo-v1")
    personas = PersonaGenerator(make_provider(config)).generate_batch(args.count, args.seed, q.topic,
        {"價格敏感型": 3, "品質導向型": 2, "外觀導向型": 2, "低度興趣型": 3, "高度興趣型": 2})
    for p in personas:
        rt.db.save("persona", p)
    spec = TaskSpec(questionnaire=q, personas=personas, provider=config, seed=args.seed, interval_seconds=0)
    task = rt.db.create_task(spec)
    rt.runner.start(task)
    rt.runner.thread.join()
    responses = rt.db.responses(task)
    output = ROOT / "outputs" / "demo" / task
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_bytes(export_json(rt.db, task))
    (output / "results.xlsx").write_bytes(export_excel(rt.db, task))
    (output / "results-csv.zip").write_bytes(export_csv_zip(rt.db, task))
    if args.browser:
        server = rt.local_form()
        try:
            target = FormTarget(name="本地驗收", url=server.url(q.id), questionnaire_id=q.id, kind="local", authorized=True)
            rt.db.save("target", target)
            rt.set_setting("url_allowlist", sorted(set(rt.setting("url_allowlist", []) + [target.url])))
            automation = FormAutomation(rt.db, rt.data_dir / "artifacts")
            for r in responses[:2]:
                print(automation.run(target, r, [target.url], True)["message"])
                print(automation.run(target, r, [target.url], False)["message"])
        finally:
            server.close()
    # Include browser audit results in the exported dataset, too.
    (output / "results.json").write_bytes(export_json(rt.db, task))
    (output / "results.xlsx").write_bytes(export_excel(rt.db, task))
    (output / "results-csv.zip").write_bytes(export_csv_zip(rt.db, task))
    print(f"任務 {task}: {len(responses)}/{len(personas)} 回答；{rt.db.task(task)['status']}")
    print(f"輸出：{output}")


if __name__ == "__main__":
    main()
