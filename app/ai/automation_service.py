"""Provider-independent orchestration for AI automation-code drafts."""

from .automation_schemas import validate_automation_test_draft
from .schemas import MAX_REQUIREMENT_LENGTH
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
    if not isinstance(test_case_context["title"], str) or not test_case_context["title"].strip():
        raise ValueError("У тест-кейса должно быть название.")
    if not isinstance(test_case_context["preconditions"], list):
        raise ValueError("Предусловия имеют неверный формат.")
    if not isinstance(test_case_context["steps"], list) or not test_case_context["steps"]:
        raise ValueError("В тест-кейсе должны быть шаги.")
    if not isinstance(test_case_context["parameters"], list):
        raise ValueError("Параметры тест-кейса имеют неверный формат.")

    # The route is responsible for excluding secret values. This service accepts
    # parameter names and secret flags only, and rejects value-bearing fields.
    safe_parameters = []
    for item in test_case_context["parameters"]:
        if not isinstance(item, dict) or set(item) != {"name", "is_secret"}:
            raise ValueError("В контексте параметров не должно быть значений.")
        if not isinstance(item["name"], str) or not item["name"].strip():
            raise ValueError("Имя параметра имеет неверный формат.")
        if not isinstance(item["is_secret"], bool):
            raise ValueError("Признак секретного параметра имеет неверный формат.")
        safe_parameters.append({
            "name": item["name"].strip(),
            "is_secret": item["is_secret"],
        })

    safe_context = {
        "title": test_case_context["title"].strip(),
        "preconditions": test_case_context["preconditions"],
        "steps": test_case_context["steps"],
        "parameters": safe_parameters,
    }
    prompt = build_automation_user_prompt(safe_context)
    if len(prompt) > MAX_AUTOMATION_CONTEXT_LENGTH:
        raise ValueError("Тест-кейс слишком большой для подготовки автотеста.")

    try:
        raw_draft = provider.generate_structured(
            system_prompt=AUTOMATION_SYSTEM_PROMPT,
            user_prompt=prompt,
            response_format=__import__(
                "app.ai.automation_schemas", fromlist=["automation_test_draft_response_format"]
            ).automation_test_draft_response_format(),
        )
    except AIProviderError:
        raise
    except Exception as error:
        raise AIProviderError(
            "Не удалось подготовить черновик автотеста. Попробуйте позже."
        ) from error

    return validate_automation_test_draft(raw_draft)
