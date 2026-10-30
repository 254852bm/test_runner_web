"""Idempotent SQLite migration adding user.is_deleted."""
from app import create_app, db

app = create_app()
with app.app_context():
    rows = db.session.execute(db.text("PRAGMA table_info(user)")).all()
    columns = {row[1] for row in rows}
    if "is_deleted" not in columns:
        db.session.execute(db.text(
            "ALTER TABLE user ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"
        ))
        db.session.commit()
        print("Added user.is_deleted.")
    else:
        print("user.is_deleted already exists; nothing to do.")
