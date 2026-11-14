"""Local Ollama adapter for development; no API key or provider billing."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .prompts import SYSTEM_PROMPT, build_user_prompt
from .provider import AIProviderError
from .schemas import json_schema_response_format


class OllamaLocalProvider:
    def __init__(self, *, model, base_url="http://127.0.0.1:11434", timeout_seconds=60, opener=None):
        if not model or len(model) > 120:
            raise ValueError("Укажите локальную модель Ollama.")
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Локальный Ollama должен быть доступен только через loopback HTTP.")
        if parsed.path not in ("", "/"):
            raise ValueError("Укажите адрес Ollama без пути API.")
        if not 1 <= timeout_seconds <= 180:
            raise ValueError("Таймаут локальной модели должен быть от 1 до 180 секунд.")
        self.model = model
        self.endpoint = base_url.rstrip("/") + "/api/chat"
        self.timeout_seconds = timeout_seconds
        self._opener = opener or urllib.request.urlopen

    def generate(self, requirement):
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(requirement)},
            ],
            "stream": False,
            "format": json_schema_response_format()["json_schema"]["schema"],
            "options": {"temperature": 0.2},
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read(1_000_001)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as error:
            raise AIProviderError(
                "Не удалось связаться с локальной моделью Ollama. Проверьте, что она запущена."
            ) from error
        if len(raw) > 1_000_000:
            raise AIProviderError("Локальная модель вернула слишком большой ответ.")
        try:
            payload = json.loads(raw.decode("utf-8"))
            message = payload["message"]["content"]
            if not isinstance(message, str):
                raise ValueError("Unexpected content type")
            return json.loads(message)
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise AIProviderError("Локальная модель вернула ответ неверного формата.") from error
