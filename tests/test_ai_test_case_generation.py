import json
import urllib.error

import pytest

from app.ai.provider import (
    AIProviderError,
    YandexAIStudioConfig,
    YandexAIStudioProvider,
)
from app.ai.schemas import (
    MAX_REQUIREMENT_LENGTH,
    json_schema_response_format,
    validate_test_case_draft,
)
from app.ai.service import generate_test_case_draft


def valid_draft():
    return {
        "title": "Проверка входа с корректными данными",
        "preconditions": ["Пользователь зарегистрирован"],
        "steps": [
            {
                "action": "Открыть страницу входа",
                "expected_result": "Отображается форма входа",
            },
            {
                "action": "Ввести корректные учётные данные и отправить форму",
                "expected_result": "Пользователь успешно авторизован",
            },
        ],
        "test_type": "positive",
        "priority": "high",
        "assumptions": [],
        "open_questions": [],
    }


class FakeProvider:
    def __init__(self, result):
        self.result = result
        self.received_requirement = None

    def generate(self, requirement):
        self.received_requirement = requirement
        return self.result


def test_service_trims_requirement_and_returns_validated_draft():
    provider = FakeProvider(valid_draft())

    result = generate_test_case_draft(provider, "  Проверить вход  ")

    assert provider.received_requirement == "Проверить вход"
    assert result["title"] == "Проверка входа с корректными данными"
    assert len(result["steps"]) == 2


@pytest.mark.parametrize("requirement", ["", "   ", None, "x" * (MAX_REQUIREMENT_LENGTH + 1)])
def test_service_rejects_empty_or_oversized_requirement_without_calling_provider(requirement):
    provider = FakeProvider(valid_draft())

    with pytest.raises(ValueError):
        generate_test_case_draft(provider, requirement)

    assert provider.received_requirement is None


def test_validator_rejects_unexpected_fields():
    payload = valid_draft()
    payload["project_name"] = "must not be accepted"

    with pytest.raises(ValueError, match="неполный или неожиданный"):
        validate_test_case_draft(payload)


def test_validator_rejects_empty_actions():
    payload = valid_draft()
    payload["steps"][0]["action"] = "  "

    with pytest.raises(ValueError, match="не должно быть пустым"):
        validate_test_case_draft(payload)


def test_validator_rejects_too_many_steps():
    payload = valid_draft()
    payload["steps"] = [
        {"action": "Действие", "expected_result": "Результат"} for _ in range(31)
    ]

    with pytest.raises(ValueError, match="от 1 до 30"):
        validate_test_case_draft(payload)


def test_schema_requires_all_fields_and_disallows_additional_properties():
    schema = json_schema_response_format()["json_schema"]["schema"]

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["test_type"]["enum"] == [
        "positive", "negative", "boundary"
    ]


def test_yandex_adapter_sends_privacy_header_and_parses_json(monkeypatch):
    draft = valid_draft()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps({
                "choices": [{"message": {"content": json.dumps(draft, ensure_ascii=False)}}]
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    config = YandexAIStudioConfig(
        api_key="test-api-key",
        folder_id="test-folder",
        model_uri="gpt://test-folder/model/latest",
    )
    provider = YandexAIStudioProvider(config, opener=fake_urlopen)

    result = provider.generate("Только тестовое требование")

    assert result == draft
    assert captured["request"].get_header("X-data-logging-enabled") == "false"
    assert captured["request"].get_header("X-folder-id") == "test-folder"
    assert captured["request"].get_header("Authorization") == "Api-Key test-api-key"
    sent_body = json.loads(captured["request"].data.decode("utf-8"))
    assert sent_body["store"] is False
    assert sent_body["n"] == 1
    assert len(sent_body["messages"]) == 2
    assert "Только тестовое требование" in sent_body["messages"][1]["content"]
    assert captured["timeout"] == 25


def test_yandex_adapter_does_not_expose_http_error_body():
    def failing_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 500, "server error", hdrs=None,
            fp=None
        )

    provider = YandexAIStudioProvider(
        YandexAIStudioConfig(
            api_key="test-api-key",
            folder_id="test-folder",
            model_uri="gpt://test-folder/model/latest",
        ),
        opener=failing_urlopen,
    )

    with pytest.raises(AIProviderError) as error:
        provider.generate("private requirement")

    assert "private requirement" not in str(error.value)
    assert "test-api-key" not in str(error.value)


def test_provider_config_hides_api_key_from_repr():
    config = YandexAIStudioConfig(
        api_key="do-not-display-this",
        folder_id="test-folder",
        model_uri="gpt://test-folder/model/latest",
    )

    assert "do-not-display-this" not in repr(config)
