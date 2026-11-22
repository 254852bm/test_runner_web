import pytest
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Project, TestCase, TestDataColumn, TestDataRow, TestDataSet, TestStep, User


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "INSTANCE_PATH": str(instance_path),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'automation-routes.sqlite'}",
        "WTF_CSRF_ENABLED": False,
        "AI_AUTOMATION_TESTS_ENABLED": False,
    })
    with app.app_context():
        db.create_all()
        owner = User(email="automation-owner@example.test", password=generate_password_hash("test-password"))
        other = User(email="automation-other@example.test", password=generate_password_hash("test-password"))
        db.session.add_all([owner, other])
        db.session.flush()
        project = Project(name="Automation project", user_id=owner.id)
        foreign_project = Project(name="Foreign project", user_id=other.id)
        db.session.add_all([project, foreign_project])
        db.session.flush()
        test_case = TestCase(
            title="Проверка авторизации",
            precondition="Пользователь зарегистрирован",
            steps="Открыть форму",
            expected_result="Форма отображается",
            project_id=project.id,
        )
        db.session.add(test_case)
        db.session.flush()
        db.session.add(TestStep(
            test_case_id=test_case.id,
            position=1,
            action="Открыть форму входа",
            expected_result="Форма отображается",
        ))
        dataset = TestDataSet(test_case_id=test_case.id, name="Учётные данные")
        db.session.add(dataset)
        db.session.flush()
        db.session.add(TestDataColumn(
            dataset_id=dataset.id,
            key="password",
            label="Пароль",
            is_secret=True,
            position=1,
        ))
        db.session.add(TestDataRow(
            dataset_id=dataset.id,
            name="Строка 1",
            values_json={},
            encrypted_values_json="ciphertext-must-not-be-read",
            is_enabled=True,
            position=1,
        ))
        db.session.commit()
        app.config["OWNER_ID"] = owner.id
        app.config["PROJECT_ID"] = project.id
        app.config["TEST_ID"] = test_case.id
        app.config["FOREIGN_PROJECT_ID"] = foreign_project.id
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _login(client, app, user_id=None):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id or app.config["OWNER_ID"])
        session["_fresh"] = True


def test_automation_draft_requires_login(client, app):
    response = client.get(
        f"/project/{app.config['PROJECT_ID']}/test/{app.config['TEST_ID']}/automation-draft"
    )
    assert response.status_code == 302


def test_automation_draft_only_allows_project_owner(client, app):
    _login(client, app)
    response = client.get(
        f"/project/{app.config['FOREIGN_PROJECT_ID']}/test/{app.config['TEST_ID']}/automation-draft"
    )
    assert response.status_code == 404


def test_automation_draft_page_is_disabled_by_default(client, app):
    _login(client, app)
    response = client.get(
        f"/project/{app.config['PROJECT_ID']}/test/{app.config['TEST_ID']}/automation-draft"
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Генерация автотестов пока отключена" in html
    assert "Подготовить черновик автотеста" in html


def test_automation_context_contains_parameter_names_but_no_values(app):
    with app.app_context():
        from app.ai.automation_routes import _safe_test_case_context

        test_case = db.session.get(TestCase, app.config["TEST_ID"])
        context = _safe_test_case_context(test_case)

        assert context["parameters"] == [{"name": "Пароль", "is_secret": True}]
        assert "ciphertext-must-not-be-read" not in repr(context)
        assert "values_json" not in repr(context)
        assert context["steps"][0]["action"] == "Открыть форму входа"



def _valid_automation_draft():
    return {
        "summary": "Черновик проверки формы входа",
        "target_profile": {
            "language": "java",
            "framework": "junit5",
            "test_type": "ui",
        },
        "files": [{
            "path": "src/test/java/LoginTest.java",
            "content": "class LoginTest { /* TODO: add verified locator */ }",
        }],
        "assumptions": ["Используется согласованный тестовый стенд."],
        "open_questions": ["Какой URL тестового стенда использовать?"],
        "todo_items": ["Добавить проверенный URL и локаторы."],
        "coverage_notes": ["Проверяется отображение формы входа."],
    }


def test_automation_draft_post_renders_generated_code_without_persisting(
    client, app, monkeypatch
):
    from app.ai import automation_routes
    from app import db

    _login(client, app)
    app.config["AI_AUTOMATION_TESTS_ENABLED"] = True
    app.config["AI_PROVIDER_MODE"] = "ollama"

    calls = {"provider": 0, "reserved": 0}

    class FakeProvider:
        pass

    def fake_generate(provider, context):
        calls["provider"] += 1
        assert context["parameters"] == [{"name": "Пароль", "is_secret": True}]
        return _valid_automation_draft()

    monkeypatch.setattr(automation_routes, "_provider", lambda: FakeProvider())
    monkeypatch.setattr(automation_routes, "_reserve_generation_slot",
                        lambda: calls.__setitem__("reserved", calls["reserved"] + 1) or True)
    monkeypatch.setattr(automation_routes, "generate_automation_test_draft", fake_generate)
    monkeypatch.setattr(automation_routes, "validate_csrf", lambda token: None)

    response = client.post(
        f"/project/{app.config['PROJECT_ID']}/test/{app.config['TEST_ID']}/automation-draft",
        data={"csrf_token": "test-token"},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Черновик проверки формы входа" in html
    assert "class LoginTest" in html
    assert "Какой URL тестового стенда использовать?" in html
    assert calls == {"provider": 1, "reserved": 1}

    with app.app_context():
        from app.models import TestCase
        test_case = db.session.get(TestCase, app.config["TEST_ID"])
        assert test_case.title == "Проверка авторизации"
        assert "LoginTest" not in (test_case.steps or "")


def test_automation_draft_provider_error_is_shown_without_traceback(
    client, app, monkeypatch
):
    from app.ai import automation_routes
    from app.ai.provider import AIProviderError

    _login(client, app)
    app.config["AI_AUTOMATION_TESTS_ENABLED"] = True
    app.config["AI_PROVIDER_MODE"] = "ollama"
    monkeypatch.setattr(automation_routes, "_provider", lambda: object())
    monkeypatch.setattr(automation_routes, "_reserve_generation_slot", lambda: True)
    monkeypatch.setattr(
        automation_routes,
        "generate_automation_test_draft",
        lambda provider, context: (_ for _ in ()).throw(
            AIProviderError("Не удалось подготовить черновик автотеста. Попробуйте позже.")
        ),
    )
    monkeypatch.setattr(automation_routes, "validate_csrf", lambda token: None)

    response = client.post(
        f"/project/{app.config['PROJECT_ID']}/test/{app.config['TEST_ID']}/automation-draft",
        data={"csrf_token": "test-token"},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Не удалось подготовить черновик автотеста" in html
    assert "Traceback" not in html
