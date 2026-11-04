"""Authenticated UI endpoints for AI-assisted test case drafts.

Generation is opt-in and disabled unless AI_TEST_CASES_ENABLED=1 is explicitly
set in the server environment. Draft generation never writes to the database.
"""

import os

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError, validate_csrf

from app.models import Project
from .provider import AIProviderError, YandexAIStudioConfig, YandexAIStudioProvider
from .schemas import MAX_REQUIREMENT_LENGTH, MAX_STEPS, MAX_STEP_TEXT_LENGTH
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
    api_key = current_app.config.get("YANDEX_AI_API_KEY") or os.getenv("YANDEX_AI_API_KEY", "")
    folder_id = current_app.config.get("YANDEX_AI_FOLDER_ID") or os.getenv("YANDEX_AI_FOLDER_ID", "")
    model_uri = current_app.config.get("YANDEX_AI_MODEL_URI") or os.getenv("YANDEX_AI_MODEL_URI", "")
    return YandexAIStudioProvider(YandexAIStudioConfig(
        api_key=api_key,
        folder_id=folder_id,
        model_uri=model_uri,
        timeout_seconds=current_app.config.get("AI_PROVIDER_TIMEOUT_SECONDS", 25),
        max_completion_tokens=current_app.config.get("AI_MAX_COMPLETION_TOKENS", 3000),
    ))


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

    # Do not use zip() on untrusted form arrays until their lengths match:
    # zip() silently drops trailing actions/results and can corrupt a test case.
    if len(actions) != len(expected_results):
        flash("Не удалось проверить шаги: действия и ожидаемые результаты не совпадают.", "warning")
        return redirect(url_for("ai.test_case_draft", project_id=project.id))

    if not 1 <= len(actions) <= MAX_STEPS:
        flash(f"Тест-кейс должен содержать от 1 до {MAX_STEPS} шагов.", "warning")
        return redirect(url_for("ai.test_case_draft", project_id=project.id))

    pairs = []
    for index, (action, expected) in enumerate(zip(actions, expected_results), start=1):
        action = action.strip()
        expected = expected.strip()
        if not action:
            flash(f"Заполните действие в шаге {index}.", "warning")
            return redirect(url_for("ai.test_case_draft", project_id=project.id))
        if len(action) > MAX_STEP_TEXT_LENGTH or len(expected) > MAX_STEP_TEXT_LENGTH:
            flash(f"Текст действия и ожидаемого результата в шаге {index} не должен превышать {MAX_STEP_TEXT_LENGTH} символов.", "warning")
            return redirect(url_for("ai.test_case_draft", project_id=project.id))
        pairs.append((action, expected))

    if not title or len(title) > 200:
        flash("Название тест-кейса обязательно и не должно превышать 200 символов.", "warning")
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
    except Exception as error:
        db.session.rollback()
        # Avoid logging exception text/tracebacks here: database exceptions may
        # include SQL parameters containing user-authored test case content.
        current_app.logger.warning(
            "AI draft save failed (project_id=%s, user_id=%s, error_type=%s)",
            project.id,
            current_user.id,
            type(error).__name__,
        )
        flash("Не удалось сохранить тест-кейс. Попробуйте ещё раз.", "danger")
        return redirect(url_for("ai.test_case_draft", project_id=project.id))

    flash("Тест-кейс сохранён. Проверьте его и при необходимости добавьте скриншоты.", "success")
    return redirect(url_for("main.test_detail", project_id=project.id, test_id=test.id))
