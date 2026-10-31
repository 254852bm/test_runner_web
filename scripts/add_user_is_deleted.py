"""Safely add user.is_deleted to an existing SQLite database.

Run explicitly, for example:
    python scripts/add_user_is_deleted.py --database /root/pr14-test/instance/test_runner.db

The script never creates a database and never calls db.create_all().
"""
import argparse
from pathlib import Path

from sqlalchemy.engine import URL

from app import create_app, db


def parse_args():
    parser = argparse.ArgumentParser(
        description="Add the user.is_deleted column to an existing SQLite database."
    )
    parser.add_argument(
        "--database",
        required=True,
        help="Path to an existing SQLite database file. No database is created.",
    )
    return parser.parse_args()


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
            drivername="sqlite",
            database=str(database_path),
        ),
        "SKIP_DB_CREATE_ALL": True,
    })

    with app.app_context():
        with db.engine.begin() as connection:
            rows = connection.execute(db.text("PRAGMA table_info(user)")).all()
            if not rows:
                raise SystemExit(
                    f"Table 'user' was not found in {database_path}. "
                    "No changes were made."
                )

            columns = {row[1] for row in rows}
            if "is_deleted" in columns:
                print(f"user.is_deleted already exists in {database_path}; nothing to do.")
                return

            connection.execute(db.text(
                "ALTER TABLE user ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"
            ))

        print(f"Added user.is_deleted to {database_path}.")


if __name__ == "__main__":
    main()
