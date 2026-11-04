"""Provider-independent orchestration and input validation."""

from .provider import AIProviderError
from .schemas import MAX_REQUIREMENT_LENGTH, validate_test_case_draft


def generate_test_case_draft(provider, requirement):
    """Generate and validate a draft; this function never writes to the database."""
    if not isinstance(requirement, str):
        raise ValueError("Введите текст требования.")
    normalized_requirement = requirement.strip()
    if not normalized_requirement:
        raise ValueError("Введите текст требования.")
    if len(normalized_requirement) > MAX_REQUIREMENT_LENGTH:
        raise ValueError(
            f"Требование слишком длинное (максимум {MAX_REQUIREMENT_LENGTH} символов)."
        )

    try:
        raw_draft = provider.generate(normalized_requirement)
    except AIProviderError:
        raise
    except Exception as error:
        # Keep unexpected provider details (which could include request data) private.
        raise AIProviderError(
            "Не удалось подготовить черновик. Попробуйте позже."
        ) from error

    return validate_test_case_draft(raw_draft)
