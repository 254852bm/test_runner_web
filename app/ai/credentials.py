"""Authenticated encryption helpers for per-user AI provider credentials."""

import os

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


class CredentialEncryptionError(RuntimeError):
    """Raised when the dedicated credential encryption key is unavailable or invalid."""


def _fernet():
    key = current_app.config.get("AI_CREDENTIAL_ENCRYPTION_KEY")
    if key is None:
        key = os.getenv("AI_CREDENTIAL_ENCRYPTION_KEY", "")
    if not isinstance(key, str) or not key.strip():
        raise CredentialEncryptionError(
            "Защищённое хранение ключей ИИ не настроено. Подключение недоступно."
        )
    try:
        return Fernet(key.strip().encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise CredentialEncryptionError(
            "Ключ шифрования ИИ настроен некорректно. Обратитесь к администратору."
        ) from error


def encrypt_api_key(api_key):
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("Введите API-ключ.")
    return _fernet().encrypt(api_key.strip().encode("utf-8")).decode("ascii")


def decrypt_api_key(ciphertext):
    if not isinstance(ciphertext, str) or not ciphertext:
        raise CredentialEncryptionError("Сохранённый ключ ИИ недоступен. Подключите его заново.")
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeEncodeError, UnicodeDecodeError) as error:
        raise CredentialEncryptionError(
            "Не удалось расшифровать ключ ИИ. Подключите API-ключ заново."
        ) from error
