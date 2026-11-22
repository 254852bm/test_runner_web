import pytest

from app import create_app, db
from app.models import (
    Project, TestCase, TestDataColumn, TestDataRow, TestDataSet,
    TestRun, TestRunDataSnapshot, User,
)


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    database_path = tmp_path / "parameterization.sqlite"
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


def _case_with_run():
    user = User(email="parameterization@example.test", password="not-a-real-password")
    db.session.add(user)
    db.session.flush()
    project = Project(name="Parameterization project", user_id=user.id)
    db.session.add(project)
    db.session.flush()
    case = TestCase(
        title="Login test", precondition="",
        steps="Enter {{login}}", expected_result="",
        project_id=project.id,
    )
    db.session.add(case)
    db.session.flush()
    run = TestRun(status="PASS", test_case_id=case.id, user_id=user.id)
    db.session.add(run)
    db.session.commit()
    return user, case, run


def test_data_set_columns_and_rows_are_persisted_in_isolated_database(app):
    with app.app_context():
        user, case, run = _case_with_run()
        dataset = TestDataSet(test_case_id=case.id, name="Login examples")
        db.session.add(dataset)
        db.session.flush()
        db.session.add_all([
            TestDataColumn(dataset_id=dataset.id, key="login", label="Логин", position=0),
            TestDataColumn(dataset_id=dataset.id, key="expected", label="Ожидаемый результат", position=1),
        ])
        row = TestDataRow(
            dataset_id=dataset.id,
            name="Valid user",
            values_json={"login": "qa@example.test", "expected": "Dashboard"},
            is_enabled=True,
            position=0,
        )
        db.session.add(row)
        db.session.commit()

        saved = db.session.get(TestDataSet, dataset.id)
        assert saved.test_case_id == case.id
        assert [column.key for column in saved.columns] == ["login", "expected"]
        assert saved.rows[0].values_json == {
            "login": "qa@example.test", "expected": "Dashboard"
        }


def test_duplicate_column_key_is_rejected_within_dataset(app):
    with app.app_context():
        user, case, run = _case_with_run()
        dataset = TestDataSet(test_case_id=case.id, name="Duplicate columns")
        db.session.add(dataset)
        db.session.flush()
        db.session.add_all([
            TestDataColumn(dataset_id=dataset.id, key="login", label="Login", position=0),
            TestDataColumn(dataset_id=dataset.id, key="login", label="Second login", position=1),
        ])
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()


def test_run_snapshot_keeps_original_values_after_data_row_is_edited(app):
    with app.app_context():
        user, case, run = _case_with_run()
        dataset = TestDataSet(test_case_id=case.id, name="Accounts")
        db.session.add(dataset)
        db.session.flush()
        row = TestDataRow(
            dataset_id=dataset.id, name="Initial row",
            values_json={"login": "first@example.test"}, position=0,
        )
        db.session.add(row)
        db.session.flush()
        snapshot = TestRunDataSnapshot(
            test_run_id=run.id,
            dataset_id=dataset.id,
            data_row_id=row.id,
            dataset_name_snapshot=dataset.name,
            row_name_snapshot=row.name,
            values_snapshot_json=dict(row.values_json),
        )
        db.session.add(snapshot)
        db.session.commit()
        snapshot_id = snapshot.id

        row.name = "Renamed row"
        row.values_json = {"login": "changed@example.test"}
        dataset.name = "Renamed set"
        db.session.commit()

        saved = db.session.get(TestRunDataSnapshot, snapshot_id)
        assert saved.dataset_name_snapshot == "Accounts"
        assert saved.row_name_snapshot == "Initial row"
        assert saved.values_snapshot_json == {"login": "first@example.test"}


def test_run_can_exist_without_parameterization_snapshot(app):
    with app.app_context():
        user, case, run = _case_with_run()
        saved = db.session.get(TestRun, run.id)
        assert saved.data_snapshot is None


def test_dataset_deletion_cascades_its_columns_and_rows(app):
    with app.app_context():
        user, case, run = _case_with_run()
        dataset = TestDataSet(test_case_id=case.id, name="Temporary")
        db.session.add(dataset)
        db.session.flush()
        column = TestDataColumn(
            dataset_id=dataset.id, key="login", label="Login", position=0
        )
        row = TestDataRow(
            dataset_id=dataset.id, name="One",
            values_json={"login": "user"}, position=0
        )
        db.session.add_all([column, row])
        db.session.commit()
        dataset_id, column_id, row_id = dataset.id, column.id, row.id

        db.session.delete(db.session.get(TestDataSet, dataset_id))
        db.session.commit()

        assert db.session.get(TestDataColumn, column_id) is None
        assert db.session.get(TestDataRow, row_id) is None
