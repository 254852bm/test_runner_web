import json

import pytest

from app.ai.local_provider import OllamaLocalProvider
from app.ai.provider import AIProviderError


def _valid_draft():
    return {
        "title": "Локальная проверка",
        "preconditions": [],
        "steps": [{"action": "Открыть страницу", "expected_result": "Страница открыта"}],
        "test_type": "positive",
        "priority": "medium",
        "assumptions": [],
        "open_questions": [],
    }


def test_ollama_adapter_uses_local_endpoint_and_json_schema():
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps({
                "message": {"content": json.dumps(_valid_draft(), ensure_ascii=False)}
            }).encode("utf-8")

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return Response()

    provider = OllamaLocalProvider(
        model="qwen2.5:3b", opener=opener, timeout_seconds=45
    )
    result = provider.generate("Проверить вход")

    assert result == _valid_draft()
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["timeout"] == 45
    assert captured["body"]["stream"] is False
    assert captured["body"]["format"]["type"] == "object"
    assert "Проверить вход" in captured["body"]["messages"][1]["content"]


@pytest.mark.parametrize("url", [
    "https://example.com",
    "http://192.168.1.10:11434",
    "http://127.0.0.1:11434/api/chat",
])
def test_ollama_adapter_rejects_non_loopback_or_ambiguous_urls(url):
    with pytest.raises(ValueError):
        OllamaLocalProvider(model="qwen2.5:3b", base_url=url)


def test_ollama_adapter_hides_transport_errors():
    def opener(request, timeout):
        raise OSError("sensitive local path /home/user/private")

    provider = OllamaLocalProvider(model="qwen2.5:3b", opener=opener)
    with pytest.raises(AIProviderError) as error:
        provider.generate("private requirement")
    assert "private requirement" not in str(error.value)
    assert "/home/user/private" not in str(error.value)
