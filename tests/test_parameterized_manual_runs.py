import pytest

from app import create_app, db
from app.models import (
    Project, TestCase, TestDataColumn, TestDataRow, TestDataSet,
    TestRun, TestRunDataSnapshot, TestStep, StepRun, User,
)


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    database_path = tmp_path / "parameterized-run.sqlite"
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


def _parameterized_case():
    user = User(email="run-data@example.test", password="not-a-real-password")
    db.session.add(user)
    db.session.flush()
    project = Project(name="Run data project", user_id=user.id)
    db.session.add(project)
    db.session.flush()
    case = TestCase(
        title="Parameterized test",
        precondition="Open {{base_url}}",
        steps="Enter {{login}}",
        expected_result="",
        project_id=project.id,
    )
    db.session.add(case)
    db.session.flush()
    step = TestStep(
        test_case_id=case.id, position=1,
        action="Enter {{login}}",
        expected_result="Welcome {{login}}",
    )
    db.session.add(step)
    db.session.flush()
    dataset = TestDataSet(test_case_id=case.id, name="Accounts")
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
    row = TestDataRow(
        dataset_id=dataset.id, name="Valid user",
        values_json={
            "base_url": "https://example.test",
            "login": "qa@example.test",
        },
        is_enabled=True,
    )
    db.session.add(row)
    db.session.commit()
    return user, project, case, dataset, row


def test_manual_run_substitutes_values_and_saves_immutable_snapshot(app):
    with app.app_context():
        user, project, case, dataset, row = _parameterized_case()
        user_id, project_id, case_id = user.id, project.id, case.id
        dataset_id, row_id = dataset.id, row.id

    client = app.test_client()
    _login(client, user_id)
    url = (
        f"/project/{project_id}/run?test_id={case_id}"
        f"&data_set_id={dataset_id}&data_row_id={row_id}"
    )

    response = client.get(url)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Open https://example.test" in html
    assert "Enter qa@example.test" in html
    assert "Welcome qa@example.test" in html
    assert "Accounts" in html
    assert "Valid user" in html

    response = client.post(
        url,
        data={"step_status[]": ["PASS"], "step_comment[]": ["Looks good"]},
        follow_redirects=False,
    )
    assert response.status_code == 302, (
        f"POST returned {response.status_code}; page content: "
        + response.get_data(as_text=True)[:5000]
    )

    with app.app_context():
        run = TestRun.query.filter_by(test_case_id=case_id).one()
        step_run = StepRun.query.filter_by(test_run_id=run.id).one()
        snapshot = TestRunDataSnapshot.query.filter_by(test_run_id=run.id).one()
        assert step_run.step_text == "Enter qa@example.test"
        assert step_run.expected_result == "Welcome qa@example.test"
        assert step_run.comment == "Looks good"
        assert snapshot.dataset_name_snapshot == "Accounts"
        assert snapshot.row_name_snapshot == "Valid user"
        assert snapshot.values_snapshot_json == {
            "base_url": "https://example.test",
            "login": "qa@example.test",
        }
        project_id = run.test_case.project_id

    history_response = app.test_client().get(f"/project/{project_id}/history")
    assert history_response.status_code == 302  # Login is required for a fresh client.
    history_client = app.test_client()
    _login(history_client, user_id)
    history_response = history_client.get(f"/project/{project_id}/history")
    assert history_response.status_code == 200
    assert "Accounts" in history_response.get_data(as_text=True)
    assert "Valid user" in history_response.get_data(as_text=True)


def test_manual_run_without_data_parameters_still_works(app):
    with app.app_context():
        user, project, case, dataset, row = _parameterized_case()
        user_id, project_id, case_id = user.id, project.id, case.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/run?test_id={case_id}",
        data={"step_status[]": ["PASS"], "step_comment[]": ["Legacy flow"]},
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        run = TestRun.query.filter_by(test_case_id=case_id).one()
        assert run.data_snapshot is None
        step_run = StepRun.query.filter_by(test_run_id=run.id).one()
        assert step_run.step_text == "Enter {{login}}"


def test_manual_run_rejects_unknown_placeholder_without_creating_run(app):
    with app.app_context():
        user, project, case, dataset, row = _parameterized_case()
        case.precondition = "Open {{unknown}}"
        db.session.commit()
        user_id, project_id, case_id = user.id, project.id, case.id
        dataset_id, row_id = dataset.id, row.id

    client = app.test_client()
    _login(client, user_id)
    response = client.get(
        f"/project/{project_id}/run?test_id={case_id}"
        f"&data_set_id={dataset_id}&data_row_id={row_id}",
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        assert TestRun.query.filter_by(test_case_id=case_id).count() == 0
