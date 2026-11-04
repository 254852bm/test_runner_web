"""Shared schema and strict validation for AI-generated manual test drafts."""

from copy import deepcopy


MAX_TITLE_LENGTH = 200
MAX_REQUIREMENT_LENGTH = 12_000
MAX_PRECONDITIONS = 10
MAX_STEPS = 30
MAX_STEP_TEXT_LENGTH = 1_000
MAX_NOTES = 10
MAX_NOTE_LENGTH = 500

TEST_CASE_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "preconditions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "expected_result": {"type": "string"},
                },
                "required": ["action", "expected_result"],
                "additionalProperties": False,
            },
        },
        "test_type": {
            "type": "string",
            "enum": ["positive", "negative", "boundary"],
        },
        "priority": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "open_questions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "title",
        "preconditions",
        "steps",
        "test_type",
        "priority",
        "assumptions",
        "open_questions",
    ],
    "additionalProperties": False,
}


def json_schema_response_format():
    """Return a fresh provider-compatible JSON Schema response_format."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "manual_test_case_draft",
            "description": "Editable draft of a manual software test case.",
            "strict": True,
            "schema": deepcopy(TEST_CASE_DRAFT_SCHEMA),
        },
    }


def _string(value, field, max_length, *, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError(f"Поле {field} должно быть текстом.")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ValueError(f"Поле {field} не должно быть пустым.")
    if len(normalized) > max_length:
        raise ValueError(f"Поле {field} превышает допустимую длину.")
    return normalized


def _string_list(value, field, max_items, max_length):
    if not isinstance(value, list) or len(value) > max_items:
        raise ValueError(f"Поле {field} содержит недопустимое количество элементов.")
    return [
        _string(item, f"{field}[{index}]", max_length)
        for index, item in enumerate(value)
    ]


def validate_test_case_draft(payload):
    """Validate and normalize untrusted model output before it reaches the UI."""
    if not isinstance(payload, dict):
        raise ValueError("ИИ вернул результат неверного формата.")

    expected_keys = {
        "title", "preconditions", "steps", "test_type", "priority",
        "assumptions", "open_questions",
    }
    if set(payload) != expected_keys:
        raise ValueError("ИИ вернул неполный или неожиданный набор полей.")

    title = _string(payload["title"], "title", MAX_TITLE_LENGTH)
    preconditions = _string_list(
        payload["preconditions"], "preconditions", MAX_PRECONDITIONS, MAX_NOTE_LENGTH
    )
    assumptions = _string_list(
        payload["assumptions"], "assumptions", MAX_NOTES, MAX_NOTE_LENGTH
    )
    open_questions = _string_list(
        payload["open_questions"], "open_questions", MAX_NOTES, MAX_NOTE_LENGTH
    )

    steps = payload["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError("Тест-кейс должен содержать от 1 до 30 шагов.")

    normalized_steps = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) != {"action", "expected_result"}:
            raise ValueError(f"Шаг {index + 1} имеет неверный формат.")
        normalized_steps.append({
            "action": _string(
                step["action"], f"steps[{index}].action", MAX_STEP_TEXT_LENGTH
            ),
            "expected_result": _string(
                step["expected_result"],
                f"steps[{index}].expected_result",
                MAX_STEP_TEXT_LENGTH,
                allow_empty=True,
            ),
        })

    test_type = payload["test_type"]
    if test_type not in {"positive", "negative", "boundary"}:
        raise ValueError("Неизвестный тип тест-кейса.")
    priority = payload["priority"]
    if priority not in {"low", "medium", "high"}:
        raise ValueError("Неизвестный приоритет тест-кейса.")

    return {
        "title": title,
        "preconditions": preconditions,
        "steps": normalized_steps,
        "test_type": test_type,
        "priority": priority,
        "assumptions": assumptions,
        "open_questions": open_questions,
    }
