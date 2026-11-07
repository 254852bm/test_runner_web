import sqlite3
import sys

import pytest

from app import create_app, db
from app.models import (
    ApiToken, Project, StepRun, StepRunScreenshot,
    TestCase as CaseModel, TestRun as RunModel,
    TestStep as StepModel, TestStepScreenshot as StepScreenshotModel,
    User,
)
from scripts.add_test_data_encryption_columns import main


def _legacy_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE user (id INTEGER PRIMARY KEY);
            CREATE TABLE test_case (id INTEGER PRIMARY KEY);
            CREATE TABLE test_run (id INTEGER PRIMARY KEY);
            CREATE TABLE api_token (id INTEGER PRIMARY KEY, token TEXT);
            """
        )


def test_test_data_migration_adds_only_feature_tables_and_columns(tmp_path, monkeypatch):
    database = tmp_path / "legacy-test-runner.db"
    _legacy_database(database)
    monkeypatch.setattr(
        sys, "argv", ["add_test_data_encryption_columns.py", "--database", str(database)]
    )

    main()

    with sqlite3.connect(database) as connection:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {
            "user", "test_case", "test_run", "api_token",
            "test_data_set", "test_data_column", "test_data_row",
            "test_run_data_snapshot", "test_data_batch",
        }.issubset(tables)
        row_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(test_data_row)")
        }
        snapshot_columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(test_run_data_snapshot)"
            )
        }
        token_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(api_token)")
        }
        assert "encrypted_values_json" in row_columns
        assert "encrypted_values_snapshot" in snapshot_columns
        assert "allow_secret_data" in token_columns
        assert connection.execute(
            "SELECT dflt_value FROM pragma_table_info('api_token') "
            "WHERE name='allow_secret_data'"
        ).fetchone()[0] == "0"


def test_test_data_migration_is_idempotent(tmp_path, monkeypatch):
    database = tmp_path / "legacy-test-runner.db"
    _legacy_database(database)
    argv = [
        "add_test_data_encryption_columns.py", "--database", str(database)
    ]
    monkeypatch.setattr(sys, "argv", argv)

    main()
    main()

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='test_data_set'"
        ).fetchone()[0] == 1


def test_test_data_migration_preserves_existing_application_records(tmp_path, monkeypatch):
    database = tmp_path / "populated-legacy-test-runner.db"
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    app = create_app({
        "TESTING": True,
        "INSTANCE_PATH": str(instance_path),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database}",
    })

    with app.app_context():
        user = User(email="legacy@example.test", password="hashed-password")
        db.session.add(user)
        db.session.flush()
        project = Project(name="Legacy project", user_id=user.id)
        db.session.add(project)
        db.session.flush()
        case = CaseModel(
            title="Legacy test case",
            steps="Open the page",
            expected_result="Page is visible",
            project_id=project.id,
        )
        db.session.add(case)
        db.session.flush()
        step = StepModel(
            test_case_id=case.id,
            position=1,
            action="Open the page",
            expected_result="Page is visible",
        )
        db.session.add(step)
        db.session.flush()
        step_screenshot = StepScreenshotModel(
            test_step_id=step.id,
            user_id=user.id,
            stored_name="legacy-step.png",
            original_name="step.png",
            mime_type="image/png",
            size_bytes=128,
        )
        db.session.add(step_screenshot)
        run = RunModel(
            status="PASS",
            comment="Existing run must survive",
            test_case_id=case.id,
            user_id=user.id,
            source="auto",
            duration_ms=321,
        )
        token = ApiToken(
            user_id=user.id,
            token="legacy-api-token",
            name="Legacy token",
        )
        db.session.add_all([run, token])
        db.session.flush()
        step_run = StepRun(
            test_run_id=run.id,
            test_step_id=step.id,
            status="PASS",
            step_text="Open the page",
            expected_result="Page is visible",
        )
        db.session.add(step_run)
        db.session.flush()
        run_screenshot = StepRunScreenshot(
            step_run_id=step_run.id,
            user_id=user.id,
            stored_name="legacy-run.png",
            original_name="run.png",
            mime_type="image/png",
            size_bytes=256,
        )
        db.session.add_all([step_run, run_screenshot])
        db.session.commit()

    # Simulate the schema before the parameterization feature was installed.
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        for table in (
            "test_data_batch",
            "test_run_data_snapshot",
            "test_data_row",
            "test_data_column",
            "test_data_set",
        ):
            connection.execute(f'DROP TABLE IF EXISTS "{table}"')
        connection.execute(
            "ALTER TABLE api_token DROP COLUMN allow_secret_data"
        )
        connection.commit()

    monkeypatch.setattr(
        sys,
        "argv",
        ["add_test_data_encryption_columns.py", "--database", str(database)],
    )
    main()

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT email FROM user WHERE id=1"
        ).fetchone() == ("legacy@example.test",)
        assert connection.execute(
            "SELECT name FROM project WHERE id=1"
        ).fetchone() == ("Legacy project",)
        assert connection.execute(
            "SELECT title FROM test_case WHERE id=1"
        ).fetchone() == ("Legacy test case",)
        assert connection.execute(
            "SELECT status, comment, duration_ms FROM test_run WHERE id=1"
        ).fetchone() == ("PASS", "Existing run must survive", 321)
        assert connection.execute(
            "SELECT token, name FROM api_token WHERE id=1"
        ).fetchone() == ("legacy-api-token", "Legacy token")
        assert connection.execute(
            "SELECT action, expected_result FROM test_step WHERE id=1"
        ).fetchone() == ("Open the page", "Page is visible")
        assert connection.execute(
            "SELECT stored_name, size_bytes FROM test_step_screenshot WHERE id=1"
        ).fetchone() == ("legacy-step.png", 128)
        assert connection.execute(
            "SELECT status, step_text FROM step_run WHERE id=1"
        ).fetchone() == ("PASS", "Open the page")
        assert connection.execute(
            "SELECT stored_name, size_bytes FROM step_run_screenshot WHERE id=1"
        ).fetchone() == ("legacy-run.png", 256)
        assert connection.execute(
            """
            SELECT s.stored_name, r.status, t.action
            FROM step_run_screenshot AS s
            JOIN step_run AS r ON r.id = s.step_run_id
            JOIN test_step AS t ON t.id = r.test_step_id
            WHERE s.id = 1
            """
        ).fetchone() == ("legacy-run.png", "PASS", "Open the page")
        assert connection.execute(
            """
            SELECT s.stored_name, t.action
            FROM test_step_screenshot AS s
            JOIN test_step AS t ON t.id = s.test_step_id
            WHERE s.id = 1
            """
        ).fetchone() == ("legacy-step.png", "Open the page")
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT allow_secret_data FROM api_token WHERE id=1"
        ).fetchone()[0] == 0


def test_test_data_migration_refuses_to_create_missing_database(tmp_path, monkeypatch):
    database = tmp_path / "must-not-be-created.db"
    monkeypatch.setattr(
        sys, "argv", ["add_test_data_encryption_columns.py", "--database", str(database)]
    )

    with pytest.raises(SystemExit, match="Refusing to create"):
        main()

    assert not database.exists()
