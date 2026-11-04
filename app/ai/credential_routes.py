"""User-owned BYOK credential settings. Saving a key never calls the provider."""
from datetime import datetime

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError, validate_csrf

from app import db
from app.ai_credentials import encrypt_ai_credential
from app.models import AICredential


ai_credentials_bp = Blueprint("ai_credentials", __name__)
CONSENT_VERSION = "BYOK-CONSENT-v1"


def _check_csrf():
    try:
        validate_csrf(request.form.get("csrf_token"))
    except ValidationError:
        abort(400, description="Недействительный CSRF-токен")


@ai_credentials_bp.route("/settings/ai-credentials", methods=["GET", "POST"])
@login_required
def settings():
    credential = AICredential.query.filter_by(user_id=current_user.id).first()
    if request.method == "POST":
        _check_csrf()
        action = request.form.get("action", "save")
        if action == "disable":
            if credential:
                credential.is_enabled = False
                db.session.commit()
            flash("ИИ отключён. Сохранённый ключ не удалён.", "info")
            return redirect(url_for("ai_credentials.settings"))
        if action == "delete":
            if credential:
                db.session.delete(credential)
                db.session.commit()
            flash("Сохранённый AI-ключ удалён.", "success")
            return redirect(url_for("ai_credentials.settings"))
        if action != "save":
            abort(400)

        provider = request.form.get("provider", "")
        api_key = request.form.get("api_key", "")
        folder_id = request.form.get("folder_id", "")
        if request.form.get("consent_version") != CONSENT_VERSION:
            flash("Перед сохранением ключа необходимо подтвердить условия использования.", "warning")
            return redirect(url_for("ai_credentials.settings"))
        if request.form.get("paid_request_notice") != "accepted" or request.form.get("consent_accepted") != "accepted":
            flash("Подтвердите, что запросы к провайдеру могут быть платными.", "warning")
            return redirect(url_for("ai_credentials.settings"))
        try:
            encrypted = encrypt_ai_credential(
                user_id=current_user.id, provider=provider, api_key=api_key, folder_id=folder_id
            )
        except ValueError as error:
            flash(str(error), "warning")
            return redirect(url_for("ai_credentials.settings"))

        now = datetime.utcnow()
        if credential is None:
            credential = AICredential(
                user_id=current_user.id,
                provider=provider,
                encrypted_payload=encrypted,
                is_enabled=True,
                consent_version=CONSENT_VERSION,
                consented_at=now,
            )
            db.session.add(credential)
        else:
            credential.provider = provider
            credential.encrypted_payload = encrypted
            credential.is_enabled = True
            credential.consent_version = CONSENT_VERSION
            credential.consented_at = now
        try:
            db.session.commit()
        except Exception as error:
            db.session.rollback()
            current_app.logger.warning(
                "AI credential save failed (user_id=%s, error_type=%s)",
                current_user.id,
                type(error).__name__,
            )
            flash("Не удалось сохранить ключ. Проверьте настройки и попробуйте ещё раз.", "danger")
            return redirect(url_for("ai_credentials.settings"))
        flash("Ключ сохранён в зашифрованном виде. Проверочный запрос не выполнялся.", "success")
        return redirect(url_for("ai_credentials.settings"))

    return render_template("ai_credentials_settings.html", credential=credential)


@ai_credentials_bp.route("/settings/ai-credentials/disable", methods=["POST"])
@login_required
def disable():
    _check_csrf()
    credential = AICredential.query.filter_by(user_id=current_user.id).first()
    if credential:
        credential.is_enabled = False
        db.session.commit()
    flash("ИИ отключён. Сохранённый ключ не удалён.", "info")
    return redirect(url_for("ai_credentials.settings"))


@ai_credentials_bp.route("/settings/ai-credentials/delete", methods=["POST"])
@login_required
def delete():
    _check_csrf()
    credential = AICredential.query.filter_by(user_id=current_user.id).first()
    if credential:
        db.session.delete(credential)
        db.session.commit()
    flash("Сохранённый AI-ключ удалён.", "success")
    return redirect(url_for("ai_credentials.settings"))
