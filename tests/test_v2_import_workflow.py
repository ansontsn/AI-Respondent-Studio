import json

import pytest

from survey_sim.errors import AppError
from survey_sim.google_import import parse_public_metadata, parse_official_form, stable_option
from survey_sim.models import ProviderConfig, TaskSpec
from survey_sim.parsers import import_json, parse_google_dom
from survey_sim.questionnaire_review import review_report, confirm_questionnaire
from survey_sim.security import SecretStore
from survey_sim.workflow import provider_ready, fingerprint, validated_plan


def public_document(items):
    form = [None] * 9
    form[0], form[1], form[8] = "測試情境", items, "公開 metadata 測試"
    document = [None] * 19
    document[1], document[3], document[18] = form, "表單名稱", 0
    return document


def item(id, title, kind, options=None, required=True):
    return [id, title, None, kind, [[id + 100, options, int(required)]]]


def test_public_metadata_pages_scale_and_forward_routes():
    items = [item(1, "是否使用", 2, [["是",None,22], ["否",None,-3]]),
             [22,"量表頁",None,8,None,-2], item(2,"偏好",5, [[str(i)] for i in range(1,6)]),
             item(3,"留言",1,required=False)]
    html = '<script>var FB_PUBLIC_LOAD_DATA_ = ' + json.dumps(public_document(items), ensure_ascii=False) + ';</script>'
    q = parse_google_dom(html, "https://docs.google.com/forms/d/e/test/viewform")
    assert len(q.pages) == 2 and not q.confirmed
    assert q.questions[1].type == "linear_scale" and q.questions[1].scale_max == 5
    assert q.next_page("P1", {"G_1": stable_option("是")}) == "P_22"
    assert q.next_page("P1", {"G_1": stable_option("否")}) == "END"
    assert q.questions[2].required is False
    assert q.import_diagnostics["method"] == "public_metadata"


def test_public_special_type_and_backward_route_are_explicit():
    items = [[22,"第二頁",None,8,None,-2], item(1,"回頭",2,[["回第一頁",None,-1]]), item(2,"檔案",13)]
    html = '<script>FB_PUBLIC_LOAD_DATA_=' + json.dumps(public_document(items)) + ';</script>'
    q = parse_google_dom(html, "https://docs.google.com/forms/d/e/test/viewform")
    assert q.questions[-1].type == "unsupported"
    assert q.import_diagnostics["unresolved_routes"]
    with pytest.raises(AppError, match="不支援"): confirm_questionnaire(q, True)


def test_metadata_is_not_evaluated_and_falls_back_with_warning():
    html = '<script>FB_PUBLIC_LOAD_DATA_=not_json();</script><div role="listitem"><div role="heading">文字</div><input type="text"></div>'
    q = parse_google_dom(html, "https://docs.google.com/forms/d/e/test/viewform")
    assert q.import_diagnostics["method"] == "visible_dom"
    assert any("變動" in w for w in q.import_warnings)


def test_official_form_json_preserves_ids_pages_and_skip():
    data = {"info": {"title": "官方 JSON"}, "items": [
        {"itemId":"i1", "title":"是否使用", "questionItem":{"question":{"questionId":"q1","required":True,
         "choiceQuestion":{"type":"RADIO","options":[{"value":"是","goToSectionId":"section"},{"value":"否","goToAction":"SUBMIT_FORM"}]}}}},
        {"itemId":"section","title":"使用經驗","pageBreakItem":{}},
        {"itemId":"i2","title":"滿意度","questionItem":{"question":{"questionId":"q2","required":True,"scaleQuestion":{"low":0,"high":10}}}}]}
    q = import_json(json.dumps(data))
    assert q.questions[0].id == "G_q1" and q.questions[1].scale_min == 0
    assert q.next_page("P1", {"G_q1":stable_option("是")}) == "P_section"
    assert q.next_page("P1", {"G_q1":stable_option("否")}) == "END"
    assert not q.confirmed


def test_dom_explicit_scale_does_not_guess_numeric_single():
    controls = ''.join(f'<div role="radio" data-value="{i}"></div>' for i in range(1,6))
    base = '<div role="listitem" {kind}><div role="heading">程度</div>' + controls + '</div>'
    assert parse_google_dom(base.format(kind='data-question-type="scale"'), "url").questions[0].type == "linear_scale"
    assert parse_google_dom(base.format(kind=''), "url").questions[0].type == "single"


def test_wizard_confirmation_gate_and_preview_signature(questionnaire, persona, config):
    questionnaire.confirmed = False
    with pytest.raises(AppError): validated_plan(questionnaire,[persona],config)
    with pytest.raises(AppError): confirm_questionnaire(questionnaire, False)
    confirm_questionnaire(questionnaire, True)
    spec = validated_plan(questionnaire,[persona],config)
    signature = fingerprint(spec)
    spec.personas[0].traits.price_sensitivity = .1
    assert fingerprint(spec) != signature
    assert review_report(questionnaire)["questions"] == 17


def test_provider_readiness_is_configuration_not_live_validation(config):
    store = SecretStore()
    assert provider_ready(config,store)[0]
    api = ProviderConfig(provider="openai", model="test")
    assert not provider_ready(api,store)[0]
    store.put(api.id,"fictional-test-key")
    assert provider_ready(api,store)[0]
