import pytest
from cryptography.fernet import Fernet

from app import create_app, db
from app.models import Project, TestCase, TestDataColumn, TestDataRow, TestDataSet, User
from app.test_data_crypto import decrypt_secret_values


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "INSTANCE_PATH": str(instance_path),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'simple-parameters.sqlite'}",
        "TEST_DATA_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _user_and_project(app):
    with app.app_context():
        user = User(email="simple-parameters@example.test", password="test-password")
        db.session.add(user)
        db.session.flush()
        project = Project(name="Simple parameters", user_id=user.id)
        db.session.add(project)
        db.session.commit()
        return user.id, project.id


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_create_test_saves_simple_key_value_parameters(app):
    user_id, project_id = _user_and_project(app)
    client = app.test_client()
    _login(client, user_id)

    response = client.post(f"/project/{project_id}/create_test", data={
        "title": "Вход с параметрами",
        "precondition": "Открыть {{base_url}}",
        "step_action[]": ["Ввести {{login}}"],
        "step_expected[]": ["Пользователь вошёл"],
        "data_set_count": "1",
        "data_0_name": "Основные параметры",
        "default_data_set_index": "0",
        "data_0_column_key[]": ["base_url", "login"],
        "data_0_column_label[]": ["base_url", "login"],
        "data_0_row_name[]": ["Значения по умолчанию"],
        "data_0_default_row_index": "0",
        "data_0_row_0_value_0": "https://example.test",
        "data_0_row_0_value_1": "tester",
    })
    assert response.status_code == 302

    with app.app_context():
        test = TestCase.query.filter_by(project_id=project_id, title="Вход с параметрами").one()
        dataset = TestDataSet.query.filter_by(test_case_id=test.id).one()
        assert dataset.is_default is True
        assert [column.key for column in dataset.columns] == ["base_url", "login"]
        row = TestDataRow.query.filter_by(dataset_id=dataset.id).one()
        assert row.is_default is True
        assert row.values_json == {
            "base_url": "https://example.test",
            "login": "tester",
        }


def test_create_test_encrypts_secret_parameter_values(app):
    user_id, project_id = _user_and_project(app)
    client = app.test_client()
    _login(client, user_id)

    response = client.post(f"/project/{project_id}/create_test", data={
        "title": "Вход с секретом",
        "precondition": "",
        "step_action[]": ["Ввести {{password}}"],
        "step_expected[]": ["Успешный вход"],
        "data_set_count": "1",
        "data_0_name": "Основные параметры",
        "default_data_set_index": "0",
        "data_0_column_key[]": ["password"],
        "data_0_column_label[]": ["password"],
        "data_0_column_is_secret_0": "1",
        "data_0_row_name[]": ["Значения по умолчанию"],
        "data_0_default_row_index": "0",
        "data_0_row_0_value_0": "not-a-real-password",
    })
    assert response.status_code == 302

    with app.app_context():
        test = TestCase.query.filter_by(project_id=project_id, title="Вход с секретом").one()
        dataset = TestDataSet.query.filter_by(test_case_id=test.id).one()
        row = TestDataRow.query.filter_by(dataset_id=dataset.id).one()
        assert row.values_json == {}
        assert "not-a-real-password" not in (row.encrypted_values_json or "")
        assert decrypt_secret_values(row.encrypted_values_json) == {
            "password": "not-a-real-password"
        }


def test_create_test_rejects_secret_named_parameter_without_secret_flag(app):
    user_id, project_id = _user_and_project(app)
    client = app.test_client()
    _login(client, user_id)

    response = client.post(f"/project/{project_id}/create_test", data={
        "title": "Небезопасный параметр",
        "precondition": "",
        "step_action[]": ["Ввести {{password}}"],
        "step_expected[]": ["Успешный вход"],
        "data_set_count": "1",
        "data_0_name": "Основные параметры",
        "default_data_set_index": "0",
        "data_0_column_key[]": ["password"],
        "data_0_column_label[]": ["password"],
        "data_0_row_name[]": ["Значения по умолчанию"],
        "data_0_default_row_index": "0",
        "data_0_row_0_value_0": "plain-text-must-not-be-saved",
    })
    assert response.status_code == 200
    with app.app_context():
        assert TestCase.query.filter_by(project_id=project_id).count() == 0
        assert TestDataSet.query.count() == 0


def test_create_test_without_parameters_still_works(app):
    user_id, project_id = _user_and_project(app)
    client = app.test_client()
    _login(client, user_id)

    response = client.post(f"/project/{project_id}/create_test", data={
        "title": "Обычный тест",
        "precondition": "",
        "step_action[]": ["Открыть главную страницу"],
        "step_expected[]": ["Главная страница открыта"],
    })
    assert response.status_code == 302
    with app.app_context():
        test = TestCase.query.filter_by(project_id=project_id, title="Обычный тест").one()
        assert TestDataSet.query.filter_by(test_case_id=test.id).count() == 0
