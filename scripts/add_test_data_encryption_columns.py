"""Prepare test-data feature tables and encrypted payload columns in SQLite.

Example (run only against a backed-up TEST database first):
    python scripts/add_test_data_encryption_columns.py --database /path/to/test_runner.db

The script never creates a database. It creates only the new test-data feature tables
when they are missing, then adds the required columns to existing tables.
"""
import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.engine import URL

from app import create_app, db
from app.models import (
    TestDataSet, TestDataColumn, TestDataRow, TestRunDataSnapshot, TestDataBatch,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Prepare test-data tables, encrypted payload columns, and token permissions."
    )
    parser.add_argument(
        "--database", required=True,
        help="Path to an existing SQLite database file. No database is created.",
    )
    return parser.parse_args()


def add_column(connection, table, column, sql_type):
    rows = connection.execute(db.text(f"PRAGMA table_info({table})")).all()
    if not rows:
        raise SystemExit(f"Table '{table}' was not found. No changes were made.")
    columns = {row[1] for row in rows}
    if column in columns:
        print(f"{table}.{column} already exists; nothing to do.")
        return
    connection.execute(db.text(
        f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
    ))
    print(f"Added {table}.{column}.")


def main():
    args = parse_args()
    database_path = Path(args.database).expanduser().resolve()
    if not database_path.is_file():
        raise SystemExit(
            f"Database file does not exist: {database_path}. "
            "Refusing to create a new database."
        )

    app = create_app({
        "SQLALCHEMY_DATABASE_URI": URL.create(
            drivername="sqlite", database=str(database_path)
        ),
        "SKIP_DB_CREATE_ALL": True,
    })
    with app.app_context():
        # Refuse an unrelated or empty SQLite file before making any changes.
        with db.engine.connect() as connection:
            existing_tables = set(connection.execute(db.text(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )).scalars().all())
        required_base_tables = {"user", "test_case", "test_run", "api_token"}
        missing_base_tables = required_base_tables - existing_tables
        if missing_base_tables:
            names = ", ".join(sorted(missing_base_tables))
            raise SystemExit(
                f"Required application tables are missing: {names}. No changes were made."
            )

        # Create only these feature tables if they do not yet exist. This is
        # targeted and does not attempt to alter or create unrelated app tables.
        db.create_all(tables=[
            TestDataSet.__table__,
            TestDataColumn.__table__,
            TestDataRow.__table__,
            TestRunDataSnapshot.__table__,
            TestDataBatch.__table__,
        ])

        with db.engine.begin() as connection:
            add_column(connection, "test_data_row", "encrypted_values_json", "TEXT")
            add_column(
                connection, "test_run_data_snapshot",
                "encrypted_values_snapshot", "TEXT"
            )
            add_column(
                connection, "api_token", "allow_secret_data",
                "BOOLEAN NOT NULL DEFAULT 0"
            )
        print(f"Test-data tables and encryption columns are ready in {database_path}.")


if __name__ == "__main__":
    main()
