"""Safe, opt-in AI generation of Java/JUnit 5 automation-test drafts.

Generated code is rendered for review only. This blueprint never persists or
executes generated code and never includes test-data values in provider context.
"""

from flask import Blueprint, abort, current_app, flash, render_template, request
from flask_login import current_user, login_required
from flask_wtf.csrf import ValidationError, validate_csrf

from app.models import AICredential, Project, TestCase, TestDataColumn, TestDataSet, TestStep
from .routes import (
    _provider,
    _provider_mode,
    _reserve_generation_slot,
)
from .automation_service import generate_automation_test_draft
from .provider import AIProviderError


automation_ai_bp = Blueprint("automation_ai", __name__)


def _automation_enabled():
    configured = current_app.config.get("AI_AUTOMATION_TESTS_ENABLED")
    if configured is not None:
        return configured is True
    import os
    return os.getenv("AI_AUTOMATION_TESTS_ENABLED", "").strip() == "1"


def _owned_test(project_id, test_id):
    project = Project.query.filter_by(
        id=project_id, user_id=current_user.id
    ).first()
    if project is None:
        abort(404)
    test_case = TestCase.query.filter_by(
        id=test_id, project_id=project.id
    ).first_or_404()
    return project, test_case


def _safe_test_case_context(test_case):
    steps = TestStep.query.filter_by(test_case_id=test_case.id).order_by(
        TestStep.position.asc(), TestStep.id.asc()
    ).all()
    if not steps:
        raise ValueError("Сначала добавьте в тест-кейс хотя бы один шаг.")

    parameters = []
    seen = set()
    datasets = TestDataSet.query.filter_by(test_case_id=test_case.id).all()
    for dataset in datasets:
        columns = TestDataColumn.query.filter_by(dataset_id=dataset.id).order_by(
            TestDataColumn.position.asc(), TestDataColumn.id.asc()
        ).all()
        for column in columns:
            identity = column.key.casefold()
            if identity in seen:
                continue
            seen.add(identity)
            # Deliberately include names and secrecy flags only, never row values.
            parameters.append({
                "name": column.label or column.key,
                "is_secret": bool(column.is_secret),
            })

    return {
        "title": test_case.title,
        "preconditions": [
            line.strip()
            for line in (test_case.precondition or "").splitlines()
            if line.strip()
        ][:10],
        "steps": [
            {
                "action": step.action or "",
                "expected_result": step.expected_result or "",
            }
            for step in steps
        ],
        "parameters": parameters,
    }


@automation_ai_bp.route(
    "/project/<int:project_id>/test/<int:test_id>/automation-draft",
    methods=["GET", "POST"],
)
@login_required
def automation_test_draft(project_id, test_id):
    project, test_case = _owned_test(project_id, test_id)
    provider_mode = _provider_mode()
    credential = AICredential.query.filter_by(user_id=current_user.id).first()
    credential_available = (
        provider_mode == "ollama" or bool(credential and credential.is_enabled)
    )
    enabled = _automation_enabled()
    draft = None

    if request.method == "POST":
        try:
            validate_csrf(request.form.get("csrf_token"))
        except ValidationError:
            abort(400, description="Недействительный CSRF-токен")

        if not enabled:
            flash("Генерация автотестов с ИИ пока не включена администратором.", "info")
        elif not credential_available:
            flash("Подключите собственный AI-ключ в настройках TestRun.", "info")
        elif provider_mode != "ollama" and request.form.get("paid_request_confirm") != "accepted":
            flash("Перед запросом подтвердите возможную оплату AI-провайдеру.", "warning")
        elif not _reserve_generation_slot():
            flash("Достигнут часовой лимит AI-запросов. Попробуйте позже.", "warning")
        else:
            try:
                context = _safe_test_case_context(test_case)
                draft = generate_automation_test_draft(_provider(), context)
            except (ValueError, AIProviderError) as error:
                flash(str(error), "warning")

    return render_template(
        "ai_automation_test_draft.html",
        project=project,
        test=test_case,
        draft=draft,
        enabled=enabled,
        credential_available=credential_available,
        provider_mode=provider_mode,
    )
