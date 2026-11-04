import re

import pytest
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Project, TestCase, TestCaseVersion, User


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
        data={"csrf_token": "test-token", "requirement": "Проверить авторизацию"},
    )

    assert response.status_code == 200
    with app.app_context():
        assert TestCase.query.count() == 0
        assert TestCaseVersion.query.count() == 0


def test_enabled_generation_renders_editable_draft_without_database_write(client, app, monkeypatch):
    _login(client, app)
    import app.ai.routes as ai_routes

    app.config["AI_TEST_CASES_ENABLED"] = True

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
        data={"csrf_token": "test-token", "requirement": "Проверить авторизацию"},
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


def test_reviewed_draft_save_rejects_blank_action_instead_of_silently_dropping_it(client, app, monkeypatch):
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
