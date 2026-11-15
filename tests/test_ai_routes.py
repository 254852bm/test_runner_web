import re
from datetime import datetime

import pytest
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import AICredential, AIGenerationAttempt, AIDraftSave, Project, TestCase, TestCaseVersion, User


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "INSTANCE_PATH": str(instance_path),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'ai-routes.sqlite'}",
        "WTF_CSRF_ENABLED": False,
        "AI_TEST_CASES_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
        user = User(email="owner@example.test", password=generate_password_hash("test-password"))
        other = User(email="other@example.test", password=generate_password_hash("test-password"))
        db.session.add_all([user, other])
        db.session.flush()
        project = Project(name="AI draft project", user_id=user.id)
        foreign_project = Project(name="Private project", user_id=other.id)
        db.session.add_all([project, foreign_project])
        db.session.commit()
        app.config["TEST_OWNER_ID"] = user.id
        app.config["TEST_PROJECT_ID"] = project.id
        app.config["TEST_FOREIGN_PROJECT_ID"] = foreign_project.id
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _login(client, app):
    with client.session_transaction() as session:
        session["_user_id"] = str(app.config["TEST_OWNER_ID"])
        session["_fresh"] = True


def _csrf_token(client, project_id):
    response = client.get(f"/project/{project_id}/ai-draft")
    assert response.status_code == 200
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
    assert match
    return match.group(1)



def _add_ai_credential(app):
    with app.app_context():
        db.session.add(AICredential(
            user_id=app.config["TEST_OWNER_ID"],
            provider="yandex_ai_studio",
            encrypted_payload="test-ciphertext",
            is_enabled=True,
            consent_version="BYOK-CONSENT-v1",
            consented_at=datetime.utcnow(),
        ))
        db.session.commit()


def test_ai_draft_page_requires_login(client, app):
    response = client.get(f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft")
    assert response.status_code == 302


def test_ai_draft_page_only_shows_own_project(client, app):
    _login(client, app)
    response = client.get(f"/project/{app.config['TEST_FOREIGN_PROJECT_ID']}/ai-draft")
    assert response.status_code == 404


def test_ai_draft_page_is_disabled_by_default(client, app):
    _login(client, app)
    response = client.get(f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft")
    assert response.status_code == 200
    assert "Интерфейс подготовлен" in response.get_data(as_text=True)
    assert "disabled" in response.get_data(as_text=True)


def test_disabled_generation_does_not_call_provider_or_write_to_database(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes

    def unexpected_provider():
        raise AssertionError("Provider must not be initialized when feature is disabled")

    monkeypatch.setattr(ai_routes, "_provider", unexpected_provider)
    monkeypatch.setattr(ai_routes, "validate_csrf", lambda token: None)
    response = client.post(
        f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft",
        data={"csrf_token": "test-token", "requirement": "Проверить авторизацию", "paid_request_confirm": "accepted"},
    )

    assert response.status_code == 200
    with app.app_context():
        assert TestCase.query.count() == 0
        assert TestCaseVersion.query.count() == 0


def test_enabled_generation_renders_editable_draft_without_database_write(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes

    app.config["AI_TEST_CASES_ENABLED"] = True
    _add_ai_credential(app)

    class FakeProvider:
        def generate(self, requirement):
            assert requirement == "Проверить авторизацию"
            return {
                "title": "Проверка авторизации",
                "preconditions": ["Пользователь зарегистрирован"],
                "steps": [{
                    "action": "Открыть форму входа",
                    "expected_result": "Форма отображается",
                }],
                "test_type": "positive",
                "priority": "high",
                "assumptions": [],
                "open_questions": [],
            }

    monkeypatch.setattr(ai_routes, "_provider", lambda: FakeProvider())
    monkeypatch.setattr(ai_routes, "validate_csrf", lambda token: None)
    response = client.post(
        f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft",
        data={"csrf_token": "test-token", "requirement": "Проверить авторизацию", "paid_request_confirm": "accepted"},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Проверка авторизации" in html
    assert 'name="step_action[]"' in html
    with app.app_context():
        assert TestCase.query.count() == 0
        assert TestCaseVersion.query.count() == 0


def test_reviewed_draft_save_creates_test_and_first_version(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes
    monkeypatch.setattr(ai_routes, "validate_csrf", lambda token: None)
    project_id = app.config["TEST_PROJECT_ID"]
    token = "test-token"
    response = client.post(
        f"/project/{project_id}/ai-draft/save",
        data={
            "csrf_token": token,
            "draft_save_token": "b" * 32,
            "title": "Проверка сохранения черновика",
            "precondition": "Пользователь зарегистрирован",
            "step_action[]": ["Открыть форму входа"],
            "step_expected[]": ["Форма отображается"],
        },
    )
    assert response.status_code == 302
    with app.app_context():
        test_case = TestCase.query.one()
        assert test_case.title == "Проверка сохранения черновика"
        assert test_case.project_id == project_id
        version = TestCaseVersion.query.one()
        assert version.test_case_id == test_case.id
        assert version.version_number == 1


def test_reviewed_draft_save_rejects_missing_csrf_token(client, app):
    _login(client, app)
    response = client.post(
        f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft/save",
        data={
            "title": "Forged test",
            "step_action[]": ["Do something"],
            "step_expected[]": ["Something happens"],
        },
    )
    assert response.status_code == 400
    with app.app_context():
        assert TestCase.query.count() == 0
        assert TestCaseVersion.query.count() == 0


def test_reviewed_draft_save_rejects_foreign_project(client, app):
    _login(client, app)
    response = client.post(
        f"/project/{app.config['TEST_FOREIGN_PROJECT_ID']}/ai-draft/save",
        data={
            "title": "Forged test",
            "step_action[]": ["Do something"],
            "step_expected[]": ["Something happens"],
        },
    )
    assert response.status_code == 404
    with app.app_context():
        assert TestCase.query.count() == 0
        assert TestCaseVersion.query.count() == 0


def test_enabled_generation_requires_per_request_payment_confirmation(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes
    app.config["AI_TEST_CASES_ENABLED"] = True
    _add_ai_credential(app)

    def unexpected_provider():
        raise AssertionError("Provider must not be called without per-request confirmation")

    monkeypatch.setattr(ai_routes, "_provider", unexpected_provider)
    monkeypatch.setattr(ai_routes, "validate_csrf", lambda token: None)
    response = client.post(
        f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft",
        data={"csrf_token": "test-token", "requirement": "Проверить авторизацию"},
    )
    assert response.status_code == 200
    assert "Перед каждым запросом подтвердите возможную оплату" in response.get_data(as_text=True)
    with app.app_context():
        assert TestCase.query.count() == 0


def test_provider_uses_only_current_users_encrypted_credential(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes
    app.config["AI_TEST_CASES_ENABLED"] = True
    app.config["YANDEX_AI_MODEL_URI"] = "gpt://test-model"
    _add_ai_credential(app)
    captured = {}

    monkeypatch.setattr(
        ai_routes,
        "decrypt_ai_credential",
        lambda **kwargs: {"api_key": "user-owned-key", "folder_id": "user-folder"},
    )

    class FakeProvider:
        def __init__(self, config):
            captured["api_key"] = config.api_key
            captured["folder_id"] = config.folder_id
            captured["model_uri"] = config.model_uri

        def generate(self, requirement):
            return {
                "title": "Проверка",
                "preconditions": [],
                "steps": [{"action": "Открыть страницу", "expected_result": "Страница открыта"}],
                "test_type": "positive",
                "priority": "medium",
                "assumptions": [],
                "open_questions": [],
            }

    monkeypatch.setattr(ai_routes, "YandexAIStudioProvider", FakeProvider)
    monkeypatch.setattr(ai_routes, "validate_csrf", lambda token: None)
    response = client.post(
        f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft",
        data={
            "csrf_token": "test-token",
            "requirement": "Проверить авторизацию",
            "paid_request_confirm": "accepted",
        },
    )
    assert response.status_code == 200
    assert captured == {
        "api_key": "user-owned-key",
        "folder_id": "user-folder",
        "model_uri": "gpt://test-model",
    }


def test_reviewed_draft_save_rejects_mismatched_step_arrays(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes
    monkeypatch.setattr(ai_routes, "validate_csrf", lambda token: None)
    response = client.post(
        f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft/save",
        data={
            "csrf_token": "test-token",
            "title": "Несогласованные шаги",
            "step_action[]": ["Первое действие", "Второе действие"],
            "step_expected[]": ["Только один результат"],
        },
    )
    assert response.status_code == 302
    with app.app_context():
        assert TestCase.query.count() == 0
        assert TestCaseVersion.query.count() == 0


def test_reviewed_draft_save_rejects_blank_action(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes
    monkeypatch.setattr(ai_routes, "validate_csrf", lambda token: None)
    response = client.post(
        f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft/save",
        data={
            "csrf_token": "test-token",
            "title": "Пустое действие",
            "step_action[]": ["   "],
            "step_expected[]": ["Ожидаемый результат"],
        },
    )
    assert response.status_code == 302
    with app.app_context():
        assert TestCase.query.count() == 0
        assert TestCaseVersion.query.count() == 0


def test_reviewed_draft_save_rejects_more_than_30_steps(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes
    monkeypatch.setattr(ai_routes, "validate_csrf", lambda token: None)
    response = client.post(
        f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft/save",
        data={
            "csrf_token": "test-token",
            "title": "Слишком много шагов",
            "step_action[]": [f"Действие {i}" for i in range(31)],
            "step_expected[]": [f"Результат {i}" for i in range(31)],
        },
    )
    assert response.status_code == 302
    with app.app_context():
        assert TestCase.query.count() == 0
        assert TestCaseVersion.query.count() == 0



def test_local_ollama_mode_generates_without_customer_key_or_paid_confirmation(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes
    app.config["AI_TEST_CASES_ENABLED"] = True
    app.config["AI_PROVIDER_MODE"] = "ollama"
    calls = []

    class FakeProvider:
        def generate(self, requirement):
            calls.append(requirement)
            return {
                "title": "Локальный черновик",
                "preconditions": [],
                "steps": [{"action": "Открыть страницу", "expected_result": "Страница открыта"}],
                "test_type": "positive",
                "priority": "medium",
                "assumptions": [],
                "open_questions": [],
            }

    monkeypatch.setattr(ai_routes, "_provider", lambda: FakeProvider())
    monkeypatch.setattr(ai_routes, "validate_csrf", lambda token: None)
    response = client.post(
        f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft",
        data={"csrf_token": "test-token", "requirement": "Локальная проверка"},
    )

    assert response.status_code == 200
    assert "Локальный черновик" in response.get_data(as_text=True)
    assert calls == ["Локальная проверка"]
    with app.app_context():
        assert AICredential.query.count() == 0
        assert AIGenerationAttempt.query.count() == 1
        assert TestCase.query.count() == 0


def test_generation_rate_limit_blocks_provider_before_outbound_call(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes
    app.config["AI_TEST_CASES_ENABLED"] = True
    app.config["AI_PROVIDER_MODE"] = "yandex"
    app.config["AI_GENERATIONS_PER_HOUR"] = 2
    _add_ai_credential(app)

    def unexpected_provider():
        raise AssertionError("Provider must not be called after rate limit is reached")

    monkeypatch.setattr(ai_routes, "_provider", unexpected_provider)
    monkeypatch.setattr(ai_routes, "validate_csrf", lambda token: None)
    with app.app_context():
        db.session.add_all([
            AIGenerationAttempt(user_id=app.config["TEST_OWNER_ID"]),
            AIGenerationAttempt(user_id=app.config["TEST_OWNER_ID"]),
        ])
        db.session.commit()

    response = client.post(
        f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft",
        data={
            "csrf_token": "test-token",
            "requirement": "Проверить авторизацию",
            "paid_request_confirm": "accepted",
        },
    )
    assert response.status_code == 200
    assert "Достигнут лимит" in response.get_data(as_text=True)
    with app.app_context():
        assert AIGenerationAttempt.query.count() == 2


def test_configured_cost_upper_bound_is_shown_before_paid_request(client, app):
    _login(client, app)
    app.config["AI_TEST_CASES_ENABLED"] = True
    _add_ai_credential(app)
    app.config["AI_PRICE_INPUT_RUB_PER_1K"] = 0.2
    app.config["AI_PRICE_OUTPUT_RUB_PER_1K"] = 0.2
    app.config["AI_MAX_COMPLETION_TOKENS"] = 3000
    response = client.get(f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft")
    assert response.status_code == 200
    assert "Примерная стоимость" in response.get_data(as_text=True)
    assert "₽" in response.get_data(as_text=True)



def test_reviewed_draft_save_is_idempotent_when_form_is_submitted_twice(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes
    monkeypatch.setattr(ai_routes, "validate_csrf", lambda token: None)
    payload = {
        "csrf_token": "test-token",
        "draft_save_token": "a" * 32,
        "title": "Проверка повторного сохранения",
        "precondition": "Пользователь создан",
        "step_action[]": ["Открыть страницу входа"],
        "step_expected[]": ["Форма входа отображается"],
    }
    url = f"/project/{app.config['TEST_PROJECT_ID']}/ai-draft/save"

    first = client.post(url, data=payload, follow_redirects=False)
    second = client.post(url, data=payload, follow_redirects=False)

    assert first.status_code == 302
    assert second.status_code == 302
    assert first.headers["Location"] == second.headers["Location"]
    with app.app_context():
        assert TestCase.query.count() == 1
        assert TestCaseVersion.query.count() == 1
        assert AIDraftSave.query.count() == 1
        assert AIDraftSave.query.first().test_case_id == TestCase.query.first().id
