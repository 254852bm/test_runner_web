import copy

import pytest

from app.ai.automation_schemas import (
    automation_test_draft_response_format,
    validate_automation_test_draft,
)


def valid_automation_draft():
    return {
        "summary": "Черновик проверки успешного входа.",
        "target_profile": {
            "language": "java",
            "framework": "junit5",
            "test_type": "api",
        },
        "files": [{
            "path": "src/test/java/example/LoginTest.java",
            "content": "class LoginTest { /* TODO: add project-specific client */ }",
        }],
        "assumptions": ["Проект использует JUnit 5."],
        "open_questions": ["Какой API-клиент используется в проекте?"],
        "todo_items": ["Настроить адрес тестового стенда."],
        "coverage_notes": ["Покрывает шаги входа из ручного тест-кейса."],
    }


def test_validator_accepts_java_junit5_text_draft():
    result = validate_automation_test_draft(valid_automation_draft())

    assert result["target_profile"] == {
        "language": "java", "framework": "junit5", "test_type": "api"
    }
    assert result["files"][0]["path"].endswith("LoginTest.java")


def test_schema_is_strict_and_requires_every_field():
    schema = automation_test_draft_response_format()["json_schema"]["schema"]

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["target_profile"]["additionalProperties"] is False


@pytest.mark.parametrize("path", [
    "../LoginTest.java",
    "/tmp/LoginTest.java",
    "src\\test\\LoginTest.java",
    "src/test/../../LoginTest.java",
    "build.gradle",
    ".env",
    ".hidden/LoginTest.java",
    "src/" + chr(1) + "LoginTest.java",
    "src/test/run.sh",
    "src/CON.java",
    "src/nul.md",
    "src/trailing.java ",
    "src/trailing./LoginTest.java",
    "src/" + chr(127) + "LoginTest.java",
])
def test_validator_rejects_unsafe_or_unsupported_paths(path):
    payload = valid_automation_draft()
    payload["files"][0]["path"] = path

    with pytest.raises(ValueError):
        validate_automation_test_draft(payload)


def test_validator_accepts_spaces_before_extension():
    payload = valid_automation_draft()
    payload["files"][0]["path"] = "src/test/Login draft.java"

    result = validate_automation_test_draft(payload)

    assert result["files"][0]["path"] == "src/test/Login draft.java"


def test_validator_rejects_duplicate_paths():
    payload = valid_automation_draft()
    payload["files"].append(copy.deepcopy(payload["files"][0]))

    with pytest.raises(ValueError, match="повторяющиеся"):
        validate_automation_test_draft(payload)


def test_validator_rejects_unexpected_fields():
    payload = valid_automation_draft()
    payload["server_command"] = "do not execute"

    with pytest.raises(ValueError, match="неполный или неожиданный"):
        validate_automation_test_draft(payload)


def test_validator_rejects_non_java_profiles():
    payload = valid_automation_draft()
    payload["target_profile"]["language"] = "python"

    with pytest.raises(ValueError, match="Java"):
        validate_automation_test_draft(payload)


def test_validator_rejects_empty_file_content():
    payload = valid_automation_draft()
    payload["files"][0]["content"] = "  "

    with pytest.raises(ValueError, match="не должно быть пустым"):
        validate_automation_test_draft(payload)


def test_validator_rejects_oversized_file_content():
    payload = valid_automation_draft()
    payload["files"][0]["content"] = "x" * 20_001

    with pytest.raises(ValueError, match="длину"):
        validate_automation_test_draft(payload)


@pytest.mark.parametrize("value", [[], {}, None])
def test_validator_rejects_non_string_profile_fields(value):
    payload = valid_automation_draft()
    payload["target_profile"]["test_type"] = value

    with pytest.raises(ValueError, match="профиль"):
        validate_automation_test_draft(payload)


def test_validator_rejects_duplicate_paths_case_insensitively():
    payload = valid_automation_draft()
    payload["files"].append({
        "path": "src/test/java/example/logintest.java",
        "content": "class LoginTest {}",
    })

    with pytest.raises(ValueError, match="повторяющиеся"):
        validate_automation_test_draft(payload)
