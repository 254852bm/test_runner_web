"""Validation and safe placeholder substitution for test data rows.

This module intentionally refuses secret columns until encrypted storage and
controlled secret retrieval are implemented. It never evaluates expressions.
"""
import re


_PLACEHOLDER_RE = re.compile(r"{{([A-Za-z_][A-Za-z0-9_]*)}}")


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ValueError("Значения тестовых данных должны быть строками или числами.")


def _placeholders(text):
    return set(_PLACEHOLDER_RE.findall(text or ""))


def _substitute(text, values):
    text = text or ""
    return _PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], text)


def prepare_test_data(test_case, dataset, row):
    """Validate ownership and return rendered text plus a safe immutable snapshot.

    Secret columns are rejected for now: accepting them before encrypted storage
    exists would silently persist credentials as plaintext in values_json.
    """
    if dataset.test_case_id != test_case.id:
        raise ValueError("Набор данных не относится к выбранному тест-кейсу.")
    if row.dataset_id != dataset.id:
        raise ValueError("Строка данных не относится к выбранному набору.")

    columns = list(dataset.columns)
    keys = [column.key for column in columns]
    if len(keys) != len(set(keys)):
        raise ValueError("В наборе есть повторяющиеся имена переменных.")

    secret_keys = [column.key for column in columns if column.is_secret]
    if secret_keys:
        raise ValueError(
            "В наборе есть секретные поля. Их использование станет доступно "
            "после подключения безопасного зашифрованного хранения."
        )

    raw_values = row.values_json or {}
    if not isinstance(raw_values, dict):
        raise ValueError("Некорректный формат значений строки тестовых данных.")

    allowed_keys = set(keys)
    unknown_value_keys = set(raw_values) - allowed_keys
    if unknown_value_keys:
        raise ValueError("В строке есть значения для неизвестных колонок.")

    # Validate all defined values, not only those referenced by the current case.
    values = {key: _text(raw_values.get(key)) for key in keys}

    step_items = sorted(list(test_case.step_items), key=lambda item: item.position)
    source_texts = [test_case.precondition or ""]
    for step in step_items:
        source_texts.extend([step.action or "", step.expected_result or ""])

    used_keys = set()
    for source in source_texts:
        used_keys.update(_placeholders(source))

    unknown_placeholders = used_keys - allowed_keys
    if unknown_placeholders:
        names = ", ".join(sorted(unknown_placeholders))
        raise ValueError(f"В тест-кейсе используются неизвестные переменные: {names}.")

    missing_values = [key for key in sorted(used_keys) if not values.get(key, "").strip()]
    if missing_values:
        names = ", ".join(missing_values)
        raise ValueError(f"Не заполнены значения переменных: {names}.")

    rendered_steps = [
        {
            "step_id": step.id,
            "action": _substitute(step.action, values),
            "expected_result": _substitute(step.expected_result, values),
        }
        for step in step_items
    ]

    # Include ordinary values as a snapshot so future edits to the row cannot
    # alter history. Secrets cannot reach this point.
    safe_snapshot = {
        key: values[key]
        for key in keys
    }

    return {
        "precondition": _substitute(test_case.precondition, values),
        "steps": rendered_steps,
        "values_snapshot": safe_snapshot,
        "dataset_name_snapshot": dataset.name,
        "row_name_snapshot": row.name,
    }
