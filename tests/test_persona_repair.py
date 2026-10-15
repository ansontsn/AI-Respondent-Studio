import copy

import pytest

from survey_sim.errors import AppError, ProviderError
from survey_sim.mock_ai import MockProvider
from survey_sim.personas import PersonaGenerator


class RecordingProvider(MockProvider):
    def __init__(self, config):
        super().__init__(config)
        self.calls = []

    def generate(self, operation, payload, system):
        self.calls.append((operation, copy.deepcopy(payload)))
        return super().generate(operation, payload, system)


def test_echoed_format_marker_removed_without_retry_or_mutation(config):
    class Echo(RecordingProvider):
        results = []
        def generate(self, operation, payload, system):
            result = super().generate(operation, payload, system)
            result.data["type"] = "json_object"
            self.results.append(result.data)
            return result
    provider = Echo(config)
    actual = PersonaGenerator(provider).generate_one(42, "AI 自動混合", "ONLYFRAME")
    expected = PersonaGenerator(MockProvider(config)).generate_one(42, "AI 自動混合", "ONLYFRAME")
    assert actual == expected
    assert [op for op, _ in provider.calls] == ["background", "persona"]
    assert all(data["type"] == "json_object" for data in provider.results)


@pytest.mark.parametrize("operation,path", [("background", "occupation"), ("persona", "behavior")])
def test_missing_required_field_repaired_with_specific_feedback(config, operation, path):
    class Missing(RecordingProvider):
        def generate(self, op, payload, system):
            result = super().generate(op, payload, system)
            if op == operation:
                if not payload.get("validation_feedback"):
                    result.data.pop(path)
                else:
                    assert path in payload["validation_feedback"]
                    assert "缺少必填" in payload["validation_feedback"]
            return result
    provider = Missing(config)
    person = PersonaGenerator(provider).generate_one(42, "AI 自動混合", "ONLYFRAME")
    assert person.id and len([op for op, _ in provider.calls if op == operation]) == 2
    assert {payload["seed"] for _, payload in provider.calls} == {42}


@pytest.mark.parametrize("unexpected,value", [("unexpected", "do not display this content"), ("type", "object")])
def test_unknown_fields_remain_invalid_and_retries_are_bounded(config, unexpected, value):
    class Unknown(RecordingProvider):
        def generate(self, op, payload, system):
            result = super().generate(op, payload, system)
            if op == "persona":
                result.data[unexpected] = value
            return result
    provider = Unknown(config)
    with pytest.raises(AppError) as error:
        PersonaGenerator(provider).generate_one(42, "AI 自動混合", "一般")
    assert unexpected in str(error.value) and "多出未允許欄位" in str(error.value)
    assert "3 次" in str(error.value) and "增加輸出 Token" not in str(error.value)
    assert value not in str(error.value)
    assert len(provider.calls) == 4
    assert all(value not in payload.get("validation_feedback", "") for _, payload in provider.calls)


def test_invalid_trait_repair_keeps_validation_strict(config):
    class InvalidTraits(RecordingProvider):
        def generate(self, op, payload, system):
            result = super().generate(op, payload, system)
            if op == "persona":
                result.data["type"] = "json_object"
                result.data["traits"]["rationality"] = 3
            return result
    provider = InvalidTraits(config)
    with pytest.raises(AppError, match="traits.rationality.*超過允許上限"):
        PersonaGenerator(provider).generate_one(42, "AI 自動混合", "一般")
    assert len(provider.calls) == 4


@pytest.mark.parametrize("change", ["reworded", "omitted"])
def test_changed_or_omitted_background_is_restored_without_another_request(config, change):
    # Review S-01: the confirmed background is owned by the application, so a
    # reworded or missing background no longer costs a repair request.
    class Changed(RecordingProvider):
        def generate(self, op, payload, system):
            result = super().generate(op, payload, system)
            if op == "persona":
                if change == "omitted":
                    result.data.pop("background")
                else:
                    result.data["background"]["occupation"] = "另一職業"
            return result
    provider = Changed(config)
    person = PersonaGenerator(provider).generate_one(42, "AI 自動混合", "一般")
    assert [op for op, _ in provider.calls] == ["background", "persona"]
    assert person.background.model_dump() == provider.calls[1][1]["background"]


def test_trait_conditions_are_applied_without_another_request(config):
    class Changed(RecordingProvider):
        def generate(self, op, payload, system):
            result = super().generate(op, payload, system)
            if op == "persona":
                result.data["traits"]["rationality"] = .2
            return result
    provider = Changed(config)
    person = PersonaGenerator(provider).generate_one(42, "AI 自動混合", "一般", trait_overrides={"rationality": .8})
    assert person.traits.rationality == .8
    assert [op for op, _ in provider.calls] == ["background", "persona"]


def test_malformed_json_can_retry(config):
    class Malformed(RecordingProvider):
        def generate(self, op, payload, system):
            result = super().generate(op, payload, system)
            if op == "background" and not payload.get("validation_feedback"):
                raise ProviderError("not JSON", kind="format")
            return result
    provider = Malformed(config)
    assert PersonaGenerator(provider).generate_one(42, "AI 自動混合", "一般").id
    assert [op for op, _ in provider.calls] == ["background", "background", "persona"]


@pytest.mark.parametrize("kind,message", [("api", "API Key 無效"), ("api", "AI 請求逾時"), ("truncated", "AI 輸出被 Token 上限截斷；請增加最大輸出 Token。")])
def test_auth_network_and_truncation_keep_their_original_errors(config, kind, message):
    class Failed(RecordingProvider):
        def generate(self, op, payload, system):
            self.calls.append((op, payload))
            raise ProviderError(message, kind=kind)
    provider = Failed(config)
    with pytest.raises(ProviderError) as error:
        PersonaGenerator(provider).generate_one(42, "AI 自動混合", "一般")
    assert str(error.value) == message and len(provider.calls) == 1


def test_batch_preserves_saved_people_when_later_repair_fails(db, config):
    class Partial(RecordingProvider):
        def generate(self, op, payload, system):
            result = super().generate(op, payload, system)
            if op == "persona" and payload["seed"] == 43:
                result.data.pop("behavior")
            return result
    with pytest.raises(AppError, match="behavior.*缺少必填"):
        PersonaGenerator(Partial(config)).generate_batch(3, 42, "一般", {"AI 自動混合": 1},
            on_persona=lambda p, *_: db.save("persona", p))
    people = db.list("persona")
    assert len(people) == 1 and people[0].seed == 42


def test_thirty_people_with_echoed_format_marker_match_baseline(config):
    class Echo(RecordingProvider):
        def generate(self, op, payload, system):
            result = super().generate(op, payload, system)
            result.data["type"] = "json_object"
            return result
    ratios = {"AI 自動混合": 1}
    actual = PersonaGenerator(Echo(config)).generate_batch(30, 42, "一般消費與生活", ratios)
    expected = PersonaGenerator(MockProvider(config)).generate_batch(30, 42, "一般消費與生活", ratios)
    assert actual == expected and len({p.id for p in actual}) == 30


@pytest.mark.parametrize("invalid", [False, True])
def test_people_button_handles_marker_and_displays_real_validation_error(config, tmp_path, monkeypatch, invalid):
    from streamlit.testing.v1 import AppTest
    from survey_sim import ui_people
    from survey_sim.storage import Database
    class Echo(MockProvider):
        def generate(self, op, payload, system):
            result = super().generate(op, payload, system)
            result.data["type"] = "json_object"
            if invalid and op == "persona":
                result.data["traits"]["rationality"] = 3
            return result
    monkeypatch.setattr(ui_people, "make_provider", lambda *args: Echo(config))
    code = "from survey_sim.runtime import Runtime\nfrom survey_sim.ui_people import people_page\npeople_page(Runtime(" + repr(str(tmp_path / "ui")) + "))"
    app = AppTest.from_string(code, default_timeout=15).run()
    next(i for i in app.number_input if i.label == "人物數量").set_value(2).run()
    next(b for b in app.button if b.label == "生成並儲存人物").click().run()
    assert not app.exception
    saved = Database(tmp_path / "ui/simulator.sqlite3").list("persona")
    if invalid:
        assert not saved
        assert any("traits.rationality" in error.value and "超過允許上限" in error.value for error in app.error)
        assert all("增加輸出 Token" not in error.value for error in app.error)
    else:
        assert len(saved) == 2 and not app.error
        assert any("已建立並保存 2 位" in success.value for success in app.success)
