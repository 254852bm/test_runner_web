"""Minimal, non-generative connectivity check for Yandex AI Studio."""
import json
import urllib.error
import urllib.request


class AIConnectionCheckError(Exception):
    """Safe message suitable for display; never contains credentials or bodies."""


def check_yandex_connection(*, api_key, folder_id, opener=None, timeout_seconds=10):
    if not api_key or not folder_id:
        raise AIConnectionCheckError("Не настроены API-ключ или Folder ID.")
    request = urllib.request.Request(
        "https://ai.api.cloud.yandex.net/v1/models",
        headers={
            "Authorization": f"Api-Key {api_key}",
            "x-project": folder_id,
            "Accept": "application/json",
        },
        method="GET",
    )
    open_request = opener or urllib.request.urlopen
    try:
        with open_request(request, timeout=timeout_seconds) as response:
            raw = response.read(256_001)
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as error:
        # Do not expose provider response bodies, which may contain sensitive data.
        if error.code in (401, 403):
            raise AIConnectionCheckError(
                "Yandex отклонил ключ или у ключа нет необходимых прав для каталога."
            ) from None
        raise AIConnectionCheckError(
            "Yandex AI Studio временно недоступна. Попробуйте позже."
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AIConnectionCheckError(
            "Не удалось связаться с Yandex AI Studio. Проверьте сеть и попробуйте позже."
        ) from None
    if status != 200:
        raise AIConnectionCheckError("Yandex AI Studio вернула неожиданный ответ.")
    if len(raw) > 256_000:
        raise AIConnectionCheckError("Ответ Yandex AI Studio превышает допустимый размер.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise AIConnectionCheckError("Yandex AI Studio вернула некорректный ответ.") from None
    if not isinstance(payload, dict) or payload.get("object") != "list" or not isinstance(payload.get("data"), list):
        raise AIConnectionCheckError("Yandex AI Studio вернула неожиданный формат списка моделей.")
    return len(payload["data"])
