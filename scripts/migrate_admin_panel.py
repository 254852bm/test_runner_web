import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Prevent the app factory from implicitly changing schema before this migration
# has inspected and backed up the existing database.
os.environ["SKIP_DB_CREATE_ALL"] = "1"

from sqlalchemy import inspect, text
from app import create_app, db


app = create_app()
with app.app_context():
    database_name = db.engine.url.database
    if not database_name or database_name == ":memory:":
        raise RuntimeError("Expected an on-disk SQLite database; refusing to migrate.")

    database_path = Path(database_name)
    if not database_path.is_absolute():
        # Flask-SQLAlchemy resolves relative SQLite paths from app.instance_path.
        database_path = (Path(app.instance_path) / database_path).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(
            f"Database file was not found at {database_path}; refusing to create or migrate a new database."
        )

    inspector = inspect(db.engine)
    if "user" not in inspector.get_table_names():
        raise RuntimeError("The existing database has no user table; refusing to migrate.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = database_path.with_name(f"{database_path.name}.before_admin_{timestamp}.bak")
    with sqlite3.connect(str(database_path)) as source, sqlite3.connect(str(backup_path)) as backup:
        source.backup(backup)
    if backup_path.stat().st_size == 0:
        raise RuntimeError("Database backup is empty; refusing to migrate.")
    with sqlite3.connect(str(backup_path)) as backup_check:
        integrity = backup_check.execute("PRAGMA integrity_check").fetchone()
    if not integrity or integrity[0] != "ok":
        raise RuntimeError(f"Database backup failed integrity_check: {integrity!r}")

    columns = {column["name"] for column in inspector.get_columns("user")}
    with db.engine.begin() as connection:
        if "is_blocked" not in columns:
            connection.execute(text("ALTER TABLE user ADD COLUMN is_blocked BOOLEAN NOT NULL DEFAULT 0"))
        if "blocked_until" not in columns:
            connection.execute(text("ALTER TABLE user ADD COLUMN blocked_until DATETIME"))
        if "blocked_reason" not in columns:
            connection.execute(text("ALTER TABLE user ADD COLUMN blocked_reason VARCHAR(300)"))

    # Create only the new audit/error tables; do not invoke create_all here.
    from app.models import AdminAuditLog, AppErrorLog
    AdminAuditLog.__table__.create(bind=db.engine, checkfirst=True)
    AppErrorLog.__table__.create(bind=db.engine, checkfirst=True)
    print(f"Admin panel migration complete. Backup: {backup_path}")
