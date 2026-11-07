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
