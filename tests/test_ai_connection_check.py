import json
import urllib.error

import pytest

from app.ai.connection_check import (
    AIConnectionCheckError,
    check_yandex_connection,
)


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.payload[:limit]


def test_check_lists_models_without_sending_prompt():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        captured["data"] = request.data
        return FakeResponse(json.dumps({
            "object": "list",
            "data": [{"id": "model-1", "object": "model"}],
        }).encode())

    count = check_yandex_connection(
        api_key="dummy-secret", folder_id="folder-123", opener=opener
    )
    assert count == 1
    assert captured["url"] == "https://ai.api.cloud.yandex.net/v1/models"
    assert captured["method"] == "GET"
    assert captured["data"] is None
    assert captured["headers"]["Authorization"] == "Api-key dummy-secret"
    assert captured["headers"]["X-project"] == "folder-123"


def test_check_maps_auth_error_without_exposing_provider_body():
    def opener(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", {}, None
        )

    with pytest.raises(AIConnectionCheckError, match="отклонил ключ"):
        check_yandex_connection(
            api_key="dummy-secret", folder_id="folder-123", opener=opener
        )


def test_check_rejects_unexpected_response():
    with pytest.raises(AIConnectionCheckError, match="неожиданный формат"):
        check_yandex_connection(
            api_key="dummy-secret",
            folder_id="folder-123",
            opener=lambda request, timeout: FakeResponse(b'{"unexpected": true}'),
        )


def test_check_does_not_accept_empty_credentials():
    with pytest.raises(AIConnectionCheckError):
        check_yandex_connection(api_key="", folder_id="folder-123")
