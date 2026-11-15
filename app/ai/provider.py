"""Yandex AI Studio Chat Completions adapter (no implicit network retries)."""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import json_schema_response_format


class AIProviderError(Exception):
    """Safe, user-displayable provider error without request/response contents."""


@dataclass(frozen=True)
class YandexAIStudioConfig:
    api_key: str = field(repr=False)
    folder_id: str
    model_uri: str
    timeout_seconds: int = 25
    max_completion_tokens: int = 3_000

    def __post_init__(self):
        if not self.api_key or not self.folder_id or not self.model_uri:
            raise ValueError("Не настроены параметры подключения к Yandex AI Studio.")
        if not 1 <= self.timeout_seconds <= 60:
            raise ValueError("Таймаут AI-провайдера должен быть от 1 до 60 секунд.")
        if not 100 <= self.max_completion_tokens <= 8_000:
            raise ValueError("Некорректный лимит ответа AI-провайдера.")


class YandexAIStudioProvider:
    ENDPOINT = "https://ai.api.cloud.yandex.net/v1/chat/completions"

    def __init__(self, config, opener=None):
        self.config = config
        self._opener = opener or urllib.request.urlopen

    def generate(self, requirement):
        body = {
            "model": self.config.model_uri,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(requirement)},
            ],
            "temperature": 0.2,
            "n": 1,
            "stream": False,
            "store": False,
            "max_completion_tokens": self.config.max_completion_tokens,
            "response_format": json_schema_response_format(),
        }
        request = urllib.request.Request(
            self.ENDPOINT,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Api-Key {self.config.api_key}",
                "Content-Type": "application/json",
                "x-folder-id": self.config.folder_id,
                # Requests are logged by default in AI Studio; always opt out.
                "x-data-logging-enabled": "false",
            },
            method="POST",
        )

        try:
            with self._opener(request, timeout=self.config.timeout_seconds) as response:
                raw_response = response.read(1_000_001)
        except urllib.error.HTTPError as error:
            # Do not log or expose provider response bodies: they may echo user text.
            raise AIProviderError(
                "Сервис генерации временно недоступен. Попробуйте позже."
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AIProviderError(
                "Не удалось связаться с сервисом генерации. Попробуйте позже."
            ) from error

        if len(raw_response) > 1_000_000:
            raise AIProviderError("Сервис генерации вернул слишком большой ответ.")

        try:
            response_data = json.loads(raw_response.decode("utf-8"))
            content = response_data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Unexpected content type")
            return json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as error:
            raise AIProviderError(
                "Сервис генерации вернул ответ, который не удалось обработать."
            ) from error
