import ssl
import smtplib
import logging
from email.message import EmailMessage
from email.utils import formatdate
import os
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from app import db
from flask_wtf.csrf import generate_csrf, validate_csrf, ValidationError
from app.models import FeedbackTicket, FeedbackMessage

def notify_support_admin(ticket, message_text, user_email):
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "465"))
    username = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    recipient = os.getenv("SUPPORT_EMAIL_TO", "")
    if not all((host, username, password, recipient)):
        logging.error("Support email notification skipped: SMTP settings are incomplete")
        return
    email = EmailMessage()
    email["Subject"] = f"Новое обращение в поддержку #{ticket.id}: {ticket.subject}"
    email["From"] = os.getenv("SMTP_FROM", username)
    email["To"] = recipient
    email["Date"] = formatdate(localtime=True)
    email.set_content(f"Новое обращение #{ticket.id}\nТема: {ticket.subject}\nКатегория: {ticket.category}\nОт: {user_email}\n\n{message_text}")
    try:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15) as server:
            server.login(username, password)
            server.send_message(email)
    except Exception:
        logging.exception("Failed to send support ticket notification")

support_bp = Blueprint("support", __name__, url_prefix="/support")

@support_bp.context_processor
def inject_support_csrf():
    return {"csrf_token": generate_csrf}



def is_admin():
    admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    return bool(admin_email) and current_user.email.strip().lower() == admin_email


def check_support_csrf():
    try:
        validate_csrf(request.form.get("csrf_token"))
    except ValidationError:
        abort(400, description="Недействительный CSRF-токен")


@support_bp.route("/")
@login_required
def index():
    query = FeedbackTicket.query
    if not is_admin():
        query = query.filter_by(user_id=current_user.id)
    tickets = query.order_by(FeedbackTicket.updated_at.desc()).all()
    return render_template("support.html", tickets=tickets, is_admin=is_admin())


@support_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_ticket():
    if request.method == "POST":
        check_support_csrf()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        category = request.form.get("category", "Вопрос").strip()
        if not subject or len(subject) > 200 or not message or len(message) > 10000:
            flash("Укажите тему до 200 символов и сообщение до 10000 символов.", "danger")
            return render_template("support_new.html")
        ticket = FeedbackTicket(
            user_id=current_user.id,
            subject=subject,
            category=category if category in ("Вопрос", "Ошибка", "Предложение") else "Вопрос",
            status="open"
        )
        db.session.add(ticket)
        db.session.flush()
        db.session.add(FeedbackMessage(ticket_id=ticket.id, sender_id=current_user.id, message=message))
        db.session.commit()
        notify_support_admin(ticket, message, current_user.email)
        flash("Обращение создано.", "success")
        return redirect(url_for("support.detail", ticket_id=ticket.id))
    return render_template("support_new.html")


@support_bp.route("/<int:ticket_id>", methods=["GET", "POST"])
@login_required
def detail(ticket_id):
    ticket = FeedbackTicket.query.get_or_404(ticket_id)
    admin = is_admin()
    if ticket.user_id != current_user.id and not admin:
        abort(403)
    if request.method == "POST":
        check_support_csrf()
        message = request.form.get("message", "").strip()
        if not message or len(message) > 10000:
            flash("Сообщение не должно быть пустым или длиннее 10000 символов.", "danger")
        else:
            db.session.add(FeedbackMessage(ticket_id=ticket.id, sender_id=current_user.id, message=message))
            if admin and request.form.get("status") in ("open", "closed"):
                ticket.status = request.form["status"]
            elif not admin:
                ticket.status = "open"
            db.session.commit()
            flash("Ответ отправлен.", "success")
            return redirect(url_for("support.detail", ticket_id=ticket.id))
    return render_template("support_detail.html", ticket=ticket, is_admin=admin)
