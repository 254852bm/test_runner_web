"""Authenticated encryption for user-supplied AI provider credentials.

The encryption key is separate from Flask sessions and test-data encryption.
Credential plaintext is returned only to the server-side provider resolver.
"""
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app, has_app_context


class AICredentialEncryptionError(ValueError):
    """Credential encryption is unavailable or ciphertext cannot be trusted."""


def _cipher():
    key = ""
    if has_app_context():
        key = current_app.config.get("AI_CREDENTIAL_ENCRYPTION_KEY", "") or ""
    if not key:
        key = os.getenv("AI_CREDENTIAL_ENCRYPTION_KEY", "")
    if not isinstance(key, str) or not key:
        raise AICredentialEncryptionError(
            "AI_CREDENTIAL_ENCRYPTION_KEY не настроен; сохранение ключа отключено."
        )
    try:
        return Fernet(key.encode("ascii"))
    except (UnicodeError, TypeError, ValueError):
        raise AICredentialEncryptionError(
            "Ключ шифрования AI-учётных данных имеет неверный формат."
        ) from None


def encrypt_ai_credential(*, user_id, provider, api_key, folder_id):
    """Encrypt and bind a credential to one user and one provider."""
    if not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("Некорректный пользователь.")
    if provider != "yandex_ai_studio":
        raise ValueError("Этот AI-провайдер пока не поддерживается.")
    if not isinstance(api_key, str):
        raise ValueError("API-ключ должен быть текстом.")
    api_key = api_key.strip()
    if not api_key or len(api_key) > 4096 or any(ord(char) < 32 for char in api_key):
        raise ValueError("Проверьте API-ключ: он пустой или имеет недопустимый формат.")
    payload = json.dumps(
        {"user_id": user_id, "provider": provider, "api_key": api_key},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _cipher().encrypt(payload).decode("ascii")


def decrypt_ai_credential(*, user_id, provider, encrypted_payload):
    """Decrypt only for the owning user and the expected provider."""
    if not encrypted_payload or not isinstance(encrypted_payload, str):
        raise AICredentialEncryptionError("Зашифрованный ключ не найден.")
    try:
        raw = _cipher().decrypt(encrypted_payload.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except AICredentialEncryptionError:
        raise
    except (InvalidToken, UnicodeError, ValueError, TypeError):
        raise AICredentialEncryptionError(
            "Не удалось расшифровать AI-ключ. Проверьте настройки шифрования."
        ) from None
    if (
        not isinstance(payload, dict)
        or payload.get("user_id") != user_id
        or payload.get("provider") != provider
        or not isinstance(payload.get("api_key"), str)
        or not payload["api_key"]
    ):
        raise AICredentialEncryptionError(
            "AI-ключ не принадлежит этому пользователю или провайдеру."
        )
    return {"api_key": payload["api_key"], "folder_id": payload["folder_id"]}
