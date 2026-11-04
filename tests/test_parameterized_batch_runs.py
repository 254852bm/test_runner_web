import pytest

from app import create_app, db
from app.models import (
    Project, TestCase, TestDataBatch, TestDataColumn, TestDataRow, TestDataSet,
    TestRun, TestRunDataSnapshot, TestStep, User,
)


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    database_path = tmp_path / "parameterized-batch.sqlite"
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


def _batch_case():
    user = User(email="batch@example.test", password="not-a-real-password")
    db.session.add(user)
    db.session.flush()
    project = Project(name="Batch project", user_id=user.id)
    db.session.add(project)
    db.session.flush()
    case = TestCase(
        title="Batch login", precondition="Open {{base_url}}",
        steps="Enter {{login}}", expected_result="",
        project_id=project.id,
    )
    db.session.add(case)
    db.session.flush()
    step = TestStep(
        test_case_id=case.id, position=1,
        action="Enter {{login}}", expected_result="Welcome {{login}}",
    )
    db.session.add(step)
    db.session.flush()
    dataset = TestDataSet(test_case_id=case.id, name="Batch accounts")
    db.session.add(dataset)
    db.session.flush()
    db.session.add_all([
        TestDataColumn(
            dataset_id=dataset.id, key="base_url", label="Base URL", position=0
        ),
        TestDataColumn(
            dataset_id=dataset.id, key="login", label="Login", position=1
        ),
    ])
    first = TestDataRow(
        dataset_id=dataset.id, name="First user",
        values_json={"base_url": "https://example.test", "login": "first@example.test"},
        is_enabled=True, position=0,
    )
    second = TestDataRow(
        dataset_id=dataset.id, name="Second user",
        values_json={"base_url": "https://example.test", "login": "second@example.test"},
        is_enabled=True, position=1,
    )
    disabled = TestDataRow(
        dataset_id=dataset.id, name="Disabled user",
        values_json={"base_url": "https://example.test", "login": "disabled@example.test"},
        is_enabled=False, position=2,
    )
    db.session.add_all([first, second, disabled])
    db.session.commit()
    return user, project, case, dataset, first, second, disabled


def test_sequential_run_creates_one_run_per_active_row_and_finishes_batch(app):
    with app.app_context():
        user, project, case, dataset, first, second, disabled = _batch_case()
        user_id, project_id, case_id, dataset_id = user.id, project.id, case.id, dataset.id

    client = app.test_client()
    _login(client, user_id)
    start_url = (
        f"/project/{project_id}/run?test_id={case_id}"
        f"&data_set_id={dataset_id}&run_all=1"
    )
    start = client.get(start_url, follow_redirects=False)
    assert start.status_code == 302
    first_url = start.headers["Location"]

    first_page = client.get(first_url)
    assert first_page.status_code == 200
    first_html = first_page.get_data(as_text=True)
    assert "Итерация 1 из 2" in first_html
    assert "first@example.test" in first_html
    assert "disabled@example.test" not in first_html

    first_post = client.post(
        first_url,
        data={"step_status[]": ["PASS"], "step_comment[]": ["First iteration"]},
        follow_redirects=False,
    )
    assert first_post.status_code == 302
    second_url = first_post.headers["Location"]
    assert "data_index=1" in second_url

    second_page = client.get(second_url)
    assert second_page.status_code == 200
    second_html = second_page.get_data(as_text=True)
    assert "Итерация 2 из 2" in second_html
    assert "second@example.test" in second_html

    second_post = client.post(
        second_url,
        data={"step_status[]": ["FAIL"], "step_comment[]": ["Second iteration failed"]},
        follow_redirects=False,
    )
    assert second_post.status_code == 302
    assert "/stats" in second_post.headers["Location"]

    with app.app_context():
        runs = TestRun.query.filter_by(test_case_id=case_id).order_by(TestRun.id).all()
        assert len(runs) == 2
        snapshots = [run.data_snapshot for run in runs]
        assert [snapshot.row_name_snapshot for snapshot in snapshots] == [
            "First user", "Second user"
        ]
        assert [snapshot.values_snapshot_json["login"] for snapshot in snapshots] == [
            "first@example.test", "second@example.test"
        ]
        assert [run.status for run in runs] == ["PASS", "FAIL"]
        assert TestDataBatch.query.filter_by(user_id=user_id).count() == 0


def test_sequential_batch_cannot_be_used_by_another_user(app):
    with app.app_context():
        user, project, case, dataset, first, second, disabled = _batch_case()
        other = User(email="batch-other@example.test", password="not-a-real-password")
        db.session.add(other)
        db.session.flush()
        batch = TestDataBatch(
            token="private-batch-token",
            user_id=user.id,
            test_case_id=case.id,
            dataset_id=dataset.id,
            row_ids_json=[first.id, second.id],
            next_index=0,
        )
        db.session.add(batch)
        db.session.commit()
        other_id, project_id, case_id, dataset_id = (
            other.id, project.id, case.id, dataset.id
        )

    client = app.test_client()
    _login(client, other_id)
    response = client.get(
        f"/project/{project_id}/run?test_id={case_id}&data_set_id={dataset_id}"
        "&run_all=1&batch_id=private-batch-token&data_index=0"
    )
    assert response.status_code == 404
