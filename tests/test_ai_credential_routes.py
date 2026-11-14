import re

import pytest
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.ai_credentials import decrypt_ai_credential
from app.models import AICredential, User


@pytest.fixture()
def app(tmp_path):
    instance = tmp_path / "instance"
    instance.mkdir()
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-session-key",
        "AI_CREDENTIAL_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "INSTANCE_PATH": str(instance),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'credential-routes.sqlite'}",
        "WTF_CSRF_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
        user = User(email="owner@example.test", password=generate_password_hash("password"))
        other = User(email="other@example.test", password=generate_password_hash("password"))
        db.session.add_all([user, other])
        db.session.commit()
        app.config["OWNER_ID"] = user.id
        app.config["OTHER_ID"] = other.id
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _form(**overrides):
    data = {
        "csrf_token": "test-token",
        "provider": "yandex_ai_studio",
        "api_key": "never-store-plaintext",
        "folder_id": "folder-123",
        "consent_version": "BYOK-CONSENT-v1",
        "paid_request_notice": "accepted",
        "consent_accepted": "accepted",
    }
    data.update(overrides)
    return data


def test_saving_key_requires_explicit_consent(client, app, monkeypatch):
    import app.ai.credential_routes as routes
    monkeypatch.setattr(routes, "validate_csrf", lambda token: None)
    _login(client, app.config["OWNER_ID"])
    response = client.post(
        "/settings/ai-credentials",
        data=_form(consent_accepted=""),
    )
    assert response.status_code == 302
    with app.app_context():
        assert AICredential.query.count() == 0


def test_saving_key_encrypts_it_without_provider_request(client, app, monkeypatch):
    import app.ai.credential_routes as routes
    monkeypatch.setattr(routes, "validate_csrf", lambda token: None)
    _login(client, app.config["OWNER_ID"])
    response = client.post("/settings/ai-credentials", data=_form())
    assert response.status_code == 302
    with app.app_context():
        credential = AICredential.query.one()
        assert "never-store-plaintext" not in credential.encrypted_payload
        assert "folder-123" not in credential.encrypted_payload
        decrypted = decrypt_ai_credential(
            user_id=app.config["OWNER_ID"],
            provider=credential.provider,
            encrypted_payload=credential.encrypted_payload,
        )
        assert decrypted == {
            "api_key": "never-store-plaintext",
            "folder_id": "folder-123",
        }
        assert credential.is_enabled is True
        assert credential.consent_version == "BYOK-CONSENT-v1"


def test_user_cannot_see_another_users_credential(client, app, monkeypatch):
    import app.ai.credential_routes as routes
    monkeypatch.setattr(routes, "validate_csrf", lambda token: None)
    _login(client, app.config["OWNER_ID"])
    client.post("/settings/ai-credentials", data=_form())
    _login(client, app.config["OTHER_ID"])
    response = client.get("/settings/ai-credentials")
    assert response.status_code == 200
    assert "never-store-plaintext" not in response.get_data(as_text=True)
    assert "ключ не подключён" in response.get_data(as_text=True).lower() or "добавить или заменить" in response.get_data(as_text=True).lower()


def test_disable_and_delete_are_post_only_and_csrf_protected(client, app):
    _login(client, app.config["OWNER_ID"])
    assert client.get("/settings/ai-credentials/delete").status_code == 405
    assert client.post("/settings/ai-credentials/delete").status_code == 400
