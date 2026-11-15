import sqlite3
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "add_default_test_data_selection.py"


def _database(path):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE test_data_set (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    connection.execute("CREATE TABLE test_data_row (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    connection.commit()
    connection.close()


def test_default_selection_migration_adds_columns_and_is_idempotent(tmp_path):
    database = tmp_path / "test_runner.db"
    _database(database)

    first = subprocess.run(
        [sys.executable, str(SCRIPT), "--database", str(database)],
        capture_output=True, text=True, check=False,
    )
    assert first.returncode == 0, first.stderr
    assert "Added test_data_set.is_default" in first.stdout
    assert "Added test_data_row.is_default" in first.stdout
    assert "Integrity: ok" in first.stdout

    second = subprocess.run(
        [sys.executable, str(SCRIPT), "--database", str(database)],
        capture_output=True, text=True, check=False,
    )
    assert second.returncode == 0, second.stderr
    assert "already exists" in second.stdout

    connection = sqlite3.connect(database)
    try:
        for table in ("test_data_set", "test_data_row"):
            columns = {row[1]: row for row in connection.execute(f'PRAGMA table_info("{table}")')}
            assert columns["is_default"][3] == 1
            assert columns["is_default"][4] == "0"
    finally:
        connection.close()


def test_default_selection_migration_refuses_to_create_missing_database(tmp_path):
    missing = tmp_path / "missing.db"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--database", str(missing)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert not missing.exists()
    assert "Refusing to create it" in result.stderr
