from sqlalchemy import inspect, text
from app import create_app, db
from app.models import AdminAuditLog, AppErrorLog

app = create_app()
with app.app_context():
    inspector = inspect(db.engine)
    columns = {column['name'] for column in inspector.get_columns('user')}
    with db.engine.begin() as connection:
        if 'is_blocked' not in columns:
            connection.execute(text('ALTER TABLE user ADD COLUMN is_blocked BOOLEAN NOT NULL DEFAULT 0'))
        if 'blocked_until' not in columns:
            connection.execute(text('ALTER TABLE user ADD COLUMN blocked_until DATETIME'))
        if 'blocked_reason' not in columns:
            connection.execute(text('ALTER TABLE user ADD COLUMN blocked_reason VARCHAR(300)'))
    db.create_all()
    print('Admin panel schema migration complete.')
