import os
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import validate_csrf, ValidationError
from sqlalchemy import or_

from app import db
from app.models import User, FeedbackTicket, AdminAuditLog, AppErrorLog

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _require_admin():
    expected = os.getenv("ADMIN_EMAIL", "").strip().lower()
    if not expected or not current_user.is_authenticated or current_user.email.strip().lower() != expected:
        abort(403)


def _check_csrf():
    try:
        validate_csrf(request.form.get("csrf_token"))
    except ValidationError:
        abort(400, description="Недействительный CSRF-токен")


def _audit(action, target_user=None, reason=None, details=None):
    db.session.add(AdminAuditLog(
        actor_user_id=current_user.id,
        target_user_id=target_user.id if target_user else None,
        action=action,
        reason=(reason or "")[:300] or None,
        details=(details or "")[:500] or None,
    ))


@admin_bp.route("/")
@login_required
def index():
    _require_admin()
    return render_template(
        "admin/index.html",
        user_count=User.query.count(),
        blocked_count=User.query.filter_by(is_blocked=True).count(),
        open_tickets=FeedbackTicket.query.filter_by(status="open").count(),
        recent_errors=AppErrorLog.query.order_by(AppErrorLog.created_at.desc()).limit(5).all(),
        recent_audit=AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc()).limit(8).all(),
    )


@admin_bp.route("/users")
@login_required
def users():
    _require_admin()
    search = request.args.get("q", "").strip()[:100]
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    query = User.query
    if search:
        pattern = f"%{search}%"
        filters = [User.email.ilike(pattern), User.company_name.ilike(pattern)]
        if search.isdigit():
            filters.append(User.id == int(search))
        query = query.filter(or_(*filters))
    pagination = query.order_by(User.created_at.desc(), User.id.desc()).paginate(page=page, per_page=50, error_out=False)
    return render_template("admin/users.html", pagination=pagination, search=search)


@admin_bp.route("/users/<int:user_id>/block", methods=["POST"])
@login_required
def block_user(user_id):
    _require_admin()
    _check_csrf()
    user = User.query.get_or_404(user_id)
    admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    if user.id == current_user.id or user.email.strip().lower() == admin_email:
        abort(400, description="Нельзя блокировать аккаунт администратора.")
    reason = request.form.get("reason", "").strip()
    days = request.form.get("days", type=int)
    if not reason or len(reason) > 300 or days not in range(1, 31):
        flash("Укажите причину и срок блокировки от 1 до 30 дней.", "danger")
        return redirect(url_for("admin.users", q=request.form.get("q", "")))
    user.is_blocked = True
    user.blocked_until = datetime.utcnow() + timedelta(days=days)
    user.blocked_reason = reason
    _audit("user_blocked", user, reason, f"duration_days={days}")
    db.session.commit()
    flash(f"Пользователь {user.email} заблокирован на {days} дн.", "success")
    return redirect(url_for("admin.users", q=request.form.get("q", "")))


@admin_bp.route("/users/<int:user_id>/unblock", methods=["POST"])
@login_required
def unblock_user(user_id):
    _require_admin()
    _check_csrf()
    user = User.query.get_or_404(user_id)
    if not user.is_blocked:
        flash("Аккаунт уже не заблокирован.", "info")
        return redirect(url_for("admin.users", q=request.form.get("q", "")))
    old_reason = user.blocked_reason
    user.is_blocked = False
    user.blocked_until = None
    user.blocked_reason = None
    _audit("user_unblocked", user, old_reason, "manual unblock")
    db.session.commit()
    flash(f"Пользователь {user.email} разблокирован.", "success")
    return redirect(url_for("admin.users", q=request.form.get("q", "")))


@admin_bp.route("/support")
@login_required
def support():
    _require_admin()
    status = request.args.get("status", "open")
    if status not in ("open", "closed", "all"):
        status = "open"
    query = FeedbackTicket.query
    if status != "all":
        query = query.filter_by(status=status)
    tickets = query.order_by(FeedbackTicket.updated_at.desc()).limit(200).all()
    return render_template("admin/support.html", tickets=tickets, status=status)


@admin_bp.route("/errors")
@login_required
def errors():
    _require_admin()
    records = AppErrorLog.query.order_by(AppErrorLog.created_at.desc()).limit(200).all()
    return render_template("admin/errors.html", records=records)


@admin_bp.route("/audit")
@login_required
def audit():
    _require_admin()
    records = AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc()).limit(200).all()
    return render_template("admin/audit.html", records=records)


@admin_bp.route("/logs")
@login_required
def logs():
    _require_admin()
    path = Path(current_app.instance_path) / "admin-errors.log"
    lines = []
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-100:]
        except OSError:
            current_app.logger.exception("Could not read admin error log")
    return render_template("admin/logs.html", lines=lines)
