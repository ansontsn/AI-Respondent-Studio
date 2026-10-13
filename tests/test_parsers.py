import json

import pytest

from survey_sim.errors import AppError
from survey_sim.parsers import import_json, import_csv, parse_google_dom


def test_json_import_requires_new_review(questionnaire):
    q = import_json(questionnaire.model_dump_json())
    assert not q.confirmed
    assert [x.id for x in q.questions] == [x.id for x in questionnaire.questions]
    assert q.pages[0].routes == questionnaire.pages[0].routes


def test_csv_import_types_options_stable_ids():
    csv = 'id,title,type,options,page_id,required\nA,考量,multiple,價格|品質,P1,true\nB,偏好,likert,,P2,false\n'
    q = import_csv(csv, "測試")
    assert q.questions[0].id == "A" and len(q.questions[0].options) == 2
    assert not q.questions[1].required
    assert [p.id for p in q.pages] == ["P1", "P2"]


def test_import_fails_with_explicit_errors():
    with pytest.raises(AppError, match="CSV"): import_csv("name,test\n1,2", "bad")
    with pytest.raises(AppError, match="JSON"): import_json("bad")


def test_google_dom_draft_and_unknown_type_preserved():
    html = '<html><title>示範表單</title><div role="listitem" data-item-id="123"><div role="heading">喜歡嗎？ *</div><div role="radio" data-value="是"></div><div role="radio" data-value="否"></div></div><div role="listitem"><div role="heading">上傳檔案</div><input type="file"></div></html>'
    q = parse_google_dom(html, "https://docs.google.com/forms/d/e/test/viewform")
    assert q.questions[0].id == "G_123" and q.questions[0].required
    assert q.questions[1].type == "unsupported"
    assert not q.confirmed and len(q.import_warnings) >= 3
    assert parse_google_dom(html, q.source_url).questions[1].id == q.questions[1].id
    with pytest.raises(AppError): parse_google_dom("<html>Login</html>", q.source_url)
