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
