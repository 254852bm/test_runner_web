import pytest

from app.ai.automation_service import generate_automation_test_draft
from app.ai.provider import AIProviderError


def context():
    return {
        "title": "Проверка входа",
        "preconditions": ["Пользователь существует"],
        "steps": [{
            "action": "Открыть форму входа",
            "expected_result": "Форма отображается",
        }],
        "parameters": [{"name": "Пароль", "is_secret": True}],
    }


def draft():
    return {
        "summary": "Черновик теста входа.",
        "target_profile": {
            "language": "java",
            "framework": "junit5",
            "test_type": "api",
        },
        "files": [{
            "path": "src/test/java/LoginTest.java",
            "content": "class LoginTest { @org.junit.jupiter.api.Test void login() {} }",
        }],
        "assumptions": [],
        "open_questions": ["Какой API-клиент используется?"],
        "todo_items": ["Настроить тестовый URL."],
        "coverage_notes": ["Проверяет открытие формы входа."],
    }


class FakeStructuredProvider:
    def __init__(self, response=None, error=None):
        self.response = response or draft()
        self.error = error
        self.kwargs = None

    def generate_structured(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def test_service_generates_structured_draft_without_secret_values():
    provider = FakeStructuredProvider()

    result = generate_automation_test_draft(provider, context())

    assert result["target_profile"]["framework"] == "junit5"
    assert "Пароль" in provider.kwargs["user_prompt"]
    assert '"is_secret":true' in provider.kwargs["user_prompt"]
    assert "secret-value" not in provider.kwargs["user_prompt"]
    assert provider.kwargs["response_format"]["json_schema"]["strict"] is True


@pytest.mark.parametrize("bad_context", [
    None,
    {},
    {"title": "x", "preconditions": [], "steps": [], "parameters": []},
    {
        "title": "x", "preconditions": [],
        "steps": [{"action": "a", "expected_result": "b", "password": "secret"}],
        "parameters": [],
    },
    {
        "title": "x", "preconditions": [],
        "steps": [{"action": "a", "expected_result": "b"}],
        "parameters": [{"name": "Password", "is_secret": True, "value": "secret"}],
    },
])
def test_service_rejects_malformed_or_value_bearing_context_without_provider_call(bad_context):
    provider = FakeStructuredProvider()

    with pytest.raises(ValueError):
        generate_automation_test_draft(provider, bad_context)

    assert provider.kwargs is None


def test_service_converts_provider_failures_to_safe_error():
    provider = FakeStructuredProvider(error=RuntimeError("private prompt text"))

    with pytest.raises(AIProviderError) as error:
        generate_automation_test_draft(provider, context())

    assert "private prompt text" not in str(error.value)


def test_service_rejects_invalid_provider_response():
    provider = FakeStructuredProvider(response={"not": "a valid draft"})

    with pytest.raises(ValueError):
        generate_automation_test_draft(provider, context())
