from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv
import os
import logging

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///../instance/test_runner.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    if not os.getenv('SECRET_KEY') or os.getenv('SECRET_KEY') == 'dev-key':
        app.logger.warning('SECRET_KEY is missing or using the development fallback')
    os.makedirs(app.instance_path, exist_ok=True)
    from logging.handlers import RotatingFileHandler
    error_log_path = os.path.join(app.instance_path, 'admin-errors.log')
    if not any(getattr(handler, 'baseFilename', None) == error_log_path for handler in app.logger.handlers):
        handler = RotatingFileHandler(error_log_path, maxBytes=1_000_000, backupCount=3, encoding='utf-8')
        handler.setLevel(logging.ERROR)
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Пожалуйста, войдите для доступа.'

    from .auth import auth_bp
    from .routes import main_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    from .support_bot import support_bp
    app.register_blueprint(support_bp)
    from .support_routes import support_bp as user_support_bp
    app.register_blueprint(user_support_bp)
    from .api import api_bp
    app.register_blueprint(api_bp)
    from .admin_routes import admin_bp
    app.register_blueprint(admin_bp)

    @app.context_processor
    def inject_admin_context():
        from flask_login import current_user
        expected = os.getenv('ADMIN_EMAIL', '').strip().lower()
        return {
            'admin_email': expected,
            'is_site_admin': bool(expected and current_user.is_authenticated and current_user.email.strip().lower() == expected),
        }

    from flask_login import current_user, logout_user
    from flask import flash, redirect, url_for

    @app.before_request
    def reject_blocked_sessions():
        if current_user.is_authenticated and getattr(current_user, 'is_blocked_now', False):
            logout_user()
            flash('Доступ к аккаунту временно ограничен.', 'danger')
            return redirect(url_for('auth.login'))

    @app.errorhandler(Exception)
    def log_unhandled_error(error):
        from werkzeug.exceptions import HTTPException
        if isinstance(error, HTTPException):
            return error
        app.logger.exception('Unhandled application error at endpoint %s', request.endpoint or 'unknown')
        try:
            from .models import AppErrorLog
            user_id = current_user.id if current_user.is_authenticated else None
            db.session.add(AppErrorLog(endpoint=(request.endpoint or '')[:200], method=request.method[:10], error_type=type(error).__name__[:120], user_id=user_id))
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception('Could not persist application error record')
        return 'Внутренняя ошибка сервера. Попробуйте позже.', 500

    if os.getenv('SKIP_DB_CREATE_ALL') != '1':
        with app.app_context():
            db.create_all()

    return app
