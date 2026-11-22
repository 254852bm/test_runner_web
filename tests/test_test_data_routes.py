import pytest

from app import create_app, db
from app.models import (
    Project, TestCase, TestDataColumn, TestDataRow, TestDataSet,
    TestRun, TestRunDataSnapshot, TestStep, TestDataBatch, User,
)


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    database_path = tmp_path / "parameterization-routes.sqlite"
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "INSTANCE_PATH": str(instance_path),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _case():
    user = User(email="routes@example.test", password="not-a-real-password")
    db.session.add(user)
    db.session.flush()
    project = Project(name="Routes project", user_id=user.id)
    db.session.add(project)
    db.session.flush()
    case = TestCase(
        title="Login test", precondition="",
        steps="Enter {{login}}", expected_result="",
        project_id=project.id,
    )
    db.session.add(case)
    db.session.flush()
    step = TestStep(
        test_case_id=case.id, position=1,
        action="Enter {{login}}", expected_result="Dashboard is shown"
    )
    db.session.add(step)
    db.session.commit()
    return user, project, case


def test_user_can_create_dataset_and_add_edit_toggle_delete_row(app):
    with app.app_context():
        user, project, case = _case()
        user_id, project_id, case_id = user.id, project.id, case.id

    client = app.test_client()
    _login(client, user_id)

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/create",
        data={
            "dataset_name": "Login data",
            "column_key[]": ["login", "expected_message"],
            "column_label[]": ["Логин", "Ожидаемое сообщение"],
        },
    )
    assert response.status_code == 302

    with app.app_context():
        dataset = TestDataSet.query.filter_by(test_case_id=case_id).one()
        columns = {column.key: column.id for column in dataset.columns}
        dataset_id = dataset.id

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/create",
        data={
            "row_name": "Valid account",
            f"value_{columns['login']}": "qa@example.test",
            f"value_{columns['expected_message']}": "Welcome",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        row = TestDataRow.query.filter_by(dataset_id=dataset_id).one()
        row_id = row.id
        assert row.values_json == {
            "login": "qa@example.test",
            "expected_message": "Welcome",
        }

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/{row_id}/edit",
        data={
            "row_name": "Updated account",
            f"value_{columns['login']}": "updated@example.test",
            f"value_{columns['expected_message']}": "Hello",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        row = db.session.get(TestDataRow, row_id)
        assert row.name == "Updated account"
        assert row.values_json["login"] == "updated@example.test"

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/{row_id}/toggle",
        data={"is_enabled": "0"},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(TestDataRow, row_id).is_enabled is False

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/{row_id}/delete"
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(TestDataRow, row_id) is None


def test_user_cannot_view_or_create_data_for_another_users_test_case(app):
    with app.app_context():
        owner, project, case = _case()
        other = User(email="other-routes@example.test", password="not-a-real-password")
        db.session.add(other)
        db.session.commit()
        owner_project_id, case_id, other_id = project.id, case.id, other.id

    client = app.test_client()
    _login(client, other_id)
    response = client.get(f"/project/{owner_project_id}/test/{case_id}/data")
    assert response.status_code == 302

    response = client.post(
        f"/project/{owner_project_id}/test/{case_id}/data/create",
        data={
            "dataset_name": "Unauthorized",
            "column_key[]": ["login"],
            "column_label[]": ["Login"],
        },
    )
    assert response.status_code == 302
    with app.app_context():
        assert TestDataSet.query.filter_by(test_case_id=case_id).count() == 0


def test_deleting_dataset_preserves_historical_snapshot(app):
    with app.app_context():
        user, project, case = _case()
        dataset = TestDataSet(test_case_id=case.id, name="History set")
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(
            dataset_id=dataset.id, key="login", label="Login", position=0
        )
        row = TestDataRow(
            dataset_id=dataset.id, name="Original row",
            values_json={"login": "original@example.test"}
        )
        db.session.add_all([column, row])
        db.session.flush()
        run = TestRun(status="PASS", test_case_id=case.id, user_id=user.id)
        db.session.add(run)
        db.session.flush()
        snapshot = TestRunDataSnapshot(
            test_run_id=run.id, dataset_id=dataset.id, data_row_id=row.id,
            dataset_name_snapshot="History set",
            row_name_snapshot="Original row",
            values_snapshot_json={"login": "original@example.test"},
        )
        db.session.add(snapshot)
        db.session.commit()
        user_id, project_id, case_id = user.id, project.id, case.id
        dataset_id, snapshot_id = dataset.id, snapshot.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/delete"
    )
    assert response.status_code == 302

    with app.app_context():
        saved = db.session.get(TestRunDataSnapshot, snapshot_id)
        assert saved is not None
        assert saved.dataset_id is None
        assert saved.data_row_id is None
        assert saved.dataset_name_snapshot == "History set"
        assert saved.row_name_snapshot == "Original row"
        assert saved.values_snapshot_json == {"login": "original@example.test"}


def test_data_management_page_renders_empty_state(app):
    with app.app_context():
        user, project, case = _case()
        user_id, project_id, case_id = user.id, project.id, case.id
    client = app.test_client()
    _login(client, user_id)
    response = client.get(f"/project/{project_id}/test/{case_id}/data")
    assert response.status_code == 200
    assert "Создать набор данных" in response.get_data(as_text=True)


def test_route_rejects_password_like_column_name_until_encryption_exists(app):
    with app.app_context():
        user, project, case = _case()
        user_id, project_id, case_id = user.id, project.id, case.id
    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/create",
        data={
            "dataset_name": "Unsafe credentials",
            "column_key[]": ["password"],
            "column_label[]": ["Password"],
        },
    )
    assert response.status_code == 302
    with app.app_context():
        assert TestDataSet.query.filter_by(test_case_id=case_id).count() == 0



def _attach_parameterized_history(user, case):
    dataset = TestDataSet(test_case_id=case.id, name="Deletion data")
    db.session.add(dataset)
    db.session.flush()
    column = TestDataColumn(
        dataset_id=dataset.id, key="login", label="Login", position=0
    )
    row = TestDataRow(
        dataset_id=dataset.id, name="Deletion row",
        values_json={"login": "history@example.test"}
    )
    db.session.add_all([column, row])
    db.session.flush()
    run = TestRun(status="PASS", test_case_id=case.id, user_id=user.id)
    db.session.add(run)
    db.session.flush()
    snapshot = TestRunDataSnapshot(
        test_run_id=run.id, dataset_id=dataset.id, data_row_id=row.id,
        dataset_name_snapshot=dataset.name, row_name_snapshot=row.name,
        values_snapshot_json=dict(row.values_json),
    )
    batch = TestDataBatch(
        token=f"delete-test-batch-{case.id}", user_id=user.id,
        test_case_id=case.id, dataset_id=dataset.id,
        row_ids_json=[row.id], next_index=0,
    )
    db.session.add_all([snapshot, batch])
    db.session.commit()
    return dataset.id, column.id, row.id, run.id, snapshot.id, batch.id


def test_deleting_test_case_removes_its_parameterization_records_and_run_snapshots(app):
    with app.app_context():
        user, project, case = _case()
        user_id, project_id, case_id = user.id, project.id, case.id
        dataset_id, column_id, row_id, run_id, snapshot_id, batch_id = (
            _attach_parameterized_history(user, case)
        )

    client = app.test_client()
    _login(client, user_id)
    response = client.post(f"/project/{project_id}/test/{case_id}/delete")
    assert response.status_code == 302

    with app.app_context():
        assert db.session.get(TestCase, case_id) is None
        assert db.session.get(TestRun, run_id) is None
        assert db.session.get(TestRunDataSnapshot, snapshot_id) is None
        assert db.session.get(TestDataSet, dataset_id) is None
        assert db.session.get(TestDataColumn, column_id) is None
        assert db.session.get(TestDataRow, row_id) is None
        assert db.session.get(TestDataBatch, batch_id) is None


def test_deleting_project_removes_parameterization_records_and_run_snapshots(app):
    with app.app_context():
        user, project, case = _case()
        user_id, project_id, case_id = user.id, project.id, case.id
        dataset_id, column_id, row_id, run_id, snapshot_id, batch_id = (
            _attach_parameterized_history(user, case)
        )

    client = app.test_client()
    _login(client, user_id)
    response = client.post(f"/project/{project_id}/delete")
    assert response.status_code == 302

    with app.app_context():
        assert db.session.get(Project, project_id) is None
        assert db.session.get(TestCase, case_id) is None
        assert db.session.get(TestRun, run_id) is None
        assert db.session.get(TestRunDataSnapshot, snapshot_id) is None
        assert db.session.get(TestDataSet, dataset_id) is None
        assert db.session.get(TestDataColumn, column_id) is None
        assert db.session.get(TestDataRow, row_id) is None
        assert db.session.get(TestDataBatch, batch_id) is None


def test_test_detail_shows_parameter_table_and_data_variants_in_russian(app):
    with app.app_context():
        user, project, case = _case()
        dataset = TestDataSet(test_case_id=case.id, name="Основной набор")
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(
            dataset_id=dataset.id, key="login", label="Логин", position=0
        )
        row = TestDataRow(
            dataset_id=dataset.id, name="Успешный вход",
            values_json={"login": "qa@example.test"}, is_enabled=True
        )
        db.session.add_all([column, row])
        db.session.commit()
        user_id, project_id, case_id = user.id, project.id, case.id

    client = app.test_client()
    _login(client, user_id)
    response = client.get(f"/project/{project_id}/test/{case_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Параметры тест-кейса" in html
    assert "Название параметра" in html
    assert "Значение по умолчанию" in html
    assert "Успешный вход" in html
    assert "qa@example.test" in html
    assert "Управлять параметрами" in html


def test_user_can_create_dataset_with_russian_parameter_names(app):
    with app.app_context():
        user, project, case = _case()
        user_id, project_id, case_id = user.id, project.id, case.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/create",
        data={
            "dataset_name": "Поручения",
            "column_key[]": ["Исполнитель 1", "Текст поручения"],
            "column_label[]": ["Исполнитель 1", "Текст поручения"],
        },
    )
    assert response.status_code == 302

    with app.app_context():
        dataset = TestDataSet.query.filter_by(test_case_id=case_id).one()
        assert [column.key for column in dataset.columns] == [
            "Исполнитель 1", "Текст поручения"
        ]


def test_user_can_rename_own_dataset_without_changing_history(app):
    with app.app_context():
        user, project, case = _case()
        dataset = TestDataSet(test_case_id=case.id, name="Старое название")
        db.session.add(dataset)
        db.session.flush()
        row = TestDataRow(
            dataset_id=dataset.id, name="Первый вариант",
            values_json={"login": "qa@example.test"}
        )
        db.session.add(row)
        db.session.flush()
        run = TestRun(status="PASS", test_case_id=case.id, user_id=user.id)
        db.session.add(run)
        db.session.flush()
        snapshot = TestRunDataSnapshot(
            test_run_id=run.id, dataset_id=dataset.id, data_row_id=row.id,
            dataset_name_snapshot="Старое название",
            row_name_snapshot="Первый вариант",
            values_snapshot_json={"login": "qa@example.test"},
        )
        db.session.add(snapshot)
        db.session.commit()
        user_id, project_id, case_id, dataset_id = user.id, project.id, case.id, dataset.id
        snapshot_id = snapshot.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rename",
        data={"dataset_name": "Набор для регрессии"},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(TestDataSet, dataset_id).name == "Набор для регрессии"
        saved = db.session.get(TestRunDataSnapshot, snapshot_id)
        assert saved.dataset_name_snapshot == "Старое название"


def test_user_cannot_rename_another_users_dataset(app):
    with app.app_context():
        owner, project, case = _case()
        dataset = TestDataSet(test_case_id=case.id, name="Исходный набор")
        db.session.add(dataset)
        db.session.flush()
        dataset_id = dataset.id
        project_id, case_id = project.id, case.id
        other = User(email="rename-other@example.test", password="not-a-real-password")
        db.session.add(other)
        db.session.commit()
        other_id = other.id

    client = app.test_client()
    _login(client, other_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rename",
        data={"dataset_name": "Чужое название"},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(TestDataSet, dataset_id).name == "Исходный набор"


def test_renaming_dataset_rejects_empty_name(app):
    with app.app_context():
        user, project, case = _case()
        dataset = TestDataSet(test_case_id=case.id, name="Исходный набор")
        db.session.add(dataset)
        db.session.commit()
        user_id, project_id, case_id, dataset_id = user.id, project.id, case.id, dataset.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rename",
        data={"dataset_name": "   "},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(TestDataSet, dataset_id).name == "Исходный набор"


def test_create_dataset_uses_parameter_name_as_display_label_when_label_is_omitted(app):
    with app.app_context():
        user, project, case = _case()
        user_id, project_id, case_id = user.id, project.id, case.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/create",
        data={
            "dataset_name": "Русские параметры",
            "column_key[]": ["Исполнитель 1", "Текст поручения"],
        },
    )
    assert response.status_code == 302
    with app.app_context():
        dataset = TestDataSet.query.filter_by(test_case_id=case_id).one()
        assert [(column.key, column.label) for column in dataset.columns] == [
            ("Исполнитель 1", "Исполнитель 1"),
            ("Текст поручения", "Текст поручения"),
        ]


def test_test_detail_never_renders_decrypted_secret_parameter_value(app):
    from cryptography.fernet import Fernet
    from flask import current_app
    from app.test_data_crypto import encrypt_secret_values

    with app.app_context():
        current_app.config["TEST_DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
        user, project, case = _case()
        dataset = TestDataSet(test_case_id=case.id, name="Секретный набор")
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(
            dataset_id=dataset.id, key="Пароль пользователя",
            label="Пароль пользователя", position=0, is_secret=True
        )
        row = TestDataRow(
            dataset_id=dataset.id, name="Тестовый аккаунт",
            values_json={}, encrypted_values_json=encrypt_secret_values(
                {"Пароль пользователя": "do-not-render-this-secret"}
            ), is_enabled=True
        )
        db.session.add_all([column, row])
        db.session.commit()
        user_id, project_id, case_id = user.id, project.id, case.id

    client = app.test_client()
    _login(client, user_id)
    response = client.get(f"/project/{project_id}/test/{case_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Пароль пользователя" in html
    assert "Скрыто" in html
    assert "do-not-render-this-secret" not in html


def test_test_data_page_renders_variants_as_editable_matrix_without_secrets(app):
    from cryptography.fernet import Fernet
    from flask import current_app
    from app.test_data_crypto import encrypt_secret_values

    with app.app_context():
        current_app.config["TEST_DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
        user, project, case = _case()
        dataset = TestDataSet(test_case_id=case.id, name="Набор авторизации")
        db.session.add(dataset)
        db.session.flush()
        login = TestDataColumn(
            dataset_id=dataset.id, key="Логин", label="Логин", position=0
        )
        password = TestDataColumn(
            dataset_id=dataset.id, key="Пароль", label="Пароль",
            position=1, is_secret=True
        )
        row = TestDataRow(
            dataset_id=dataset.id, name="Успешный вход",
            values_json={"Логин": "qa@example.test"},
            encrypted_values_json=encrypt_secret_values(
                {"Пароль": "never-render-this-password"}
            ),
            is_enabled=True,
        )
        db.session.add_all([login, password, row])
        db.session.commit()
        user_id, project_id, case_id = user.id, project.id, case.id

    client = app.test_client()
    _login(client, user_id)
    response = client.get(f"/project/{project_id}/test/{case_id}/data")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Варианты данных" in html
    assert "Успешный вход" in html
    assert "qa@example.test" in html
    assert "Изменить" in html
    assert "Скрыто" in html
    assert "never-render-this-password" not in html


def test_user_can_duplicate_data_row_without_exposing_secret_and_copy_starts_disabled(app):
    from cryptography.fernet import Fernet
    from flask import current_app
    from app.test_data_crypto import encrypt_secret_values

    with app.app_context():
        current_app.config["TEST_DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode("ascii")
        user, project, case = _case()
        dataset = TestDataSet(test_case_id=case.id, name="Набор")
        db.session.add(dataset)
        db.session.flush()
        ordinary = TestDataColumn(dataset_id=dataset.id, key="Логин", label="Логин", position=0)
        secret = TestDataColumn(dataset_id=dataset.id, key="Пароль", label="Пароль", position=1, is_secret=True)
        encrypted = encrypt_secret_values({"Пароль": "secret-that-must-not-be-decrypted"})
        source = TestDataRow(
            dataset_id=dataset.id, name="Успешный вход",
            values_json={"Логин": "qa@example.test"},
            encrypted_values_json=encrypted, is_enabled=True, position=0,
        )
        db.session.add_all([ordinary, secret, source])
        db.session.commit()
        user_id, project_id, case_id, dataset_id, row_id = user.id, project.id, case.id, dataset.id, source.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/{row_id}/duplicate",
        data={"row_name": "Неверный пароль"},
    )
    assert response.status_code == 302

    with app.app_context():
        rows = TestDataRow.query.filter_by(dataset_id=dataset_id).order_by(TestDataRow.position).all()
        assert len(rows) == 2
        duplicate = rows[1]
        assert duplicate.name == "Неверный пароль"
        assert duplicate.values_json == {"Логин": "qa@example.test"}
        assert duplicate.encrypted_values_json == encrypted
        assert duplicate.is_enabled is False
        assert duplicate.position > rows[0].position

    response = client.get(f"/project/{project_id}/test/{case_id}/data")
    html = response.get_data(as_text=True)
    assert "Копировать" in html
    assert "secret-that-must-not-be-decrypted" not in html


def test_user_cannot_duplicate_another_users_data_row(app):
    with app.app_context():
        owner, project, case = _case()
        dataset = TestDataSet(test_case_id=case.id, name="Набор")
        db.session.add(dataset)
        db.session.flush()
        row = TestDataRow(dataset_id=dataset.id, name="Вариант", values_json={}, is_enabled=True)
        db.session.add(row)
        other = User(email="duplicate-other@example.test", password="not-a-real-password")
        db.session.add(other)
        db.session.commit()
        other_id, project_id, case_id, dataset_id, row_id = other.id, project.id, case.id, dataset.id, row.id

    client = app.test_client()
    _login(client, other_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/{row_id}/duplicate",
        data={"row_name": "Чужая копия"},
    )
    assert response.status_code == 302
    with app.app_context():
        assert TestDataRow.query.filter_by(dataset_id=dataset_id).count() == 1


def test_user_can_bulk_enable_and_disable_selected_data_rows(app):
    with app.app_context():
        user, project, case = _case()
        dataset = TestDataSet(test_case_id=case.id, name="Набор")
        db.session.add(dataset)
        db.session.flush()
        rows = [
            TestDataRow(dataset_id=dataset.id, name="Вариант 1", values_json={}, is_enabled=False),
            TestDataRow(dataset_id=dataset.id, name="Вариант 2", values_json={}, is_enabled=False),
            TestDataRow(dataset_id=dataset.id, name="Вариант 3", values_json={}, is_enabled=False),
        ]
        db.session.add_all(rows)
        db.session.commit()
        user_id, project_id, case_id, dataset_id = user.id, project.id, case.id, dataset.id
        selected_ids = [rows[0].id, rows[2].id]

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/bulk-status",
        data={"row_ids[]": [str(value) for value in selected_ids], "is_enabled": "1"},
    )
    assert response.status_code == 302
    with app.app_context():
        saved = TestDataRow.query.filter_by(dataset_id=dataset_id).order_by(TestDataRow.id).all()
        assert [row.is_enabled for row in saved] == [True, False, True]

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/bulk-status",
        data={"row_ids[]": [str(value) for value in selected_ids], "is_enabled": "0"},
    )
    assert response.status_code == 302
    with app.app_context():
        saved = TestDataRow.query.filter_by(dataset_id=dataset_id).order_by(TestDataRow.id).all()
        assert [row.is_enabled for row in saved] == [False, False, False]


def test_bulk_status_rejects_row_ids_outside_selected_dataset(app):
    with app.app_context():
        user, project, case = _case()
        first = TestDataSet(test_case_id=case.id, name="Первый набор")
        second = TestDataSet(test_case_id=case.id, name="Второй набор")
        db.session.add_all([first, second])
        db.session.flush()
        row = TestDataRow(dataset_id=second.id, name="Чужой вариант", values_json={}, is_enabled=False)
        db.session.add(row)
        db.session.commit()
        user_id, project_id, case_id, dataset_id, row_id = user.id, project.id, case.id, first.id, row.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/bulk-status",
        data={"row_ids[]": [str(row_id)], "is_enabled": "1"},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(TestDataRow, row_id).is_enabled is False


@pytest.mark.parametrize("sensitive_name", ["Пароль", "Токен", "Ключ API", "Секрет"])
def test_russian_sensitive_parameter_names_must_be_marked_secret(app, sensitive_name):
    with app.app_context():
        user, project, case = _case()
        user_id, project_id, case_id = user.id, project.id, case.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/create",
        data={
            "dataset_name": "Небезопасные параметры",
            "column_key[]": [sensitive_name],
            "column_label[]": [sensitive_name],
        },
    )
    assert response.status_code == 302
    with app.app_context():
        assert TestDataSet.query.filter_by(test_case_id=case_id).count() == 0


def test_russian_sensitive_legacy_column_is_rejected_before_substitution(app):
    from app.test_data import prepare_test_data

    with app.app_context():
        user, project, case = _case()
        dataset = TestDataSet(test_case_id=case.id, name="Legacy credentials")
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(
            dataset_id=dataset.id, key="Пароль", label="Пароль",
            position=0, is_secret=False,
        )
        row = TestDataRow(
            dataset_id=dataset.id, name="Legacy row",
            values_json={"Пароль": "must-not-be-used"},
        )
        db.session.add_all([column, row])
        db.session.commit()
        with pytest.raises(ValueError, match="секретн"):
            prepare_test_data(case, dataset, row)



def test_test_creation_can_save_simple_parameters_before_first_commit(app):
    """Create a test and its single default parameter row in one transaction."""
    with app.app_context():
        user, project, _ = _case()
        user_id, project_id = user.id, project.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/create_test",
        data={
            "title": "Login with inline test data",
            "precondition": "Open {{base_url}}",
            "step_action[]": ["Enter {{login}}"],
            "step_expected[]": ["Welcome {{login}}"],
            "data_set_count": "1",
            "data_0_column_key[]": ["base_url", "login"],
            "data_0_column_label[]": ["Адрес сайта", "Логин"],
            "data_0_row_0_value_0": "https://example.test",
            "data_0_row_0_value_1": "user1",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        test = TestCase.query.filter_by(
            project_id=project_id, title="Login with inline test data"
        ).one()
        dataset = TestDataSet.query.filter_by(test_case_id=test.id).one()
        assert dataset.name == "Основные параметры"
        assert dataset.is_default is True
        assert [column.key for column in dataset.columns] == ["base_url", "login"]
        rows = sorted(dataset.rows, key=lambda row: row.position)
        assert len(rows) == 1
        assert rows[0].name == "Значения по умолчанию"
        assert rows[0].is_default is True
        assert rows[0].values_json == {
            "base_url": "https://example.test",
            "login": "user1",
        }


def test_test_creation_without_inline_test_data_remains_supported(app):
    with app.app_context():
        user, project, _ = _case()
        user_id, project_id = user.id, project.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/create_test",
        data={
            "title": "Ordinary test without data",
            "precondition": "",
            "step_action[]": ["Open the home page"],
            "step_expected[]": ["Home page is visible"],
        },
    )
    assert response.status_code == 302

    with app.app_context():
        test = TestCase.query.filter_by(
            project_id=project_id, title="Ordinary test without data"
        ).one()
        assert TestDataSet.query.filter_by(test_case_id=test.id).count() == 0


def test_inline_test_creation_encrypts_secret_values(app):
    from cryptography.fernet import Fernet
    from flask import current_app
    from app.test_data_crypto import decrypt_secret_values

    key = Fernet.generate_key().decode("ascii")
    with app.app_context():
        current_app.config["TEST_DATA_ENCRYPTION_KEY"] = key
        user, project, _ = _case()
        user_id, project_id = user.id, project.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/create_test",
        data={
            "title": "Login with secret inline data",
            "step_action[]": ["Enter {{login}} and {{password}}"],
            "step_expected[]": ["Account is opened"],
            "data_set_count": "1",
            "data_0_name": "Secret credentials",
            "default_data_set_index": "0",
            "data_0_column_key[]": ["login", "password"],
            "data_0_column_label[]": ["Логин", "Пароль"],
            "data_0_column_is_secret_1": "1",
            "data_0_row_name[]": ["Test account"],
            "data_0_row_0_value_0": "tester",
            "data_0_row_0_value_1": "never-store-this-plaintext",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        test = TestCase.query.filter_by(
            project_id=project_id, title="Login with secret inline data"
        ).one()
        dataset = TestDataSet.query.filter_by(test_case_id=test.id).one()
        row = dataset.rows[0]
        assert row.values_json == {"login": "tester"}
        assert "never-store-this-plaintext" not in (row.encrypted_values_json or "")
        assert decrypt_secret_values(row.encrypted_values_json) == {
            "password": "never-store-this-plaintext"
        }


def test_direct_test_run_uses_default_data_set_and_default_row(app):
    with app.app_context():
        user, project, _ = _case()
        test = TestCase(
            title="Default data run",
            precondition="Open {{base_url}}",
            steps="Enter {{login}}",
            expected_result="",
            project_id=project.id,
        )
        db.session.add(test)
        db.session.flush()
        step = TestStep(
            test_case_id=test.id, position=1,
            action="Enter {{login}}", expected_result="Welcome"
        )
        dataset = TestDataSet(
            test_case_id=test.id, name="Selected by default", is_default=True
        )
        db.session.add_all([step, dataset])
        db.session.flush()
        db.session.add_all([
            TestDataColumn(dataset_id=dataset.id, key="base_url", label="URL", position=0),
            TestDataColumn(dataset_id=dataset.id, key="login", label="Login", position=1),
        ])
        db.session.flush()
        db.session.add_all([
            TestDataRow(
                dataset_id=dataset.id, name="First row",
                values_json={"base_url": "https://first.test", "login": "first"},
                position=0, is_default=False
            ),
            TestDataRow(
                dataset_id=dataset.id, name="Default row",
                values_json={"base_url": "https://default.test", "login": "default"},
                position=1, is_default=True
            ),
        ])
        db.session.commit()
        user_id, project_id, test_id = user.id, project.id, test.id

    client = app.test_client()
    _login(client, user_id)
    response = client.get(f"/project/{project_id}/run?test_id={test_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Selected by default" in html
    assert "Default row" in html
    assert "https://default.test" in html
    assert "default" in html



def test_inline_test_creation_rolls_back_case_when_data_set_is_invalid(app):
    with app.app_context():
        user, project, _ = _case()
        user_id, project_id = user.id, project.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/create_test",
        data={
            "title": "Must roll back",
            "step_action[]": ["Use {{login}}"],
            "step_expected[]": ["Success"],
            "data_set_count": "1",
            "data_0_name": "Invalid set",
            "data_0_column_key[]": ["login", "login"],
            "data_0_column_label[]": ["Login", "Duplicate login"],
        },
    )
    assert response.status_code == 200

    with app.app_context():
        assert TestCase.query.filter_by(
            project_id=project_id, title="Must roll back"
        ).count() == 0
        assert TestDataSet.query.filter(
            TestDataSet.test_case_id.in_(
                db.session.query(TestCase.id).filter_by(title="Must roll back")
            )
        ).count() == 0



def test_test_detail_displays_marked_default_row_not_first_active_row(app):
    with app.app_context():
        user, project, case = _case()
        dataset = TestDataSet(
            test_case_id=case.id, name="Основные параметры", is_default=True
        )
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(
            dataset_id=dataset.id, key="login", label="Логин", position=0
        )
        first_row = TestDataRow(
            dataset_id=dataset.id, name="Первый вариант",
            values_json={"login": "first-user"}, is_enabled=True,
            is_default=False, position=0,
        )
        default_row = TestDataRow(
            dataset_id=dataset.id, name="Значения по умолчанию",
            values_json={"login": "default-user"}, is_enabled=True,
            is_default=True, position=1,
        )
        db.session.add_all([column, first_row, default_row])
        db.session.commit()
        user_id, project_id, case_id = user.id, project.id, case.id

    client = app.test_client()
    _login(client, user_id)
    response = client.get(f"/project/{project_id}/test/{case_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "default-user" in html
    assert "first-user" in html
    assert "Значения по умолчанию" in html

def test_inline_test_creation_supports_multiple_data_sets_and_default_rows(app):
    """All selected data sets and their rows are saved atomically at test creation."""
    with app.app_context():
        user, project, _ = _case()
        user_id, project_id = user.id, project.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/create_test",
        data={
            "title": "Create test with multiple data sets",
            "precondition": "Open {{base_url}}",
            "step_action[]": ["Sign in as {{login}}"],
            "step_expected[]": ["The account is opened"],
            "data_set_count": "2",
            "default_data_set_index": "1",
            "data_0_name": "Browser matrix",
            "data_0_column_key[]": ["browser", "locale"],
            "data_0_column_label[]": ["Браузер", "Язык"],
            "data_0_row_name[]": ["Chrome", "Firefox"],
            "data_0_default_row_index": "1",
            "data_0_row_0_value_0": "Chrome",
            "data_0_row_0_value_1": "ru-RU",
            "data_0_row_1_value_0": "Firefox",
            "data_0_row_1_value_1": "en-US",
            "data_1_name": "Accounts",
            "data_1_column_key[]": ["login"],
            "data_1_column_label[]": ["Логин"],
            "data_1_row_name[]": ["Demo account"],
            "data_1_default_row_index": "0",
            "data_1_row_0_value_0": "demo-user",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        test = TestCase.query.filter_by(
            project_id=project_id, title="Create test with multiple data sets"
        ).one()
        datasets = TestDataSet.query.filter_by(test_case_id=test.id).order_by(
            TestDataSet.id.asc()
        ).all()
        assert [dataset.name for dataset in datasets] == ["Browser matrix", "Accounts"]
        assert [dataset.is_default for dataset in datasets] == [False, True]

        browser_columns = sorted(datasets[0].columns, key=lambda item: item.position)
        assert [column.key for column in browser_columns] == ["browser", "locale"]
        browser_rows = sorted(datasets[0].rows, key=lambda item: item.position)
        assert [row.name for row in browser_rows] == ["Chrome", "Firefox"]
        assert [row.is_default for row in browser_rows] == [False, True]
        assert browser_rows[1].values_json == {"browser": "Firefox", "locale": "en-US"}

        account_columns = sorted(datasets[1].columns, key=lambda item: item.position)
        assert [column.key for column in account_columns] == ["login"]
        account_rows = list(datasets[1].rows)
        assert len(account_rows) == 1
        assert account_rows[0].is_default is True
        assert account_rows[0].values_json == {"login": "demo-user"}

