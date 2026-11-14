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
