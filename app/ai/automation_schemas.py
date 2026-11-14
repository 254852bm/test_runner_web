"""Strict validation for AI-generated automation-test code drafts.

This module validates text-only draft output. It never executes generated code.
"""

from pathlib import PurePosixPath


MAX_AUTOMATION_FILES = 5
MAX_AUTOMATION_FILE_CHARS = 20_000
MAX_AUTOMATION_SUMMARY = 1_000
MAX_AUTOMATION_NOTES = 10
MAX_AUTOMATION_NOTE_CHARS = 500
ALLOWED_AUTOMATION_EXTENSIONS = {".java", ".md"}
ALLOWED_TEST_TYPES = {"api", "ui", "unit_service"}


AUTOMATION_TEST_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "target_profile": {
            "type": "object",
            "properties": {
                "language": {"type": "string", "enum": ["java"]},
                "framework": {"type": "string", "enum": ["junit5"]},
                "test_type": {"type": "string", "enum": ["api", "ui", "unit_service"]},
            },
            "required": ["language", "framework", "test_type"],
            "additionalProperties": False,
        },
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "todo_items": {"type": "array", "items": {"type": "string"}},
        "coverage_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "summary", "target_profile", "files", "assumptions",
        "open_questions", "todo_items", "coverage_notes",
    ],
    "additionalProperties": False,
}


def automation_test_draft_response_format():
    """Return a fresh strict JSON Schema response format."""
    from copy import deepcopy

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "automation_test_draft",
            "description": "Editable Java JUnit 5 automation test draft; never executed by the service.",
            "strict": True,
            "schema": deepcopy(AUTOMATION_TEST_DRAFT_SCHEMA),
        },
    }


def _text(value, field, limit, *, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError(f"Поле {field} должно быть текстом.")
    value = value.strip()
    if not allow_empty and not value:
        raise ValueError(f"Поле {field} не должно быть пустым.")
    if len(value) > limit:
        raise ValueError(f"Поле {field} превышает допустимую длину.")
    return value


def _notes(value, field):
    if not isinstance(value, list) or len(value) > MAX_AUTOMATION_NOTES:
        raise ValueError(f"Поле {field} содержит недопустимое количество элементов.")
    return [
        _text(item, f"{field}[{index}]", MAX_AUTOMATION_NOTE_CHARS)
        for index, item in enumerate(value)
    ]


def _safe_relative_path(value):
    path_text = _text(value, "files.path", 240)
    # Use POSIX separators in the interchange format on every platform.
    if "\\" in path_text or path_text.startswith("/") or ":" in path_text:
        raise ValueError("Путь файла должен быть безопасным относительным путём.")
    path = PurePosixPath(path_text)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Путь файла содержит недопустимый сегмент.")
    if path.suffix.lower() not in ALLOWED_AUTOMATION_EXTENSIONS:
        raise ValueError("Разрешены только файлы .java и .md.")
    if path.name.startswith("."):
        raise ValueError("Скрытые файлы не разрешены.")
    return path.as_posix()


def validate_automation_test_draft(payload):
    """Validate untrusted model output before rendering or offering export."""
    expected = {
        "summary", "target_profile", "files", "assumptions",
        "open_questions", "todo_items", "coverage_notes",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("ИИ вернул неполный или неожиданный набор полей.")

    profile = payload["target_profile"]
    if not isinstance(profile, dict) or set(profile) != {
        "language", "framework", "test_type"
    }:
        raise ValueError("ИИ вернул неверный профиль автотеста.")
    if profile["language"] != "java" or profile["framework"] != "junit5":
        raise ValueError("Пока поддерживается только Java + JUnit 5.")
    if profile["test_type"] not in ALLOWED_TEST_TYPES:
        raise ValueError("Неизвестный тип автотеста.")

    files = payload["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_AUTOMATION_FILES:
        raise ValueError(f"Черновик должен содержать от 1 до {MAX_AUTOMATION_FILES} файлов.")

    normalized_files = []
    seen_paths = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict) or set(item) != {"path", "content"}:
            raise ValueError(f"Файл {index + 1} имеет неверный формат.")
        path = _safe_relative_path(item["path"])
        if path in seen_paths:
            raise ValueError("Черновик содержит повторяющиеся пути файлов.")
        seen_paths.add(path)
        content = _text(
            item["content"], f"files[{index}].content",
            MAX_AUTOMATION_FILE_CHARS,
        )
        normalized_files.append({"path": path, "content": content})

    return {
        "summary": _text(payload["summary"], "summary", MAX_AUTOMATION_SUMMARY),
        "target_profile": {
            "language": "java",
            "framework": "junit5",
            "test_type": profile["test_type"],
        },
        "files": normalized_files,
        "assumptions": _notes(payload["assumptions"], "assumptions"),
        "open_questions": _notes(payload["open_questions"], "open_questions"),
        "todo_items": _notes(payload["todo_items"], "todo_items"),
        "coverage_notes": _notes(payload["coverage_notes"], "coverage_notes"),
    }
