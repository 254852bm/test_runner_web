"""Add optional default-selection flags to test data tables.

Run against a backed-up TEST database before starting the updated application:
    python scripts/add_default_test_data_selection.py --database /path/to/test_runner.db
"""
import argparse
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    database = Path(parser.parse_args().database).expanduser().resolve()
    if not database.is_file():
        raise SystemExit(f"Database file does not exist: {database}. Refusing to create it.")

    connection = sqlite3.connect(str(database))
    try:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {"test_data_set", "test_data_row"}
        if not required.issubset(tables):
            missing = ", ".join(sorted(required - tables))
            raise SystemExit(f"Required tables are missing: {missing}. No changes made.")

        changes = (
            ("test_data_set", "is_default"),
            ("test_data_row", "is_default"),
        )
        for table, column in changes:
            existing = {
                row[1] for row in connection.execute(
                    f'PRAGMA table_info("{table}")'
                )
            }
            if column not in existing:
                connection.execute(
                    f'ALTER TABLE "{table}" ADD COLUMN "{column}" BOOLEAN NOT NULL DEFAULT 0'
                )
                print(f"Added {table}.{column}")
            else:
                print(f"{table}.{column} already exists")

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            connection.rollback()
            raise SystemExit(f"Database integrity check failed: {integrity}")
        connection.commit()
        print(f"Default data-set selection is ready in {database}")
        print(f"Integrity: {integrity}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
