"""Visual smoke test against the running local app; no external websites."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from survey_sim.automation import launch_browser


def main():
    output = Path(__file__).resolve().parents[1] / "outputs" / "ui"
    output.mkdir(parents=True, exist_ok=True)
    result, errors = [], []
    with sync_playwright() as pw:
        browser = launch_browser(pw)
        page = browser.new_page(viewport={"width": 1440, "height": 1050}, locale="zh-TW")
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto("http://127.0.0.1:8501", wait_until="domcontentloaded")
        page.get_by_role("heading", name="儀表板", exact=True).wait_for(timeout=30000)
        pages = ["儀表板", "AI 模型設定", "問卷管理", "虛擬人物管理", "AI 模擬控制台", "回答檢查", "自動填表測試", "結果分析", "系統設定"]
        for i, title in enumerate(pages):
            page.locator('[data-testid="stSidebar"]').get_by_text(title, exact=True).click()
            page.get_by_role("heading", name=title, exact=True).wait_for()
            page.get_by_role("button", name="Stop", exact=True).wait_for(state="hidden", timeout=30000)
            if title == "結果分析":
                page.locator('.js-plotly-plot').first.wait_for(state="visible", timeout=30000)
            page.wait_for_timeout(500)
            if page.locator('[data-testid="stException"]').count() or page.locator('[data-testid="stAlertContainer"]').filter(has_text="操作未完成").count():
                raise RuntimeError(f"UI error on {title}")
            page.screenshot(path=str(output / f"{i+1:02d}.png"), full_page=True)
            result.append({"page": title, "status": "passed"})
        page.set_viewport_size({"width": 1024, "height": 768})
        page.locator('[data-testid="stSidebar"]').get_by_text("儀表板", exact=True).click()
        page.wait_for_timeout(500)
        page.screenshot(path=str(output / "tablet.png"), full_page=True)
        browser.close()
    if errors:
        raise RuntimeError(errors)
    (output / "verification.json").write_text(json.dumps({"pages": result, "javascript_errors": errors, "tablet_viewport": "1024x768"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("9 UI pages verified in Chrome; no JavaScript errors; desktop/tablet screenshots saved.")


if __name__ == "__main__":
    main()
