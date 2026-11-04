from cryptography.fernet import Fernet

from app import create_app
from app.ai.credentials import (
    CredentialEncryptionError,
    decrypt_api_key,
    encrypt_api_key,
)


def _app(tmp_path, key=None):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    config = {
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "INSTANCE_PATH": str(instance_path),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'credentials.sqlite'}",
        "AI_CREDENTIAL_ENCRYPTION_KEY": key or "",
    }
    return create_app(config)


def test_api_key_is_encrypted_and_can_be_decrypted(tmp_path):
    key = Fernet.generate_key().decode("ascii")
    app = _app(tmp_path, key)

    with app.app_context():
        encrypted = encrypt_api_key("  secret-provider-key  ")
        assert encrypted != "secret-provider-key"
        assert "secret-provider-key" not in encrypted
        assert decrypt_api_key(encrypted) == "secret-provider-key"


def test_encryption_is_unavailable_without_dedicated_key(tmp_path):
    app = _app(tmp_path)

    with app.app_context():
        try:
            encrypt_api_key("secret-provider-key")
        except CredentialEncryptionError as error:
            assert "не настроено" in str(error)
        else:
            raise AssertionError("Encryption must fail closed without a key")


def test_invalid_ciphertext_fails_closed(tmp_path):
    key = Fernet.generate_key().decode("ascii")
    app = _app(tmp_path, key)

    with app.app_context():
        try:
            decrypt_api_key("not-a-valid-ciphertext")
        except CredentialEncryptionError as error:
            assert "расшифровать" in str(error)
        else:
            raise AssertionError("Invalid ciphertext must not be accepted")
