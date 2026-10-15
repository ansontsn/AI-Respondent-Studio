import copy
import json
from pathlib import Path

import httpx
import pytest

from survey_sim.automation import FormAutomation, check_policy
from survey_sim.errors import AppError
from survey_sim.mock_form import MockFormServer
from survey_sim.models import FormTarget


def test_authorization_allowlist_and_research_guard(saved_response):
    r = saved_response
    t = FormTarget(name="form", url=f"http://127.0.0.1:8765/form/{r.questionnaire_id}", questionnaire_id=r.questionnaire_id)
    with pytest.raises(AppError, match="允許清單"): check_policy(t, r, [t.url + "-different"], True)
    with pytest.raises(AppError, match="授權"): check_policy(t, r, [t.url], False)
    assert check_policy(t, r, [t.url], True) == t.url
    t.purpose = "research"
    with pytest.raises(AppError, match="正式研究"): check_policy(t, r, [t.url], True)


@pytest.mark.browser
def test_real_browser_all_local_question_types_dryrun_submission_and_duplicate_guard(db, saved_response, tmp_path):
    server = MockFormServer(db, 0).start()
    try:
        t = FormTarget(name="本地", url=server.url(saved_response.questionnaire_id), questionnaire_id=saved_response.questionnaire_id, authorized=True)
        automation = FormAutomation(db, tmp_path / "screenshots")
        dry = automation.run(t, saved_response, [t.url], True)
        assert dry["status"] == "dry_run"
        assert not db.rows("SELECT * FROM local_receipts")
        result = automation.run(t, saved_response, [t.url], False)
        assert result["status"] == "success"
        receipt = db.rows("SELECT * FROM local_receipts")
        assert len(receipt) == 1
        received = json.loads(receipt[0]["answers"])
        def canonical(value):
            if isinstance(value, list): return sorted(value)
            if isinstance(value, dict): return {k: canonical(v) for k, v in value.items()}
            return value
        for answer in saved_response.answers:
            if answer.validation != "skipped" and answer.value is not None:
                assert canonical(received[answer.question_id]) == canonical(answer.value)
        assert received["Q15"] and received["Q16"]
        with pytest.raises(AppError, match="重複提交"): automation.run(t, saved_response, [t.url], False)
        assert len(db.rows("SELECT * FROM local_receipts")) == 1
    finally:
        server.close()


@pytest.mark.browser
def test_real_browser_conditional_skip(db, spec, persona, config, tmp_path):
    from survey_sim.engine import AnswerEngine
    from survey_sim.mock_ai import MockProvider
    class Skip(MockProvider):
        def generate(self, operation, payload, system):
            result = super().generate(operation, payload, system)
            for a in result.data["answers"]:
                if a["question_id"] == "Q03": a["value"] = "no"
                if a["question_id"] == "Q13": a["value"] = "low"
            return result
    db.save("questionnaire", spec.questionnaire)
    task = db.create_task(spec)
    r = AnswerEngine(Skip(config)).run(task, spec, persona)
    db.save_response(r)
    server = MockFormServer(db, 0).start()
    try:
        t = FormTarget(name="分流", url=server.url(r.questionnaire_id), questionnaire_id=r.questionnaire_id, authorized=True)
        assert FormAutomation(db, tmp_path).run(t, r, [t.url], False)["status"] == "success"
        answers = json.loads(db.rows("SELECT answers FROM local_receipts")[0]["answers"])
        assert all(id not in answers for id in ["Q05", "Q06", "Q07", "Q14"])
    finally:
        server.close()


def test_server_rejects_missing_required_and_is_idempotent(db, saved_response):
    server = MockFormServer(db, 0).start()
    try:
        url = server.url(saved_response.questionnaire_id).replace("/form/", "/submit/")
        invalid = httpx.post(url, json={"token": "t", "answers": {}, "visited": []})
        assert invalid.status_code == 400
        payload = {"token": "same", "answers": {a.question_id: a.value for a in saved_response.answers if a.validation != "skipped" and a.value is not None}, "visited": saved_response.visited_pages}
        a = httpx.post(url, json=payload)
        b = httpx.post(url, json=payload)
        assert a.status_code == 200 and b.status_code == 200
        assert a.json()["receipt"] == b.json()["receipt"]
    finally:
        server.close()


def test_unknown_status_blocks_retry_until_manual_resolution(db, saved_response, tmp_path):
    server = MockFormServer(db, 0).start()
    try:
        t = FormTarget(name="未知", url=server.url(saved_response.questionnaire_id), questionnaire_id=saved_response.questionnaire_id,
                       kind="custom", authorized=True, success_selector="#never-exists")
        # The custom adapter uses explicit mappings to the local form.
        for q in saved_response.questionnaire_snapshot.questions:
            q.binding.container_selector = f'[data-qid="{q.id}"]'
            q.binding.row_selectors = {r.id: f'[data-rowid="{r.id}"]' for r in q.rows}
        # Use local fill behavior with only success-marker overridden, by patching locator in a controlled stub is insufficient;
        # instead assert DB's conservative reservation state used for any uncertain network outcome.
        id = db.reserve_submission(saved_response.id, t, False)
        db.finish_submission(id, "unknown", "測試：接收狀態不明")
        with pytest.raises(AppError, match="重複提交"): db.reserve_submission(saved_response.id, t, False)
        db.finish_submission(id, "failed", "人工確認未收到")
        assert db.reserve_submission(saved_response.id, t, False)
    finally:
        server.close()


@pytest.mark.browser
def test_real_submission_unconfirmed_success_is_unknown(db, saved_response, tmp_path):
    server = MockFormServer(db, 0).start()
    try:
        t = FormTarget(name="不明狀態", url=server.url(saved_response.questionnaire_id), questionnaire_id=saved_response.questionnaire_id,
                       authorized=True, success_selector="#missing-success-marker")
        automation = FormAutomation(db, tmp_path)
        with pytest.raises(AppError, match="狀態不明"):
            automation.run(t, saved_response, [t.url], False)
        assert len(db.rows("SELECT * FROM local_receipts")) == 1
        assert db.rows("SELECT status FROM submissions")[0]["status"] == "unknown"
        with pytest.raises(AppError, match="重複提交"):
            automation.run(t, saved_response, [t.url], False)
    finally:
        server.close()


@pytest.mark.browser
def test_click_without_final_post_is_failed_and_keeps_after_click_artifact(db, saved_response, tmp_path, monkeypatch):
    server = MockFormServer(db, 0).start()
    try:
        target = FormTarget(name="無提交請求", url=server.url(saved_response.questionnaire_id),
            questionnaire_id=saved_response.questionnaire_id, authorized=True,
            success_selector="#success[data-receipt]")
        original = FormAutomation.navigation_button

        class NoPostButton:
            def count(self): return 1
            def is_visible(self): return True
            def click(self): return None

        monkeypatch.setattr(FormAutomation, "navigation_button",
            lambda self, page, form, *, submit=False: NoPostButton() if submit else original(self, page, form, submit=False))
        with pytest.raises(AppError, match="未發出最後提交請求"):
            FormAutomation(db, tmp_path).run(target, saved_response, [target.url], False)
        record = db.rows("SELECT status,message,artifact FROM submissions")[0]
        assert record["status"] == "failed" and "最後提交請求 0" in record["message"]
        assert Path(record["artifact"]).is_file()
        assert not db.rows("SELECT * FROM local_receipts")
    finally:
        server.close()
