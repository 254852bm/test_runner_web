"""Validation and safe placeholder substitution for test data rows."""
import re

from app.test_data_crypto import decrypt_secret_values, encrypt_secret_values

_PLACEHOLDER_RE = re.compile(r"{{([A-Za-z_][A-Za-z0-9_]*)}}")
_ANY_PLACEHOLDER_RE = re.compile(r"{{(.*?)}}")
_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|access[_-]?key)", re.IGNORECASE
)


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


def redact_secrets(text, prepared_data):
    """Replace decrypted secret values before writing text to persistent history."""
    result = text or ""
    secret_values = prepared_data.get("secret_values", {})
    for value in sorted(
        {value for value in secret_values.values() if value},
        key=len,
        reverse=True,
    ):
        result = result.replace(value, "••••••")
    return result


def prepare_test_data(test_case, dataset, row):
    """Validate, decrypt and render one row; snapshots keep secrets encrypted."""
    if dataset.test_case_id != test_case.id:
        raise ValueError("Набор данных не относится к выбранному тест-кейсу.")
    if row.dataset_id != dataset.id:
        raise ValueError("Строка данных не относится к выбранному набору.")

    columns = list(dataset.columns)
    keys = [column.key for column in columns]
    if any(not isinstance(key, str) or not _KEY_RE.fullmatch(key) for key in keys):
        raise ValueError("Некорректное имя переменной в наборе данных.")
    if len(keys) != len(set(keys)):
        raise ValueError("В наборе есть повторяющиеся имена переменных.")

    secret_keys = {
        column.key for column in columns
        if column.is_secret or _SENSITIVE_KEY_RE.search(column.key or "")
    }
    unmarked_sensitive = {
        column.key for column in columns
        if _SENSITIVE_KEY_RE.search(column.key or "") and not column.is_secret
    }
    if unmarked_sensitive:
        raise ValueError(
            "Колонки с паролями, токенами и ключами должны быть отмечены как секретные."
        )

    raw_values = row.values_json or {}
    if not isinstance(raw_values, dict):
        raise ValueError("Некорректный формат значений строки тестовых данных.")
    allowed_keys = set(keys)
    if set(raw_values) - allowed_keys:
        raise ValueError("В строке есть значения для неизвестных колонок.")
    if set(raw_values) & secret_keys:
        raise ValueError(
            "В секретной колонке обнаружено незашифрованное значение. "
            "Сохраните его заново через защищённую форму."
        )

    ordinary_keys = allowed_keys - secret_keys
    values = {key: _text(raw_values.get(key)) for key in ordinary_keys}
    secret_values = decrypt_secret_values(row.encrypted_values_json)
    if set(secret_values) - secret_keys:
        raise ValueError("В зашифрованной строке есть неизвестные секретные поля.")
    secret_values = {key: _text(secret_values.get(key)) for key in secret_keys}
    values.update(secret_values)

    step_items = sorted(list(test_case.step_items), key=lambda item: item.position)
    source_texts = [test_case.precondition or ""]
    for step in step_items:
        source_texts.extend([step.action or "", step.expected_result or ""])

    used_keys = set()
    for source in source_texts:
        for match in _ANY_PLACEHOLDER_RE.finditer(source or ""):
            if not _KEY_RE.fullmatch(match.group(1)):
                raise ValueError(
                    "Некорректный формат переменной. Используйте {{variable_name}}."
                )
        used_keys.update(_placeholders(source))

    unknown_placeholders = used_keys - allowed_keys
    if unknown_placeholders:
        names = ", ".join(sorted(unknown_placeholders))
        raise ValueError(f"В тест-кейсе используются неизвестные переменные: {names}.")

    missing_values = [
        key for key in sorted(used_keys) if not values.get(key, "").strip()
    ]
    if missing_values:
        names = ", ".join(missing_values)
        raise ValueError(f"Не заполнены значения переменных: {names}.")

    rendered_steps = []
    redacted_steps = []
    for step in step_items:
        action = _substitute(step.action, values)
        expected = _substitute(step.expected_result, values)
        rendered_steps.append({
            "step_id": step.id,
            "action": action,
            "expected_result": expected,
        })
        redacted_steps.append({
            "step_id": step.id,
            "action": redact_secrets(action, {"secret_values": secret_values}),
            "expected_result": redact_secrets(expected, {"secret_values": secret_values}),
        })

    return {
        "precondition": _substitute(test_case.precondition, values),
        "steps": rendered_steps,
        "redacted_steps": redacted_steps,
        "values_snapshot": {key: values[key] for key in ordinary_keys},
        "encrypted_values_snapshot": encrypt_secret_values(secret_values),
        "secret_keys": sorted(secret_keys),
        "secret_values": secret_values,
        "dataset_name_snapshot": dataset.name,
        "row_name_snapshot": row.name,
    }
