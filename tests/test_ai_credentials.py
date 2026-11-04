import pytest
from cryptography.fernet import Fernet

from app import create_app
from app.ai_credentials import (
    AICredentialEncryptionError,
    decrypt_ai_credential,
    encrypt_ai_credential,
)


@pytest.fixture()
def app(tmp_path):
    instance = tmp_path / "instance"
    instance.mkdir()
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "test-session-key",
        "AI_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "INSTANCE_PATH": str(instance),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'credentials.sqlite'}",
    })


def test_credential_is_encrypted_and_round_trips(app):
    secret = "yandex-api-key-do-not-leak"
    with app.app_context():
        encrypted = encrypt_ai_credential(
            user_id=42, provider="yandex_ai_studio",
            api_key=secret, folder_id="folder-123"
        )
        assert secret not in encrypted
        assert "folder-123" not in encrypted
        assert decrypt_ai_credential(
            user_id=42, provider="yandex_ai_studio", encrypted_payload=encrypted
        ) == {"api_key": secret, "folder_id": "folder-123"}


def test_credential_cannot_be_decrypted_by_another_user(app):
    with app.app_context():
        encrypted = encrypt_ai_credential(
            user_id=42, provider="yandex_ai_studio",
            api_key="secret", folder_id="folder-123"
        )
        with pytest.raises(AICredentialEncryptionError, match="не принадлежит"):
            decrypt_ai_credential(
                user_id=43, provider="yandex_ai_studio", encrypted_payload=encrypted
            )


def test_credential_cannot_be_used_for_another_provider(app):
    with app.app_context():
        encrypted = encrypt_ai_credential(
            user_id=42, provider="yandex_ai_studio",
            api_key="secret", folder_id="folder-123"
        )
        with pytest.raises(AICredentialEncryptionError, match="не принадлежит"):
            decrypt_ai_credential(
                user_id=42, provider="other", encrypted_payload=encrypted
            )


def test_missing_encryption_key_fails_closed(app):
    app.config["AI_CREDENTIAL_ENCRYPTION_KEY"] = ""
    with app.app_context():
        with pytest.raises(AICredentialEncryptionError, match="не настроен"):
            encrypt_ai_credential(
                user_id=42, provider="yandex_ai_studio",
                api_key="secret", folder_id="folder-123"
            )


def test_invalid_api_key_is_rejected(app):
    with app.app_context():
        with pytest.raises(ValueError):
            encrypt_ai_credential(
                user_id=42, provider="yandex_ai_studio",
                api_key="\nsecret", folder_id="folder-123"
            )


def test_missing_folder_id_is_rejected(app):
    with app.app_context():
        with pytest.raises(ValueError, match="Folder ID"):
            encrypt_ai_credential(
                user_id=42, provider="yandex_ai_studio",
                api_key="secret", folder_id=""
            )
