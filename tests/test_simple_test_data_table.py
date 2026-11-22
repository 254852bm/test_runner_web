import pytest
from cryptography.fernet import Fernet

from app import create_app, db
from app.models import Project, TestCase, TestDataBatch, TestDataColumn, TestDataRow, TestDataSet, TestRun, TestRunDataSnapshot, TestStep, User
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



def _create_editable_case(app, project_id):
    with app.app_context():
        test = TestCase(
            title="Редактируемый тест", precondition="Открыть {{base_url}}",
            steps="Ввести {{login}}", expected_result="Вход выполнен",
            project_id=project_id,
        )
        db.session.add(test)
        db.session.flush()
        step = TestStep(
            test_case_id=test.id, position=1,
            action="Ввести {{login}}", expected_result="Вход выполнен",
        )
        db.session.add(step)
        db.session.commit()
        return test.id, step.id


def test_edit_test_updates_simple_parameters_in_place_and_keeps_history(app):
    user_id, project_id = _user_and_project(app)
    test_id, step_id = _create_editable_case(app, project_id)
    with app.app_context():
        test = db.session.get(TestCase, test_id)
        dataset = TestDataSet(test_case_id=test.id, name="Основные параметры", is_default=True)
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(dataset_id=dataset.id, key="login", label="Логин", position=0)
        row = TestDataRow(
            dataset_id=dataset.id, name="Значения по умолчанию",
            values_json={"login": "old-user"}, is_default=True, is_enabled=True,
        )
        db.session.add_all([column, row])
        db.session.flush()
        run = TestRun(status="PASS", test_case_id=test.id, user_id=user_id)
        db.session.add(run)
        db.session.flush()
        snapshot = TestRunDataSnapshot(
            test_run_id=run.id, dataset_id=dataset.id, data_row_id=row.id,
            dataset_name_snapshot=dataset.name, row_name_snapshot=row.name,
            values_snapshot_json={"login": "old-user"},
        )
        db.session.add(snapshot)
        db.session.commit()
        dataset_id, row_id, column_id, snapshot_id = dataset.id, row.id, column.id, snapshot.id

    client = app.test_client()
    _login(client, user_id)
    page = client.get(f"/project/{project_id}/test/{test_id}/edit")
    assert page.status_code == 200
    assert "Тестовые данные" in page.get_data(as_text=True)

    response = client.post(f"/project/{project_id}/test/{test_id}/edit", data={
        "title": "Редактируемый тест обновлён",
        "precondition": "Открыть {{base_url}}",
        "step_id[]": [str(step_id)],
        "step_action[]": ["Ввести {{login}}"],
        "step_expected[]": ["Вход выполнен"],
        "data_set_count": "1",
        "data_0_column_id[]": [str(column_id)],
        "data_0_column_key[]": ["username"],
        "data_0_column_label[]": ["Имя пользователя"],
        "data_0_column_is_secret_0": "0",
        "data_0_row_0_value_0": "new-user",
    })
    assert response.status_code == 302

    with app.app_context():
        dataset = db.session.get(TestDataSet, dataset_id)
        row = db.session.get(TestDataRow, row_id)
        column = db.session.get(TestDataColumn, column_id)
        snapshot = db.session.get(TestRunDataSnapshot, snapshot_id)
        assert dataset is not None and row is not None and column is not None
        assert column.key == "username"
        assert row.values_json == {"username": "new-user"}
        assert snapshot.values_snapshot_json == {"login": "old-user"}
        assert snapshot.dataset_id == dataset_id
        assert snapshot.data_row_id == row_id


def test_edit_test_keeps_secret_when_blank_and_never_renders_it(app):
    user_id, project_id = _user_and_project(app)
    test_id, step_id = _create_editable_case(app, project_id)
    with app.app_context():
        test = db.session.get(TestCase, test_id)
        dataset = TestDataSet(test_case_id=test.id, name="Основные параметры", is_default=True)
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(
            dataset_id=dataset.id, key="password", label="Пароль",
            position=0, is_secret=True,
        )
        from app.test_data_crypto import encrypt_secret_values
        row = TestDataRow(
            dataset_id=dataset.id, name="Значения по умолчанию",
            values_json={}, encrypted_values_json=encrypt_secret_values({"password": "very-private-secret"}),
            is_default=True, is_enabled=True,
        )
        db.session.add_all([column, row])
        db.session.commit()
        dataset_id, row_id, column_id = dataset.id, row.id, column.id

    client = app.test_client()
    _login(client, user_id)
    page = client.get(f"/project/{project_id}/test/{test_id}/edit")
    html = page.get_data(as_text=True)
    assert "very-private-secret" not in html
    assert "Секрет сохранён" in html

    response = client.post(f"/project/{project_id}/test/{test_id}/edit", data={
        "title": "Редактируемый тест",
        "precondition": "",
        "step_id[]": [str(step_id)],
        "step_action[]": ["Проверить вход"],
        "step_expected[]": ["Успешно"],
        "data_set_count": "1",
        "data_0_column_id[]": [str(column_id)],
        "data_0_column_key[]": ["password"],
        "data_0_column_label[]": ["Пароль"],
        "data_0_column_is_secret_0": "1",
        "data_0_row_0_value_0": "",
    })
    assert response.status_code == 302

    with app.app_context():
        row = db.session.get(TestDataRow, row_id)
        assert row.values_json == {}
        assert decrypt_secret_values(row.encrypted_values_json) == {
            "password": "very-private-secret"
        }
        assert "very-private-secret" not in row.encrypted_values_json


def test_edit_test_rejects_complex_legacy_data_without_mutating_it(app):
    user_id, project_id = _user_and_project(app)
    test_id, step_id = _create_editable_case(app, project_id)
    with app.app_context():
        test = db.session.get(TestCase, test_id)
        dataset = TestDataSet(test_case_id=test.id, name="Legacy variants")
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(dataset_id=dataset.id, key="login", label="Login", position=0)
        rows = [
            TestDataRow(dataset_id=dataset.id, name="One", values_json={"login": "one"}),
            TestDataRow(dataset_id=dataset.id, name="Two", values_json={"login": "two"}),
        ]
        db.session.add_all([column, *rows])
        db.session.commit()
        dataset_id = dataset.id
        column_id = column.id

    client = app.test_client()
    _login(client, user_id)
    page = client.get(f"/project/{project_id}/test/{test_id}/edit")
    assert page.status_code == 200
    assert "несколько вариантов" in page.get_data(as_text=True)

    response = client.post(f"/project/{project_id}/test/{test_id}/edit", data={
        "title": "Не должно сохраниться",
        "precondition": "",
        "step_id[]": [str(step_id)],
        "step_action[]": ["Изменённое действие"],
        "step_expected[]": ["Ожидаемый результат"],
        "data_set_count": "1",
        "data_0_column_id[]": [str(column_id)],
        "data_0_column_key[]": ["login"],
        "data_0_column_label[]": ["Login"],
        "data_0_column_is_secret_0": "0",
        "data_0_row_0_value_0": "overwritten",
    })
    assert response.status_code == 302
    with app.app_context():
        test = db.session.get(TestCase, test_id)
        dataset = db.session.get(TestDataSet, dataset_id)
        assert test.title == "Редактируемый тест"
        assert dataset is not None
        assert [row.values_json["login"] for row in dataset.rows] == ["one", "two"]



def test_edit_test_can_remove_simple_parameters_without_deleting_history(app):
    user_id, project_id = _user_and_project(app)
    test_id, step_id = _create_editable_case(app, project_id)
    with app.app_context():
        test = db.session.get(TestCase, test_id)
        dataset = TestDataSet(test_case_id=test.id, name="Основные параметры", is_default=True)
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(dataset_id=dataset.id, key="login", label="Логин", position=0)
        row = TestDataRow(
            dataset_id=dataset.id, name="Значения по умолчанию",
            values_json={"login": "old-user"}, is_default=True, is_enabled=True,
        )
        db.session.add_all([column, row])
        db.session.flush()
        run = TestRun(status="PASS", test_case_id=test.id, user_id=user_id)
        db.session.add(run)
        db.session.flush()
        snapshot = TestRunDataSnapshot(
            test_run_id=run.id, dataset_id=dataset.id, data_row_id=row.id,
            dataset_name_snapshot=dataset.name, row_name_snapshot=row.name,
            values_snapshot_json={"login": "old-user"},
        )
        db.session.add(snapshot)
        db.session.commit()
        dataset_id, row_id, snapshot_id = dataset.id, row.id, snapshot.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(f"/project/{project_id}/test/{test_id}/edit", data={
        "title": "Редактируемый тест",
        "precondition": "",
        "step_id[]": [str(step_id)],
        "step_action[]": ["Проверить вход"],
        "step_expected[]": ["Успешно"],
        "data_set_count": "0",
    })
    assert response.status_code == 302

    with app.app_context():
        assert db.session.get(TestDataSet, dataset_id) is None
        assert db.session.get(TestDataRow, row_id) is None
        snapshot = db.session.get(TestRunDataSnapshot, snapshot_id)
        assert snapshot is not None
        assert snapshot.dataset_id is None
        assert snapshot.data_row_id is None
        assert snapshot.values_snapshot_json == {"login": "old-user"}


def test_profile_page_has_csrf_token_context(app):
    user_id, _project_id = _user_and_project(app)
    client = app.test_client()
    _login(client, user_id)

    response = client.get("/profile")

    assert response.status_code == 200
    assert 'name="csrf_token"' in response.get_data(as_text=True)



def test_edit_test_cannot_delete_legacy_multi_row_dataset_with_empty_form(app):
    user_id, project_id = _user_and_project(app)
    test_id, step_id = _create_editable_case(app, project_id)
    with app.app_context():
        dataset = TestDataSet(
            test_case_id=test_id, name="Legacy variants", is_default=True
        )
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(
            dataset_id=dataset.id, key="login", label="Login", position=0
        )
        rows = [
            TestDataRow(
                dataset_id=dataset.id, name="One",
                values_json={"login": "one"}, is_default=True, is_enabled=True,
            ),
            TestDataRow(
                dataset_id=dataset.id, name="Two",
                values_json={"login": "two"}, is_default=False, is_enabled=True,
            ),
        ]
        db.session.add_all([column, *rows])
        db.session.commit()
        dataset_id = dataset.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(f"/project/{project_id}/test/{test_id}/edit", data={
        "title": "Не должно сохраниться",
        "precondition": "",
        "step_id[]": [str(step_id)],
        "step_action[]": ["Изменённое действие"],
        "step_expected[]": ["Ожидаемый результат"],
        "data_set_count": "0",
    })
    assert response.status_code == 302

    with app.app_context():
        test = db.session.get(TestCase, test_id)
        dataset = db.session.get(TestDataSet, dataset_id)
        assert test.title == "Редактируемый тест"
        assert dataset is not None
        assert [row.values_json["login"] for row in dataset.rows] == ["one", "two"]


def test_edit_test_cannot_delete_dataset_with_active_batch_using_empty_form(app):
    user_id, project_id = _user_and_project(app)
    test_id, step_id = _create_editable_case(app, project_id)
    with app.app_context():
        dataset = TestDataSet(
            test_case_id=test_id, name="Основные параметры", is_default=True
        )
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(
            dataset_id=dataset.id, key="login", label="Login", position=0
        )
        row = TestDataRow(
            dataset_id=dataset.id, name="Значения по умолчанию",
            values_json={"login": "tester"}, is_default=True, is_enabled=True,
        )
        db.session.add_all([column, row])
        db.session.flush()
        batch = TestDataBatch(
            token="batch-token-for-protection-test",
            user_id=user_id, test_case_id=test_id, dataset_id=dataset.id,
            row_ids_json=[row.id], next_index=0,
        )
        db.session.add(batch)
        db.session.commit()
        dataset_id, row_id, batch_id = dataset.id, row.id, batch.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(f"/project/{project_id}/test/{test_id}/edit", data={
        "title": "Не должно сохраниться",
        "precondition": "",
        "step_id[]": [str(step_id)],
        "step_action[]": ["Изменённое действие"],
        "step_expected[]": ["Ожидаемый результат"],
        "data_set_count": "0",
    })
    assert response.status_code == 302

    with app.app_context():
        test = db.session.get(TestCase, test_id)
        assert test.title == "Редактируемый тест"
        assert db.session.get(TestDataSet, dataset_id) is not None
        assert db.session.get(TestDataRow, row_id) is not None
        assert db.session.get(TestDataBatch, batch_id) is not None
