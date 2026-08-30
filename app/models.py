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

    projects = db.relationship('Project', backref='owner', lazy=True)

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

class TestRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), nullable=False)
    comment = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    test_case_id = db.Column(db.Integer, db.ForeignKey('test_case.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Добавляем связи (relationships)
    test_case = db.relationship('TestCase', backref='runs')
    user = db.relationship('User', backref='runs')

# ===== ЭТО ВАЖНО: ЗАГРУЗЧИК ПОЛЬЗОВАТЕЛЯ ДЛЯ FLASK-LOGIN =====
from app import login_manager

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
