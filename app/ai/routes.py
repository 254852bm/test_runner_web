"""Authenticated UI endpoints for AI-assisted test case drafts.

Generation is opt-in and disabled unless AI_TEST_CASES_ENABLED=1 is explicitly
set in the server environment. Draft generation never writes to the database.
"""

import os

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError, validate_csrf

from app import db
from app.models import AIProviderCredential, Project
from .credentials import CredentialEncryptionError, decrypt_api_key, encrypt_api_key
from .provider import AIProviderError, YandexAIStudioConfig, YandexAIStudioProvider
from .schemas import MAX_REQUIREMENT_LENGTH
from .service import generate_test_case_draft


ai_bp = Blueprint("ai", __name__)


def _generation_enabled():
    configured = current_app.config.get("AI_TEST_CASES_ENABLED")
    if configured is not None:
        return configured is True
    return os.getenv("AI_TEST_CASES_ENABLED", "").strip() == "1"


def _owned_project(project_id):
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first()
    if project is None:
        abort(404)
    return project


def _provider():
    """Build a provider from the authenticated user's own encrypted credential."""
    credential = AIProviderCredential.query.filter_by(user_id=current_user.id).first()
    if credential is None:
        raise AIProviderError("Сначала подключите собственный API-ключ в настройках ИИ.")
    try:
        api_key = decrypt_api_key(credential.encrypted_api_key)
    except CredentialEncryptionError as error:
        raise AIProviderError(str(error)) from error
    return YandexAIStudioProvider(YandexAIStudioConfig(
        api_key=api_key,
        folder_id=credential.folder_id,
        model_uri=credential.model_uri,
        timeout_seconds=current_app.config.get("AI_PROVIDER_TIMEOUT_SECONDS", 25),
        max_completion_tokens=current_app.config.get("AI_MAX_COMPLETION_TOKENS", 3000),
    ))


@ai_bp.route("/settings/ai", methods=["GET", "POST"])
@login_required
def ai_settings():
    credential = AIProviderCredential.query.filter_by(user_id=current_user.id).first()

    if request.method == "POST":
        try:
            validate_csrf(request.form.get("csrf_token"))
        except ValidationError:
            abort(400, description="Недействительный CSRF-токен")

        if request.form.get("billing_acknowledged") != "yes":
            flash("Подтвердите, что понимаете условия оплаты провайдера.", "warning")
            return redirect(url_for("ai.ai_settings"))

        api_key = request.form.get("api_key", "").strip()
        folder_id = request.form.get("folder_id", "").strip()
        model_uri = request.form.get("model_uri", "").strip()
        if not api_key or len(api_key) > 4096:
            flash("Введите корректный API-ключ (не более 4096 символов).", "warning")
            return redirect(url_for("ai.ai_settings"))
        if not folder_id or len(folder_id) > 200 or not model_uri or len(model_uri) > 300:
            flash("Проверьте Folder ID и URI модели.", "warning")
            return redirect(url_for("ai.ai_settings"))

        try:
            encrypted_key = encrypt_api_key(api_key)
        except (ValueError, CredentialEncryptionError) as error:
            flash(str(error), "warning")
            return redirect(url_for("ai.ai_settings"))

        if credential is None:
            credential = AIProviderCredential(
                user_id=current_user.id,
                provider="yandex_ai_studio",
                encrypted_api_key=encrypted_key,
                folder_id=folder_id,
                model_uri=model_uri,
            )
            db.session.add(credential)
        else:
            credential.provider = "yandex_ai_studio"
            credential.encrypted_api_key = encrypted_key
            credential.folder_id = folder_id
            credential.model_uri = model_uri

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Could not save AI provider credential")
            flash("Не удалось сохранить настройки ИИ. Попробуйте позже.", "danger")
            return redirect(url_for("ai.ai_settings"))

        flash("Ключ сохранён в зашифрованном виде. Генерация не запускалась.", "success")
        return redirect(url_for("ai.ai_settings"))

    return render_template(
        "ai_settings.html",
        credential=credential,
        encryption_configured=bool(
            current_app.config.get("AI_CREDENTIAL_ENCRYPTION_KEY")
            or os.getenv("AI_CREDENTIAL_ENCRYPTION_KEY", "")
        ),
    )


@ai_bp.route("/settings/ai/delete", methods=["POST"])
@login_required
def delete_ai_settings():
    try:
        validate_csrf(request.form.get("csrf_token"))
    except ValidationError:
        abort(400, description="Недействительный CSRF-токен")

    credential = AIProviderCredential.query.filter_by(user_id=current_user.id).first()
    if credential is not None:
        db.session.delete(credential)
        db.session.commit()
        flash("Собственный ключ ИИ удалён.", "success")
    else:
        flash("Подключённого ключа нет.", "info")
    return redirect(url_for("ai.ai_settings"))


@ai_bp.route("/project/<int:project_id>/ai-draft", methods=["GET", "POST"])
@login_required
def test_case_draft(project_id):
    project = _owned_project(project_id)
    draft = None
    requirement = ""

    if request.method == "POST":
        try:
            validate_csrf(request.form.get("csrf_token"))
        except ValidationError:
            abort(400, description="Недействительный CSRF-токен")

        requirement = request.form.get("requirement", "").strip()
        if not _generation_enabled():
            flash("ИИ-помощник пока не включён администратором сервиса.", "info")
        elif request.form.get("paid_request_confirmed") != "yes":
            flash("Перед отправкой подтвердите, что запрос может тарифицироваться вашим провайдером.", "warning")
        else:
            try:
                draft = generate_test_case_draft(_provider(), requirement)
            except ValueError as error:
                flash(str(error), "warning")
            except AIProviderError as error:
                flash(str(error), "warning")

    return render_template(
        "ai_test_case_draft.html",
        project=project,
        draft=draft,
        requirement=requirement,
        ai_enabled=_generation_enabled(),
        max_requirement_length=MAX_REQUIREMENT_LENGTH,
        has_own_ai_key=AIProviderCredential.query.filter_by(user_id=current_user.id).first() is not None,
    )



@ai_bp.route("/project/<int:project_id>/ai-draft/save", methods=["POST"])
@login_required
def save_ai_test_case_draft(project_id):
    """Save an explicitly reviewed draft using the normal TestCase/Version models."""
    from app import db
    from app.models import TestCase
    from app.routes import create_test_version, save_test_steps

    project = _owned_project(project_id)
    try:
        validate_csrf(request.form.get("csrf_token"))
    except ValidationError:
        abort(400, description="Недействительный CSRF-токен")

    title = request.form.get("title", "").strip()
    precondition = request.form.get("precondition", "").strip()
    actions = request.form.getlist("step_action[]")
    expected_results = request.form.getlist("step_expected[]")
    pairs = [
        (action.strip(), expected.strip())
        for action, expected in zip(actions, expected_results)
        if action and action.strip()
    ]

    if not title or len(title) > 200 or not pairs or len(pairs) > 30:
        flash("Проверьте название и шаги тест-кейса. Нужен хотя бы один шаг.", "warning")
        return redirect(url_for("ai.test_case_draft", project_id=project.id))

    if any(len(action) > 1000 or len(expected) > 1000 for action, expected in pairs):
        flash("Текст одного шага не должен превышать 1000 символов.", "warning")
        return redirect(url_for("ai.test_case_draft", project_id=project.id))

    if len(precondition) > 5000:
        flash("Предусловие слишком длинное.", "warning")
        return redirect(url_for("ai.test_case_draft", project_id=project.id))

    test = TestCase(
        title=title,
        precondition=precondition,
        steps="\n".join(action for action, _ in pairs),
        expected_result="\n".join(expected for _, expected in pairs),
        project_id=project.id,
    )
    try:
        db.session.add(test)
        db.session.flush()
        save_test_steps(
            test,
            [action for action, _ in pairs],
            [expected for _, expected in pairs],
        )
        create_test_version(test)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not save reviewed AI test case draft")
        flash("Не удалось сохранить тест-кейс. Попробуйте ещё раз.", "danger")
        return redirect(url_for("ai.test_case_draft", project_id=project.id))

    flash("Тест-кейс сохранён. Проверьте его и при необходимости добавьте скриншоты.", "success")
    return redirect(url_for("main.test_detail", project_id=project.id, test_id=test.id))
