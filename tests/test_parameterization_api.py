import pytest

from app import create_app, db
from app.models import (
    ApiToken, Project, TestCase, TestDataColumn, TestDataRow,
    TestDataSet, TestRun, TestStep, StepRun, User,
)


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    database_path = tmp_path / "parameterization-api.sqlite"
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


def _api_objects():
    user = User(email="api-owner@example.test", password="not-a-real-password")
    db.session.add(user)
    db.session.flush()
    project = Project(name="API project", user_id=user.id)
    db.session.add(project)
    db.session.flush()
    case = TestCase(
        title="API data test", steps="Open {{base_url}}",
        expected_result="", project_id=project.id,
    )
    db.session.add(case)
    db.session.flush()
    step = TestStep(
        test_case_id=case.id, position=1,
        action="Open {{base_url}}", expected_result="Dashboard",
    )
    db.session.add(step)
    token = ApiToken(user_id=user.id, token="api-test-token-123", name="Test token")
    db.session.add(token)
    dataset = TestDataSet(test_case_id=case.id, name="API accounts")
    db.session.add(dataset)
    db.session.flush()
    columns = [
        TestDataColumn(
            dataset_id=dataset.id, key="base_url", label="Base URL", position=0
        ),
        TestDataColumn(
            dataset_id=dataset.id, key="login", label="Login", position=1
        ),
        TestDataColumn(
            dataset_id=dataset.id, key="password", label="Password",
            position=2, is_secret=False,
        ),
    ]
    db.session.add_all(columns)
    row = TestDataRow(
        dataset_id=dataset.id, name="Active account",
        values_json={
            "base_url": "https://example.test",
            "login": "qa@example.test",
            "password": "must-not-leak",
        },
        is_enabled=True, position=0,
    )
    disabled_row = TestDataRow(
        dataset_id=dataset.id, name="Disabled account",
        values_json={"base_url": "https://disabled.test", "login": "disabled"},
        is_enabled=False, position=1,
    )
    db.session.add_all([row, disabled_row])
    db.session.commit()
    return user, project, case, dataset, row, token


def test_api_returns_data_sets_and_active_rows_without_secret_like_values(app):
    with app.app_context():
        user, project, case, dataset, row, token = _api_objects()
        case_id, dataset_id = case.id, dataset.id

    client = app.test_client()
    headers = {"Authorization": "Bearer api-test-token-123"}

    response = client.get(f"/api/test-cases/{case_id}/data-sets", headers=headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["data_sets"][0]["name"] == "API accounts"
    columns = {column["key"]: column for column in payload["data_sets"][0]["columns"]}
    assert columns["base_url"]["is_secret"] is False
    assert columns["password"]["is_secret"] is True
    assert payload["data_sets"][0]["active_rows_count"] == 1

    response = client.get(f"/api/data-sets/{dataset_id}/rows", headers=headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["name"] == "Active account"
    assert payload["rows"][0]["values"] == {
        "base_url": "https://example.test",
        "login": "qa@example.test",
    }
    assert "password" not in response.get_data(as_text=True)
    assert "must-not-leak" not in response.get_data(as_text=True)


def test_data_api_requires_token(app):
    with app.app_context():
        user, project, case, dataset, row, token = _api_objects()
        case_id = case.id
    response = app.test_client().get(f"/api/test-cases/{case_id}/data-sets")
    assert response.status_code == 401


def test_data_api_does_not_expose_another_users_data(app):
    with app.app_context():
        owner, project, case, dataset, row, token = _api_objects()
        other = User(email="api-other@example.test", password="not-a-real-password")
        db.session.add(other)
        db.session.flush()
        other_token = ApiToken(
            user_id=other.id, token="other-api-token-123", name="Other token"
        )
        db.session.add(other_token)
        db.session.commit()
        case_id, dataset_id = case.id, dataset.id

    client = app.test_client()
    headers = {"X-API-Token": "other-api-token-123"}
    response = client.get(f"/api/test-cases/{case_id}/data-sets", headers=headers)
    assert response.status_code == 403
    response = client.get(f"/api/data-sets/{dataset_id}/rows", headers=headers)
    assert response.status_code == 403


def test_existing_api_run_contract_still_works(app):
    with app.app_context():
        user, project, case, dataset, row, token = _api_objects()
        case_id = case.id
        step_id = TestStep.query.filter_by(test_case_id=case.id).one().id

    response = app.test_client().post(
        "/api/run",
        json={
            "token": "api-test-token-123",
            "test_case_id": case_id,
            "status": "PASS",
            "comment": "Legacy automation client",
            "duration_ms": 1234,
            "step_results": [
                {"step_id": step_id, "status": "PASS", "actual_result": "OK"}
            ],
        },
    )
    assert response.status_code == 201
    with app.app_context():
        run = TestRun.query.filter_by(test_case_id=case_id, source="auto").one()
        step_run = StepRun.query.filter_by(test_run_id=run.id).one()
        assert step_run.actual_result == "OK"
        assert step_run.step_text == "Open {{base_url}}"
