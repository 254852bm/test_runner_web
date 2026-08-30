from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required
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
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Вы вошли!', 'success')
            return redirect(url_for('main.index'))
        else:
            flash('Неверный email или пароль', 'danger')
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