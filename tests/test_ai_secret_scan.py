import pytest
from app.ai.secret_scan import find_suspected_secret_fields

@pytest.mark.parametrize("text", [
    'password = "correct-horse-battery-staple"',
    'password = "my real secret value with spaces"',
    '"password": "json-secret-value-with-spaces"',
    "'client_secret': 'another long secret value'",
    "api_key: sk_live_1234567890abcdef",
    "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
    "-----BEGIN PRIVATE KEY-----",
    "token=ghp_abcdefghijklmnopqrstuvwxyz123456",
    "client_secret: very-long-secret-value",
])
def test_scanner_detects_likely_credentials_without_returning_values(text):
    findings = find_suspected_secret_fields({"steps": [{"action": text}]})
    assert findings == ["steps[0].action"]
    assert "correct-horse" not in str(findings)

@pytest.mark.parametrize("text", [
    "Открыть форму входа",
    "Использовать {{PASSWORD}} из переменной окружения",
    "Передать пароль в поле формы",
    "api_key={{API_KEY}}",
    "Проверить сообщение об ошибке авторизации",
    "Password is required before submitting the form",
    "Access token is refreshed after login",
])
def test_scanner_allows_normal_text_and_explicit_placeholders(text):
    assert find_suspected_secret_fields({"text": text}) == []

def test_scanner_reports_only_field_paths_for_nested_output():
    findings = find_suspected_secret_fields({
        "files": [{"path": "LoginTest.java", "content": 'String password = "do-not-leak-this-value";'}],
        "summary": "Черновик",
    })
    assert findings == ["files[0].content"]
    assert "do-not-leak" not in str(findings)

@pytest.mark.parametrize("text", [
    "token = abcdefghijklmnopqrstuvwxyz123456",
    "secret: very-long-secret-value",
    "Open https://tester:supersecret@example.test/login",
    "eyJabcdefghijk.abcdefghijk.abcdefghijk",
])
def test_scanner_detects_additional_credential_shapes(text):
    assert find_suspected_secret_fields({"text": text}) == ["text"]
