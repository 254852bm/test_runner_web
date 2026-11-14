"""Provider-independent orchestration for AI automation-code drafts."""

from .automation_schemas import (
    automation_test_draft_response_format,
    validate_automation_test_draft,
)
from .provider import AIProviderError
from .automation_prompts import AUTOMATION_SYSTEM_PROMPT, build_automation_user_prompt


MAX_AUTOMATION_CONTEXT_LENGTH = 12_000


def generate_automation_test_draft(provider, test_case_context):
    """Generate a validated code draft; never persist or execute generated code."""
    if not isinstance(test_case_context, dict):
        raise ValueError("Не удалось подготовить данные тест-кейса.")

    required = {"title", "preconditions", "steps", "parameters"}
    if set(test_case_context) != required:
        raise ValueError("Данные тест-кейса имеют неверный формат.")
    title = test_case_context["title"]
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError("У тест-кейса должно быть корректное название.")

    preconditions = test_case_context["preconditions"]
    if not isinstance(preconditions, list) or len(preconditions) > 10:
        raise ValueError("Предусловия имеют неверный формат.")
    if any(not isinstance(value, str) or len(value) > 1000 for value in preconditions):
        raise ValueError("Текст предусловий имеет неверный формат.")

    steps = test_case_context["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
        raise ValueError("В тест-кейсе должно быть от 1 до 30 шагов.")
    normalized_steps = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or set(step) != {"action", "expected_result"}:
            raise ValueError(f"Шаг {index} имеет неверный формат.")
        action = step["action"]
        expected = step["expected_result"]
        if not isinstance(action, str) or not action.strip() or len(action) > 1000:
            raise ValueError(f"Действие шага {index} имеет неверный формат.")
        if not isinstance(expected, str) or len(expected) > 1000:
            raise ValueError(f"Ожидаемый результат шага {index} имеет неверный формат.")
        normalized_steps.append({
            "action": action.strip(),
            "expected_result": expected.strip(),
        })

    parameters = test_case_context["parameters"]
    if not isinstance(parameters, list) or len(parameters) > 100:
        raise ValueError("Параметры тест-кейса имеют неверный формат.")
    safe_parameters = []
    for item in parameters:
        if not isinstance(item, dict) or set(item) != {"name", "is_secret"}:
            raise ValueError("В контексте параметров не должно быть значений.")
        if not isinstance(item["name"], str) or not item["name"].strip() or len(item["name"]) > 120:
            raise ValueError("Имя параметра имеет неверный формат.")
        if not isinstance(item["is_secret"], bool):
            raise ValueError("Признак секретного параметра имеет неверный формат.")
        safe_parameters.append({
            "name": item["name"].strip(),
            "is_secret": item["is_secret"],
        })

    safe_context = {
        "title": title.strip(),
        "preconditions": [value.strip() for value in preconditions],
        "steps": normalized_steps,
        "parameters": safe_parameters,
    }
    prompt = build_automation_user_prompt(safe_context)
    if len(prompt) > MAX_AUTOMATION_CONTEXT_LENGTH:
        raise ValueError("Тест-кейс слишком большой для подготовки автотеста.")

    try:
        raw_draft = provider.generate_structured(
            system_prompt=AUTOMATION_SYSTEM_PROMPT,
            user_prompt=prompt,
            response_format=automation_test_draft_response_format(),
        )
    except AIProviderError:
        raise
    except Exception as error:
        raise AIProviderError(
            "Не удалось подготовить черновик автотеста. Попробуйте позже."
        ) from error

    return validate_automation_test_draft(raw_draft)
