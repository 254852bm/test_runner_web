import os
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash
from flask_login import current_user, login_required
from flask_wtf.csrf import generate_csrf, validate_csrf, ValidationError
from sqlalchemy import or_

from app import db
from app.models import User, FeedbackTicket, AdminAuditLog, AppErrorLog, ApiToken

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.context_processor
def inject_admin_csrf():
    return {"csrf_token": generate_csrf}


def _require_admin():
    expected = os.getenv("ADMIN_EMAIL", "").strip().lower()
    if not expected or not current_user.is_authenticated or current_user.email.strip().lower() != expected:
        abort(403)


def _check_csrf():
    try:
        validate_csrf(request.form.get("csrf_token"))
    except ValidationError:
        abort(400, description="Недействительный CSRF-токен")


def _redirect_to_users():
    status = request.form.get("status", "active")
    if status not in ("active", "deleted", "all"):
        status = "active"
    return redirect(url_for("admin.users", q=request.form.get("q", ""), status=status))


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
        blocked_count=User.query.filter(
            User.is_blocked.is_(True),
            or_(User.blocked_until.is_(None), User.blocked_until > datetime.utcnow()),
        ).count(),
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
    status = request.args.get("status", "active")
    if status not in ("active", "deleted", "all"):
        status = "active"
    query = User.query
    if status == "active":
        query = query.filter(User.is_deleted.is_(False))
    elif status == "deleted":
        query = query.filter(User.is_deleted.is_(True))
    if search:
        pattern = f"%{search}%"
        filters = [User.email.ilike(pattern), User.company_name.ilike(pattern)]
        if search.isdigit():
            filters.append(User.id == int(search))
        query = query.filter(or_(*filters))
    pagination = query.order_by(User.created_at.desc(), User.id.desc()).paginate(page=page, per_page=50, error_out=False)
    return render_template("admin/users.html", pagination=pagination, search=search, status=status)


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
        return _redirect_to_users()
    user.is_blocked = True
    user.blocked_until = datetime.utcnow() + timedelta(days=days)
    user.blocked_reason = reason
    _audit("user_blocked", user, reason, f"duration_days={days}")
    db.session.commit()
    flash(f"Пользователь {user.email} заблокирован на {days} дн.", "success")
    return _redirect_to_users()


@admin_bp.route("/users/<int:user_id>/unblock", methods=["POST"])
@login_required
def unblock_user(user_id):
    _require_admin()
    _check_csrf()
    user = User.query.get_or_404(user_id)
    if not user.is_blocked:
        flash("Аккаунт уже не заблокирован.", "info")
        return _redirect_to_users()
    old_reason = user.blocked_reason
    user.is_blocked = False
    user.blocked_until = None
    user.blocked_reason = None
    _audit("user_unblocked", user, old_reason, "manual unblock")
    db.session.commit()
    flash(f"Пользователь {user.email} разблокирован.", "success")
    return _redirect_to_users()


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
    records = AppErrorLog.query.order_by(AppErrorLog.created_at.desc()).limit(100).all()
    return render_template("admin/logs.html", records=records)


@admin_bp.route("/users/<int:user_id>/password", methods=["POST"])
@login_required
def reset_user_password(user_id):
    _require_admin()
    _check_csrf()
    user = User.query.get_or_404(user_id)
    password = request.form.get("new_password", "")
    confirmation = request.form.get("confirm_password", "")
    if len(password) < 8 or password != confirmation:
        flash("Пароль должен содержать не менее 8 символов, а поля должны совпадать.", "danger")
    else:
        user.password = generate_password_hash(password)
        _audit("user_password_reset", user, details="admin password reset")
        db.session.commit()
        flash("Пароль пользователя изменён.", "success")
    return _redirect_to_users()


@admin_bp.route("/users/<int:user_id>/soft-delete", methods=["POST"])
@login_required
def soft_delete_user(user_id):
    _require_admin()
    _check_csrf()
    user = User.query.get_or_404(user_id)
    admin_email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    if user.id == current_user.id or user.email.strip().lower() == admin_email:
        abort(400, description="Нельзя удалить аккаунт администратора.")
    if not user.is_deleted:
        user.is_deleted = True
        ApiToken.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        _audit("user_soft_deleted", user, details="soft delete; API tokens revoked")
        db.session.commit()
        flash(f"Аккаунт {user.email} удалён. История сохранена.", "success")
    return redirect(url_for("admin.users", q=request.form.get("q", ""), status="active"))


@admin_bp.route("/users/<int:user_id>/restore", methods=["POST"])
@login_required
def restore_user(user_id):
    _require_admin()
    _check_csrf()
    user = User.query.get_or_404(user_id)
    if user.is_deleted:
        user.is_deleted = False
        _audit("user_restored", user, details="soft-deleted account restored")
        db.session.commit()
        flash(f"Аккаунт {user.email} восстановлен.", "success")
    return redirect(url_for("admin.users", q=request.form.get("q", ""), status="deleted"))
