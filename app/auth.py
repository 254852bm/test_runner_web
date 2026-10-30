from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_wtf.csrf import generate_csrf, validate_csrf, ValidationError
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from app.models import User

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user and not user.is_deleted and check_password_hash(user.password, password) and not user.is_blocked_now:
            login_user(user)
            flash('Вы вошли!', 'success')
            return redirect(url_for('main.index'))
        else:
            flash('Неверный email или пароль либо аккаунт временно заблокирован.', 'danger')
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        company = request.form.get('company')
        if User.query.filter_by(email=email).first():
            flash('Такой email уже зарегистрирован', 'danger')
            return redirect(url_for('auth.register'))
        hashed = generate_password_hash(password)
        user = User(email=email, password=hashed, company_name=company)
        db.session.add(user)
        db.session.commit()
        flash('Регистрация успешна! Войдите.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('register.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.context_processor
def inject_auth_csrf():
    return {'csrf_token': generate_csrf}


@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    try:
        validate_csrf(request.form.get('csrf_token'))
    except ValidationError:
        abort(400, description='Недействительный CSRF-токен')

    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not check_password_hash(current_user.password, current_password):
        flash('Текущий пароль указан неверно.', 'danger')
    elif len(new_password) < 8:
        flash('Новый пароль должен содержать не менее 8 символов.', 'danger')
    elif new_password != confirm_password:
        flash('Новые пароли не совпадают.', 'danger')
    elif check_password_hash(current_user.password, new_password):
        flash('Новый пароль должен отличаться от текущего.', 'danger')
    else:
        current_user.password = generate_password_hash(new_password)
        db.session.commit()
        flash('Пароль успешно изменён.', 'success')
    return redirect(url_for('main.profile'))
