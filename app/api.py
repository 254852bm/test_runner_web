from flask import Blueprint, request, jsonify
from datetime import datetime
from app import db
from app.models import ApiToken, TestCase, TestRun, StepRun, TestStep


api_bp = Blueprint('api', __name__, url_prefix='/api')


def _error(message, code=400):
    """Единый формат ошибок."""
    return jsonify({"ok": False, "error": message}), code


def _get_user_by_token(token):
    """Ищет пользователя по API-токену. Обновляет last_used_at."""
    if not token:
        return None
    api_token = ApiToken.query.filter_by(token=token).first()
    if not api_token:
        return None
    api_token.last_used_at = datetime.utcnow()
    db.session.commit()
    return api_token.user


@api_bp.route('/run', methods=['POST'])
def api_run():
    """
    Приём результата прогона тест-кейса от автоматического скрипта.

    Ожидаемый JSON:
    {
        "token": "xxx",
        "test_case_id": 15,
        "status": "PASS",           # PASS / FAIL / SKIP
        "comment": "всё ок",        # опционально
        "duration_ms": 1234,        # опционально
        "step_results": [           # опционально
            {"step_id": 1, "status": "PASS", "actual_result": "OK"},
            {"step_id": 2, "status": "FAIL", "actual_result": "Кнопка не найдена"}
        ]
    }
    """
    data = request.get_json(silent=True)
    if not data:
        return _error('Тело запроса должно быть в формате JSON')

    token = data.get('token', '').strip()
    user = _get_user_by_token(token)
    if not user:
        return _error('Неверный или отсутствующий API-токен', 401)

    test_case_id = data.get('test_case_id')
    if not test_case_id:
        return _error('Не указан test_case_id')

    test_case = TestCase.query.get(test_case_id)
    if not test_case:
        return _error(f'Тест-кейс с id={test_case_id} не найден', 404)

    # Проверяем, что тест-кейс принадлежит пользователю
    if test_case.project.owner.id != user.id:
        return _error('Доступ запрещён', 403)

    status = (data.get('status') or '').upper()
    if status not in ['PASS', 'FAIL', 'SKIP']:
        return _error('status должен быть PASS, FAIL или SKIP')

    comment = (data.get('comment') or '').strip()
    duration_ms = data.get('duration_ms')

    # Определяем версию тест-кейса (последнюю)
    from app.models import TestCaseVersion
    latest_version = TestCaseVersion.query.filter_by(
        test_case_id=test_case.id
    ).order_by(TestCaseVersion.version_number.desc()).first()

    # Создаём TestRun
    run = TestRun(
        status=status,
        comment=comment,
        test_case_id=test_case.id,
        user_id=user.id,
        version_id=latest_version.id if latest_version else None,
        source='auto',
        duration_ms=duration_ms
    )
    db.session.add(run)
    db.session.flush()

    # Сохраняем результаты шагов
    step_results = data.get('step_results') or []
    for item in step_results:
        step_id = item.get('step_id')
        step_status = (item.get('status') or '').upper()
        actual_result = item.get('actual_result', '')

        if step_status not in ['PASS', 'FAIL', 'SKIP']:
            continue

        step = TestStep.query.get(step_id)
        if not step or step.test_case_id != test_case.id:
            continue

        sr = StepRun(
            test_run_id=run.id,
            test_step_id=step.id,
            status=step_status,
            comment='',
            step_text=step.action,
            expected_result=step.expected_result or '',
            actual_result=str(actual_result or '')
        )
        db.session.add(sr)

    db.session.commit()

    return jsonify({
        "ok": True,
        "run_id": run.id,
        "status": status,
        "test_case_id": test_case.id
    }), 201


@api_bp.route('/ping', methods=['GET'])
def api_ping():
    """Простой ping — проверить, что API живой."""
    return jsonify({"ok": True, "message": "TestRun API работает"})
