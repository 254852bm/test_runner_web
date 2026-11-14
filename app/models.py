from app import db
from flask_login import UserMixin
from datetime import datetime


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    company_name = db.Column(db.String(100))
    tariff = db.Column(db.String(20), default='free')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_blocked = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    blocked_until = db.Column(db.DateTime, nullable=True)
    blocked_reason = db.Column(db.String(300), nullable=True)

    @property
    def is_blocked_now(self):
        return bool(self.is_blocked and (self.blocked_until is None or self.blocked_until > datetime.utcnow()))

    projects = db.relationship('Project', backref='owner', lazy=True)
    ai_credential = db.relationship(
        'AICredential', back_populates='user', uselist=False,
        cascade='all, delete-orphan'
    )


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    test_cases = db.relationship('TestCase', backref='project', lazy=True)


class TestCase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    precondition = db.Column(db.Text)
    steps = db.Column(db.Text, nullable=False)
    expected_result = db.Column(db.Text)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)

    step_items = db.relationship(
        'TestStep',
        backref='test_case',
        lazy=True,
        order_by='TestStep.position',
        cascade='all, delete-orphan'
    )

    versions = db.relationship(
        'TestCaseVersion',
        backref='test_case',
        lazy=True,
        order_by='TestCaseVersion.version_number',
        cascade='all, delete-orphan'
    )

    data_sets = db.relationship(
        'TestDataSet', backref='test_case', lazy=True,
        cascade='all, delete-orphan'
    )
    data_batches = db.relationship(
        'TestDataBatch', backref='test_case', lazy=True,
        cascade='all, delete-orphan'
    )


class TestCaseVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    test_case_id = db.Column(db.Integer, db.ForeignKey('test_case.id'), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    precondition = db.Column(db.Text)
    steps = db.Column(db.Text, nullable=False)
    expected_result = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='test_case_versions')


class TestStep(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    test_case_id = db.Column(db.Integer, db.ForeignKey('test_case.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    action = db.Column(db.Text, nullable=False)
    expected_result = db.Column(db.Text)
    screenshots = db.relationship('TestStepScreenshot', backref='test_step', lazy=True,
                                 cascade='all, delete-orphan', order_by='TestStepScreenshot.created_at')


class TestStepScreenshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    test_step_id = db.Column(db.Integer, db.ForeignKey('test_step.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    stored_name = db.Column(db.String(100), unique=True, nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(30), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship('User', backref='test_step_screenshots')


class TestRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), nullable=False)
    comment = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    test_case_id = db.Column(db.Integer, db.ForeignKey('test_case.id'), nullable=False)
    version_id = db.Column(db.Integer, db.ForeignKey('test_case_version.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    source = db.Column(db.String(20), default='manual')  # 'manual' или 'auto'
    duration_ms = db.Column(db.Integer)                  # время выполнения, мс

    test_case = db.relationship('TestCase', backref='runs')
    version = db.relationship('TestCaseVersion', backref='runs')
    user = db.relationship('User', backref='runs')

    step_runs = db.relationship(
        'StepRun',
        backref='test_run',
        lazy=True,
        cascade='all, delete-orphan'
    )


class StepRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    test_run_id = db.Column(db.Integer, db.ForeignKey('test_run.id'), nullable=False)
    test_step_id = db.Column(db.Integer, db.ForeignKey('test_step.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    comment = db.Column(db.Text)
    step_text = db.Column(db.Text, nullable=False)
    expected_result = db.Column(db.Text)
    actual_result = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    test_step = db.relationship('TestStep', backref='runs')
    screenshots = db.relationship(
        'StepRunScreenshot', backref='step_run', lazy=True,
        cascade='all, delete-orphan', order_by='StepRunScreenshot.created_at'
    )


class StepRunScreenshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    step_run_id = db.Column(db.Integer, db.ForeignKey('step_run.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    stored_name = db.Column(db.String(100), unique=True, nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(30), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user = db.relationship('User', backref='step_run_screenshots')


class ApiToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime)
    # Explicit per-token permission; legacy tokens remain unable to retrieve secrets.
    allow_secret_data = db.Column(
        db.Boolean, nullable=False, default=False, server_default='0'
    )

    user = db.relationship('User', backref='api_tokens')

from app import login_manager


@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(int(user_id))
    return user if user and not user.is_deleted else None


class FeedbackTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), default='Вопрос', nullable=False)
    status = db.Column(db.String(20), default='open', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref='feedback_tickets')
    messages = db.relationship(
        'FeedbackMessage',
        backref='ticket',
        lazy=True,
        order_by='FeedbackMessage.created_at',
        cascade='all, delete-orphan'
    )


class FeedbackMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('feedback_ticket.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    sender = db.relationship('User', backref='feedback_messages')


class AdminAuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(80), nullable=False)
    reason = db.Column(db.String(300), nullable=True)
    details = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    actor = db.relationship('User', foreign_keys=[actor_user_id])
    target_user = db.relationship('User', foreign_keys=[target_user_id])


class AppErrorLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    endpoint = db.Column(db.String(200), nullable=True)
    method = db.Column(db.String(10), nullable=True)
    error_type = db.Column(db.String(120), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user = db.relationship('User', foreign_keys=[user_id])


class TestDataSet(db.Model):
    """A named collection of parameter rows belonging to one test case."""
    id = db.Column(db.Integer, primary_key=True)
    test_case_id = db.Column(
        db.Integer, db.ForeignKey('test_case.id'), nullable=False, index=True
    )
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    columns = db.relationship(
        'TestDataColumn', backref='dataset', lazy=True,
        cascade='all, delete-orphan', order_by='TestDataColumn.position'
    )
    rows = db.relationship(
        'TestDataRow', backref='dataset', lazy=True,
        cascade='all, delete-orphan', order_by='TestDataRow.position'
    )
    run_snapshots = db.relationship(
        'TestRunDataSnapshot', backref='dataset', lazy=True
    )
    batches = db.relationship(
        'TestDataBatch', backref='dataset', lazy=True,
        cascade='all, delete-orphan'
    )


class TestDataColumn(db.Model):
    """A named variable definition in a test data set."""
    id = db.Column(db.Integer, primary_key=True)
    dataset_id = db.Column(
        db.Integer, db.ForeignKey('test_data_set.id'), nullable=False, index=True
    )
    key = db.Column(db.String(64), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    is_secret = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    position = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint('dataset_id', 'key', name='uq_test_data_column_dataset_key'),
    )


class TestDataRow(db.Model):
    """One row of values; values are JSON keyed by TestDataColumn.key.

    Secret-column encryption must be implemented before secret values are accepted
    through any UI or API. The model alone does not provide encryption.
    """
    id = db.Column(db.Integer, primary_key=True)
    dataset_id = db.Column(
        db.Integer, db.ForeignKey('test_data_set.id'), nullable=False, index=True
    )
    name = db.Column(db.String(120), nullable=False)
    # Ordinary values stay in JSON. Secret values must be stored only in this
    # authenticated-encryption payload; never put plaintext secrets in values_json.
    values_json = db.Column(db.JSON, nullable=False, default=dict)
    encrypted_values_json = db.Column(db.Text, nullable=True)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    run_snapshots = db.relationship(
        'TestRunDataSnapshot', backref='data_row', lazy=True
    )


class TestRunDataSnapshot(db.Model):
    """Immutable, non-secret data snapshot attached to one historical run.

    This separate table avoids altering the existing test_run table, so existing
    production databases can gain the feature additively via create_all().
    """
    id = db.Column(db.Integer, primary_key=True)
    test_run_id = db.Column(
        db.Integer, db.ForeignKey('test_run.id'), nullable=False, unique=True, index=True
    )
    dataset_id = db.Column(
        db.Integer, db.ForeignKey('test_data_set.id', ondelete='SET NULL'), nullable=True
    )
    data_row_id = db.Column(
        db.Integer, db.ForeignKey('test_data_row.id', ondelete='SET NULL'), nullable=True
    )
    dataset_name_snapshot = db.Column(db.String(120), nullable=False)
    row_name_snapshot = db.Column(db.String(120), nullable=False)
    values_snapshot_json = db.Column(db.JSON, nullable=False, default=dict)
    # Secret snapshot is encrypted independently so history remains immutable
    # without exposing credentials in ordinary JSON columns.
    encrypted_values_snapshot = db.Column(db.Text, nullable=True)
    snapshot_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    test_run = db.relationship('TestRun', backref=db.backref(
        'data_snapshot', uselist=False, cascade='all, delete-orphan'
    ))




class TestDataBatch(db.Model):
    """Server-side progress for a sequential run over a fixed list of rows."""
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    test_case_id = db.Column(
        db.Integer, db.ForeignKey('test_case.id'), nullable=False, index=True
    )
    dataset_id = db.Column(
        db.Integer, db.ForeignKey('test_data_set.id'), nullable=False, index=True
    )
    row_ids_json = db.Column(db.JSON, nullable=False, default=list)
    next_index = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', backref='test_data_batches')



class AIGenerationAttempt(db.Model):
    """Metadata-only record used for per-user generation rate limiting."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)



class AIDraftSave(db.Model):
    """Idempotency record preventing the same reviewed AI draft being saved twice."""
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    project_id = db.Column(db.Integer, nullable=False, index=True)
    test_case_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class AICredential(db.Model):
    """One encrypted, user-owned BYOK credential; plaintext is never persisted."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True, index=True
    )
    provider = db.Column(db.String(40), nullable=False)
    encrypted_payload = db.Column(db.Text, nullable=False)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    consent_version = db.Column(db.String(40), nullable=False)
    consented_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user = db.relationship('User', back_populates='ai_credential')
