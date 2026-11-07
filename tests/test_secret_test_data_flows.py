import sqlite3

import pytest
from cryptography.fernet import Fernet

from app import create_app, db
from app.models import (
    ApiToken, Project, TestCase, TestDataColumn, TestDataRow,
    TestDataSet, TestRun, TestRunDataSnapshot, TestStep, StepRun, User,
)


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-session-key",
        "TEST_DATA_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "INSTANCE_PATH": str(instance_path),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'secret-data.sqlite'}",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _secret_case():
    user = User(email="secret-owner@example.test", password="not-a-real-password")
    db.session.add(user)
    db.session.flush()
    project = Project(name="Secret data project", user_id=user.id)
    db.session.add(project)
    db.session.flush()
    case = TestCase(
        title="Login with secret",
        precondition="Open {{base_url}}",
        steps="Enter {{login}} and {{password}}",
        expected_result="Dashboard for {{login}}",
        project_id=project.id,
    )
    db.session.add(case)
    db.session.flush()
    step = TestStep(
        test_case_id=case.id,
        position=1,
        action="Enter {{login}} and {{password}}",
        expected_result="Dashboard for {{login}}",
    )
    db.session.add(step)
    db.session.flush()
    dataset = TestDataSet(test_case_id=case.id, name="Credential examples")
    db.session.add(dataset)
    db.session.flush()
    db.session.add_all([
        TestDataColumn(
            dataset_id=dataset.id, key="base_url", label="Base URL", position=0
        ),
        TestDataColumn(
            dataset_id=dataset.id, key="login", label="Login", position=1
        ),
        TestDataColumn(
            dataset_id=dataset.id, key="password", label="Password",
            position=2, is_secret=True,
        ),
    ])
    from app.test_data_crypto import encrypt_secret_values
    row = TestDataRow(
        dataset_id=dataset.id,
        name="QA account",
        values_json={
            "base_url": "https://example.test",
            "login": "qa@example.test",
        },
        encrypted_values_json=encrypt_secret_values({"password": "secret-phrase-123"}),
        is_enabled=True,
    )
    db.session.add(row)
    token = ApiToken(user_id=user.id, token="secret-api-token-123", name="Secret test")
    db.session.add(token)
    db.session.commit()
    return user, project, case, dataset, row, step, token


def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_manual_run_never_persists_decrypted_secret_in_history(app):
    with app.app_context():
        user, project, case, dataset, row, step, token = _secret_case()
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
    page = response.get_data(as_text=True)
    # The decrypted secret must not be present anywhere in the initial HTML.
    assert "secret-phrase-123" not in page
    assert 'type="password" value=""' in page
    assert "Показать" in page
    assert "qa@example.test" in page

    reveal_url = (
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}"
        f"/rows/{row_id}/secrets/"
    )
    with app.app_context():
        secret_column_id = TestDataColumn.query.filter_by(
            dataset_id=dataset_id, key="password"
        ).one().id
    import re
    csrf_match = re.search(r'data-csrf-token="([^"]+)"', page)
    assert csrf_match, "CSRF token must be present for the explicit reveal action"
    reveal_response = client.post(
        reveal_url + str(secret_column_id),
        headers={"X-CSRFToken": csrf_match.group(1)},
    )
    assert reveal_response.status_code == 200
    assert reveal_response.get_json()["value"] == "secret-phrase-123"
    assert reveal_response.headers["Cache-Control"].startswith("no-store")

    response = client.post(
        url,
        data={
            "step_status[]": ["PASS"],
            "step_comment[]": ["Confirmed secret-phrase-123 works"],
        },
    )
    assert response.status_code == 302

    with app.app_context():
        run = TestRun.query.filter_by(test_case_id=case_id).one()
        step_run = StepRun.query.filter_by(test_run_id=run.id).one()
        snapshot = TestRunDataSnapshot.query.filter_by(test_run_id=run.id).one()
        assert "secret-phrase-123" not in step_run.step_text
        assert "secret-phrase-123" not in step_run.expected_result
        assert "secret-phrase-123" not in step_run.comment
        assert "••••••" in step_run.step_text
        assert "secret-phrase-123" not in str(snapshot.values_snapshot_json)
        assert "secret-phrase-123" not in snapshot.encrypted_values_snapshot
        assert "qa@example.test" in str(snapshot.values_snapshot_json)


def test_api_hides_secret_by_default_and_requires_explicit_header_to_retrieve(app):
    with app.app_context():
        user, project, case, dataset, row, step, token = _secret_case()
        dataset_id = dataset.id

    client = app.test_client()
    headers = {"Authorization": "Bearer secret-api-token-123"}
    response = client.get(f"/api/data-sets/{dataset_id}/rows", headers=headers)
    assert response.status_code == 200
    assert "secret-phrase-123" not in response.get_data(as_text=True)
    assert response.get_json()["secrets_included"] is False

    headers["X-Test-Runner-Include-Secrets"] = "true"
    response = client.get(f"/api/data-sets/{dataset_id}/rows", headers=headers)
    assert response.status_code == 403
    with app.app_context():
        token = ApiToken.query.filter_by(token="secret-api-token-123").one()
        token.allow_secret_data = True
        db.session.commit()
    response = client.get(f"/api/data-sets/{dataset_id}/rows", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["secrets_included"] is True
    assert response.get_json()["rows"][0]["values"]["password"] == "secret-phrase-123"
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["Pragma"] == "no-cache"


def test_api_run_encrypts_secret_snapshot_and_redacts_step_results(app):
    with app.app_context():
        user, project, case, dataset, row, step, token = _secret_case()
        case_id, dataset_id, row_id, step_id = case.id, dataset.id, row.id, step.id

    response = app.test_client().post(
        "/api/run",
        headers={"Authorization": "Bearer secret-api-token-123"},
        json={
            "test_case_id": case_id,
            "data_set_id": dataset_id,
            "data_row_id": row_id,
            "status": "PASS",
            "comment": "API result included secret-phrase-123",
            "step_results": [{
                "step_id": step_id,
                "status": "PASS",
                "actual_result": "Logged in with secret-phrase-123",
            }],
        },
    )
    assert response.status_code == 201

    with app.app_context():
        run = TestRun.query.filter_by(test_case_id=case_id, source="auto").one()
        snapshot = TestRunDataSnapshot.query.filter_by(test_run_id=run.id).one()
        step_run = StepRun.query.filter_by(test_run_id=run.id).one()
        assert "secret-phrase-123" not in step_run.step_text
        assert "secret-phrase-123" not in step_run.expected_result
        assert "secret-phrase-123" not in step_run.actual_result
        assert "secret-phrase-123" not in run.comment
        assert "secret-phrase-123" not in str(snapshot.values_snapshot_json)
        assert "secret-phrase-123" not in snapshot.encrypted_values_snapshot


def test_secret_values_are_not_available_when_encryption_key_is_missing(app):
    with app.app_context():
        user, project, case, dataset, row, step, token = _secret_case()
        dataset_id = dataset.id
        token.allow_secret_data = True
        db.session.commit()
    app.config["TEST_DATA_ENCRYPTION_KEY"] = ""
    response = app.test_client().get(
        f"/api/data-sets/{dataset_id}/rows",
        headers={
            "Authorization": "Bearer secret-api-token-123",
            "X-Test-Runner-Include-Secrets": "true",
        },
    )
    assert response.status_code == 503
    assert "secret-phrase-123" not in response.get_data(as_text=True)


def test_encryption_migration_adds_columns_without_creating_database(tmp_path):
    database_path = tmp_path / "existing.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE user (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE test_case (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE test_run (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE api_token (id INTEGER PRIMARY KEY)")
    import subprocess
    import sys
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "add_test_data_encryption_columns.py"),
            "--database", str(database_path),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        row_columns = {row[1] for row in connection.execute("PRAGMA table_info(test_data_row)")}
        snapshot_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(test_run_data_snapshot)")
        }
        token_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(api_token)")
        }
    assert {"test_data_set", "test_data_column", "test_data_row", "test_run_data_snapshot", "test_data_batch"} <= tables
    assert "encrypted_values_json" in row_columns
    assert "encrypted_values_snapshot" in snapshot_columns
    assert "allow_secret_data" in token_columns


def test_encryption_migration_refuses_missing_database(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[1]
    missing_path = tmp_path / "must-not-be-created.sqlite"
    result = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "add_test_data_encryption_columns.py"),
            "--database", str(missing_path),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not missing_path.exists()


def test_secret_row_crud_uses_encrypted_storage_and_never_prefills_secret(app):
    with app.app_context():
        user, project, case, dataset, row, step, token = _secret_case()
        user_id, project_id, case_id = user.id, project.id, case.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/create",
        data={
            "dataset_name": "New credentials",
            "column_key[]": ["login", "password"],
            "column_label[]": ["Login", "Password"],
            "column_is_secret_1": "1",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        created_dataset = TestDataSet.query.filter_by(
            test_case_id=case_id, name="New credentials"
        ).one()
        password_column = next(
            column for column in created_dataset.columns if column.key == "password"
        )
        assert password_column.is_secret is True
        dataset_id, password_column_id = created_dataset.id, password_column.id
        login_column_id = next(
            column.id for column in created_dataset.columns if column.key == "login"
        )

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/create",
        data={
            "row_name": "Created credential",
            f"value_{login_column_id}": "new@example.test",
            f"secret_value_{password_column_id}": "new-secret-value",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        created_row = TestDataRow.query.filter_by(dataset_id=dataset_id).one()
        row_id = created_row.id
        assert "password" not in created_row.values_json
        assert "new-secret-value" not in str(created_row.values_json)
        assert created_row.encrypted_values_json
        assert "new-secret-value" not in created_row.encrypted_values_json

    response = client.get(f"/project/{project_id}/test/{case_id}/data")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "new-secret-value" not in page
    assert "Оставьте пустым, чтобы не менять секрет." in page

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/{row_id}/edit",
        data={
            "row_name": "Updated credential",
            f"value_{login_column_id}": "updated@example.test",
            f"secret_value_{password_column_id}": "",
        },
    )
    assert response.status_code == 302
    from app.test_data_crypto import decrypt_secret_values
    with app.app_context():
        edited_row = db.session.get(TestDataRow, row_id)
        assert decrypt_secret_values(edited_row.encrypted_values_json)["password"] == "new-secret-value"

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/rows/{row_id}/edit",
        data={
            "row_name": "Cleared credential",
            f"value_{login_column_id}": "updated@example.test",
            f"clear_secret_{password_column_id}": "1",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        edited_row = db.session.get(TestDataRow, row_id)
        assert decrypt_secret_values(edited_row.encrypted_values_json) == {}


def test_api_token_secret_permission_is_opt_in_and_user_managed(app):
    with app.app_context():
        user, project, case, dataset, row, step, token = _secret_case()
        user_id, token_id = user.id, token.id
        assert token.allow_secret_data is False

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/settings/api/{token_id}/secret-access",
        data={"allow_secret_data": "1"},
    )
    assert response.status_code == 302
    with app.app_context():
        token = db.session.get(ApiToken, token_id)
        assert token.allow_secret_data is True

    response = client.post(
        f"/settings/api/{token_id}/secret-access",
        data={"allow_secret_data": "0"},
    )
    assert response.status_code == 302
    with app.app_context():
        token = db.session.get(ApiToken, token_id)
        assert token.allow_secret_data is False


def test_column_structure_edits_move_current_values_but_preserve_run_snapshots(app):
    from app.test_data_crypto import decrypt_secret_values, encrypt_secret_values

    with app.app_context():
        user, project, case, dataset, row, step, token = _secret_case()
        run = TestRun(
            status="PASS", test_case_id=case.id, user_id=user.id,
            source="manual", comment="historical",
        )
        db.session.add(run)
        db.session.flush()
        snapshot = TestRunDataSnapshot(
            test_run_id=run.id,
            dataset_id=dataset.id,
            data_row_id=row.id,
            dataset_name_snapshot=dataset.name,
            row_name_snapshot=row.name,
            values_snapshot_json={"login": "qa@example.test"},
            encrypted_values_snapshot=encrypt_secret_values(
                {"password": "secret-phrase-123"}
            ),
        )
        db.session.add(snapshot)
        db.session.commit()
        user_id, project_id, case_id = user.id, project.id, case.id
        dataset_id, row_id = dataset.id, row.id
        login_column = next(column for column in dataset.columns if column.key == "login")
        password_column = next(column for column in dataset.columns if column.key == "password")
        base_url_column = next(column for column in dataset.columns if column.key == "base_url")
        login_column_id, password_column_id, base_url_column_id = (
            login_column.id, password_column.id, base_url_column.id
        )
        snapshot_id = snapshot.id
        old_encrypted_snapshot = snapshot.encrypted_values_snapshot

    client = app.test_client()
    _login(client, user_id)

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/columns/{login_column_id}/edit",
        data={"column_key": "username", "column_label": "User name"},
    )
    assert response.status_code == 302
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/columns/{password_column_id}/edit",
        data={"column_key": "credential", "column_label": "Credential"},
    )
    assert response.status_code == 302

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/columns/add",
        data={
            "column_key": "expected_message",
            "column_label": "Expected message",
        },
    )
    assert response.status_code == 302

    with app.app_context():
        edited_row = db.session.get(TestDataRow, row_id)
        assert edited_row.values_json["username"] == "qa@example.test"
        assert "login" not in edited_row.values_json
        encrypted_values = decrypt_secret_values(edited_row.encrypted_values_json)
        assert encrypted_values["credential"] == "secret-phrase-123"
        assert "password" not in encrypted_values
        snapshot = db.session.get(TestRunDataSnapshot, snapshot_id)
        assert snapshot.values_snapshot_json == {"login": "qa@example.test"}
        assert snapshot.encrypted_values_snapshot == old_encrypted_snapshot

    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/columns/{base_url_column_id}/delete"
    )
    assert response.status_code == 302
    response = client.post(
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}/columns/{password_column_id}/delete"
    )
    assert response.status_code == 302

    with app.app_context():
        edited_row = db.session.get(TestDataRow, row_id)
        assert "base_url" not in edited_row.values_json
        assert decrypt_secret_values(edited_row.encrypted_values_json) == {}
        snapshot = db.session.get(TestRunDataSnapshot, snapshot_id)
        assert snapshot.encrypted_values_snapshot == old_encrypted_snapshot



def test_manual_secret_reveal_requires_csrf_and_project_ownership(app):
    with app.app_context():
        user, project, case, dataset, row, step, token = _secret_case()
        owner_id, project_id, case_id = user.id, project.id, case.id
        dataset_id, row_id = dataset.id, row.id
        column_id = TestDataColumn.query.filter_by(
            dataset_id=dataset_id, key="password"
        ).one().id
        from werkzeug.security import generate_password_hash
        stranger_password = "stranger-test-password"
        stranger = User(
            email="stranger@example.test",
            password=generate_password_hash(stranger_password),
        )
        db.session.add(stranger)
        db.session.commit()
        stranger_id = stranger.id

    endpoint = (
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}"
        f"/rows/{row_id}/secrets/{column_id}"
    )
    owner_client = app.test_client()
    _login(owner_client, owner_id)

    missing_csrf = owner_client.post(endpoint)
    assert missing_csrf.status_code == 400

    stranger_client = app.test_client()
    login_response = stranger_client.post(
        "/auth/login",
        data={"email": "stranger@example.test", "password": stranger_password},
    )
    assert login_response.status_code == 302
    from flask import session as flask_session
    from flask_wtf.csrf import generate_csrf

    # Generate a valid CSRF token and copy its backing session value while
    # preserving the authenticated session established by the real login route.
    with app.test_request_context():
        csrf_token = generate_csrf()
        csrf_session_token = flask_session["csrf_token"]
    with stranger_client.session_transaction() as client_session:
        client_session["csrf_token"] = csrf_session_token
    forbidden = stranger_client.post(
        endpoint, headers={"X-CSRFToken": csrf_token}
    )
    assert forbidden.status_code == 404
    assert "secret-phrase-123" not in forbidden.get_data(as_text=True)


def test_manual_secret_reveal_rejects_missing_or_invalid_csrf_token(app):
    with app.app_context():
        user, project, case, dataset, row, step, token = _secret_case()
        user_id, project_id, case_id = user.id, project.id, case.id
        dataset_id, row_id = dataset.id, row.id
        secret_column_id = TestDataColumn.query.filter_by(
            dataset_id=dataset_id, key="password"
        ).one().id

    client = app.test_client()
    _login(client, user_id)
    endpoint = (
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}"
        f"/rows/{row_id}/secrets/{secret_column_id}"
    )
    assert client.post(endpoint).status_code == 400
    assert client.post(
        endpoint, headers={"X-CSRFToken": "invalid-token"}
    ).status_code == 400


def test_manual_secret_reveal_rejects_another_users_session(app):
    with app.app_context():
        user, project, case, dataset, row, step, token = _secret_case()
        user_id, project_id, case_id = user.id, project.id, case.id
        dataset_id, row_id = dataset.id, row.id
        secret_column_id = TestDataColumn.query.filter_by(
            dataset_id=dataset_id, key="password"
        ).one().id
        other_user = User(
            email="another-user@example.test",
            password="not-a-real-password",
        )
        db.session.add(other_user)
        db.session.commit()
        other_user_id = other_user.id

    client = app.test_client()
    _login(client, user_id)
    page = client.get(
        f"/project/{project_id}/run?test_id={case_id}"
        f"&data_set_id={dataset_id}&data_row_id={row_id}"
    )
    assert page.status_code == 200
    import re
    csrf_match = re.search(
        r'data-csrf-token="([^"]+)"', page.get_data(as_text=True)
    )
    assert csrf_match

    _login(client, other_user_id)
    endpoint = (
        f"/project/{project_id}/test/{case_id}/data/{dataset_id}"
        f"/rows/{row_id}/secrets/{secret_column_id}"
    )
    response = client.post(
        endpoint, headers={"X-CSRFToken": csrf_match.group(1)}
    )
    assert response.status_code == 404
    assert "secret-phrase-123" not in response.get_data(as_text=True)
