import sqlite3
import sys

import pytest

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


def test_test_data_migration_refuses_to_create_missing_database(tmp_path, monkeypatch):
    database = tmp_path / "must-not-be-created.db"
    monkeypatch.setattr(
        sys, "argv", ["add_test_data_encryption_columns.py", "--database", str(database)]
    )

    with pytest.raises(SystemExit, match="Refusing to create"):
        main()

    assert not database.exists()
