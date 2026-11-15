"""Create the isolated AI credential table in an existing SQLite database.

Run only against a backed-up TEST database first:
    python scripts/add_ai_credential_table.py --database /path/to/test_runner.db

This script never creates a database and creates only the AI credential, generation-attempt, and draft-save idempotency tables.
"""
import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.engine import URL
from app import create_app, db
from app.models import AICredential, AIGenerationAttempt, AIDraftSave


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    path = Path(parser.parse_args().database).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"Database file does not exist: {path}. Refusing to create it.")

    app = create_app({
        "SQLALCHEMY_DATABASE_URI": URL.create("sqlite", database=str(path)),
        "SKIP_DB_CREATE_ALL": True,
    })
    with app.app_context():
        with db.engine.connect() as connection:
            tables = set(connection.execute(db.text(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )).scalars().all())
        if "user" not in tables:
            raise SystemExit("Required user table is missing; no changes made.")
        db.metadata.create_all(bind=db.engine, tables=[AICredential.__table__, AIGenerationAttempt.__table__, AIDraftSave.__table__])
        print(f"AI credential, generation-attempt, and draft-save tables are ready in {path}")


if __name__ == "__main__":
    main()
