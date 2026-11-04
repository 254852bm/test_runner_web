import pytest
from cryptography.fernet import Fernet

from app import create_app
from app.test_data_crypto import (
    SecretEncryptionUnavailable,
    decrypt_secret_values,
    encrypt_secret_values,
)


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-session-secret",
        "TEST_DATA_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "INSTANCE_PATH": str(instance_path),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'crypto.sqlite'}",
    })
    with app.app_context():
        yield app


def test_secret_values_are_encrypted_and_round_trip(app):
    secret_values = {
        "password": "do-not-store-in-plaintext",
        "api_token": "token-value",
    }
    with app.app_context():
        encrypted = encrypt_secret_values(secret_values)
        assert encrypted
        assert "do-not-store-in-plaintext" not in encrypted
        assert "token-value" not in encrypted
        assert decrypt_secret_values(encrypted) == secret_values


def test_empty_secret_values_do_not_create_ciphertext(app):
    with app.app_context():
        assert encrypt_secret_values({}) is None
        assert decrypt_secret_values(None) == {}


def test_encryption_fails_closed_when_key_is_missing(app):
    app.config["TEST_DATA_ENCRYPTION_KEY"] = ""
    with app.app_context():
        with pytest.raises(SecretEncryptionUnavailable, match="не настроен"):
            encrypt_secret_values({"password": "secret"})


def test_decryption_fails_closed_when_key_is_wrong(app):
    with app.app_context():
        encrypted = encrypt_secret_values({"password": "secret"})
        app.config["TEST_DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
        with pytest.raises(SecretEncryptionUnavailable, match="Не удалось расшифровать"):
            decrypt_secret_values(encrypted)


def test_encryption_rejects_non_mapping_values(app):
    with app.app_context():
        with pytest.raises(ValueError, match="должны быть объектом"):
            encrypt_secret_values(["not", "a", "mapping"])
