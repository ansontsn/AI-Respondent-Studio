"""One real UI click generates three Mock responses and submits to an owned local form."""
import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from survey_sim.automation import launch_browser
from survey_sim.examples import general_example


def main():
    server = json.loads((ROOT / ".tmp/workbench-browser-server.json").read_text(encoding="utf-8-sig"))
    folder = Path(server["folder"])
    assert folder.resolve().is_relative_to((ROOT / ".tmp").resolve())
    output = ROOT / "outputs/v2-integration"
    output.mkdir(parents=True, exist_ok=True)
    database = folder / "simulator.sqlite3"
    errors = []
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        try:
            page = browser.new_page(locale="zh-TW", viewport={"width": 1440, "height": 1050}, accept_downloads=True)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server['port']}", wait_until="domcontentloaded")
            page.get_by_role("heading", name="問卷工作台", exact=True).wait_for(timeout=30000)
            def select(label, value):
                page.get_by_role("combobox", name=label, exact=True).click()
                page.get_by_role("option", name=value, exact=True).click()
                page.get_by_role("button", name="Stop", exact=True).wait_for(state="hidden", timeout=30000)
            select("本次問卷", general_example().title)
            page.get_by_text("AI 自動建立人物", exact=True).click()
            page.get_by_role("spinbutton", name="欲建立的人數", exact=True).fill("3")
            page.get_by_role("spinbutton", name="欲建立的人數", exact=True).press("Enter")
            select("執行內容", "提交到已授權測試表單")
            page.get_by_text("本次確定將模擬答案提交到以上測試表單", exact=True).click()
            page.get_by_role("button", name="Stop", exact=True).wait_for(state="hidden", timeout=30000)
            page.get_by_role("button", name="開始批次處理（實際提交）", exact=True).click()
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                with sqlite3.connect(database) as db:
                    job = db.execute("SELECT id,status,spec,error FROM workbench_jobs ORDER BY created_at DESC LIMIT 1").fetchone()
                if job and job[1] in {"completed", "failed", "completed_with_errors"}:
                    break
                page.wait_for_timeout(250)
            assert job and job[1] == "completed", job
            settings = json.loads(job[2])
            destination = urlsplit(settings["form_target"]["url"])
            assert settings["provider"]["provider"] == "mock" and settings["submission_confirmed"]
            assert destination.hostname == "127.0.0.1" and destination.port == server["form_port"]
            with sqlite3.connect(database) as db:
                counts = {table: db.execute("SELECT count(*) FROM " + table).fetchone()[0]
                          for table in ("responses", "local_receipts", "submissions", "usage")}
                statuses = [r[0] for r in db.execute("SELECT status FROM submissions")]
            assert counts == {"responses": 3, "local_receipts": 3, "submissions": 3, "usage": 0}, counts
            assert statuses == ["success"] * 3
            page.get_by_role("button", name="下載模擬 JSON", exact=True).wait_for(timeout=15000)
            with page.expect_download() as download:
                page.get_by_role("button", name="下載模擬 JSON", exact=True).click()
            download.value.save_as(str(output / "browser-simulation.json"))
            assert json.loads((output / "browser-simulation.json").read_bytes())["摘要"]["回答數"] == 3
            page.get_by_role("button", name="下載模擬 JSON", exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(output / "one-click-completed.png"), full_page=True)
            page.reload(wait_until="domcontentloaded")
            page.get_by_role("button", name="下載模擬 JSON", exact=True).wait_for(timeout=30000)
            with sqlite3.connect(database) as db:
                assert db.execute("SELECT count(*) FROM workbench_jobs").fetchone()[0] == 1
                assert db.execute("SELECT count(*) FROM responses").fetchone()[0] == 3
                assert db.execute("SELECT count(*) FROM local_receipts").fetchone()[0] == 3
            assert not errors and page.locator('[data-testid="stException"]').count() == 0
            result = {"one_click": True, "mode": "explicit_local_submit", "counts": counts, "submissions": statuses,
                      "refresh_repeated_work": False, "paid_api_calls": 0, "external_form_submissions": 0, "javascript_errors": errors}
            (output / "browser-acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
