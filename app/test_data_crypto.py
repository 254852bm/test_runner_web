"""Authenticated encryption helpers for sensitive test-data values.

Secret data is never silently stored as plaintext. The encryption key is a
separate Fernet key supplied through TEST_DATA_ENCRYPTION_KEY.
"""
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app, has_app_context


class SecretEncryptionUnavailable(ValueError):
    """Raised when encrypted test-data storage is not configured safely."""


def _cipher():
    # Inside Flask, app config is authoritative. Falling back to the process
    # environment here would make an explicitly empty test/deployment config
    # unexpectedly inherit a key and would make "disabled" impossible to test.
    if has_app_context():
        key = current_app.config.get('TEST_DATA_ENCRYPTION_KEY', '') or ''
    else:
        key = os.getenv('TEST_DATA_ENCRYPTION_KEY', '')
    if isinstance(key, str):
        key = key.encode('ascii', errors='ignore')
    if not key:
        raise SecretEncryptionUnavailable(
            'TEST_DATA_ENCRYPTION_KEY не настроен; секретные данные недоступны.'
        )
    try:
        return Fernet(key)
    except (TypeError, ValueError):
        raise SecretEncryptionUnavailable(
            'TEST_DATA_ENCRYPTION_KEY имеет неверный формат. '
            'Ожидается ключ Fernet из 32 случайных байт в URL-safe Base64.'
        ) from None


def encrypt_secret_values(values):
    """Encrypt a mapping and return a Fernet token string.

    Empty mappings are represented by None. No plaintext fallback is allowed.
    """
    if not values:
        return None
    if not isinstance(values, dict):
        raise ValueError('Секретные значения должны быть объектом.')
    try:
        payload = json.dumps(
            values, ensure_ascii=False, separators=(',', ':'), sort_keys=True
        ).encode('utf-8')
    except (TypeError, ValueError):
        raise ValueError('Секретные значения имеют неподдерживаемый формат.') from None
    return _cipher().encrypt(payload).decode('ascii')


def decrypt_secret_values(encrypted_payload):
    """Decrypt a Fernet token. Missing/invalid keys fail closed."""
    if not encrypted_payload:
        return {}
    try:
        payload = _cipher().decrypt(encrypted_payload.encode('ascii'))
        values = json.loads(payload.decode('utf-8'))
    except SecretEncryptionUnavailable:
        raise
    except (InvalidToken, UnicodeError, ValueError, TypeError):
        raise SecretEncryptionUnavailable(
            'Не удалось расшифровать секретные тестовые данные. '
            'Проверьте ключ шифрования; данные не были изменены.'
        ) from None
    if not isinstance(values, dict):
        raise SecretEncryptionUnavailable(
            'Зашифрованные тестовые данные имеют неверный формат.'
        )
    return values
