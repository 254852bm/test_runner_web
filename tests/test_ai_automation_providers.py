import json

from app.ai.automation_schemas import automation_test_draft_response_format
from app.ai.automation_prompts import AUTOMATION_SYSTEM_PROMPT, build_automation_user_prompt
from app.ai.provider import YandexAIStudioConfig, YandexAIStudioProvider
from app.ai.local_provider import OllamaLocalProvider


def sample_draft():
    return {
        "summary": "Черновик.",
        "target_profile": {
            "language": "java", "framework": "junit5", "test_type": "api"
        },
        "files": [{"path": "LoginTest.java", "content": "class LoginTest {}"}],
        "assumptions": [], "open_questions": [], "todo_items": [],
        "coverage_notes": [],
    }


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.data


def test_yandex_provider_supports_structured_automation_prompt():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(json.dumps({
            "choices": [{"message": {"content": json.dumps(sample_draft())}}]
        }).encode())

    provider = YandexAIStudioProvider(
        YandexAIStudioConfig("api-key", "folder", "gpt://folder/model/latest"),
        opener=opener,
    )
    result = provider.generate_structured(
        system_prompt=AUTOMATION_SYSTEM_PROMPT,
        user_prompt=build_automation_user_prompt({
            "title": "Вход", "preconditions": [], "steps": [], "parameters": []
        }),
        response_format=automation_test_draft_response_format(),
    )

    body = json.loads(captured["request"].data.decode())
    assert result == sample_draft()
    assert body["response_format"]["json_schema"]["name"] == "automation_test_draft"
    assert body["store"] is False
    assert captured["request"].get_header("X-data-logging-enabled") == "false"


def test_ollama_provider_supports_strict_automation_schema():
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        return FakeResponse(json.dumps({
            "message": {"content": json.dumps(sample_draft())}
        }).encode())

    provider = OllamaLocalProvider(model="test-model", opener=opener)
    result = provider.generate_structured(
        system_prompt=AUTOMATION_SYSTEM_PROMPT,
        user_prompt="test prompt",
        response_format=automation_test_draft_response_format(),
    )

    body = json.loads(captured["request"].data.decode())
    assert result == sample_draft()
    assert body["format"]["additionalProperties"] is False
    assert body["format"]["properties"]["files"]["type"] == "array"
