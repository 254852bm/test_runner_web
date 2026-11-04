from flask import Blueprint, request, jsonify
import re
from datetime import datetime
from app import db
from app.models import ApiToken, TestCase, TestRun, StepRun, TestStep, TestDataSet, TestDataRow


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
    user = api_token.user
    if not user or user.is_deleted or user.is_blocked_now:
        return None
    api_token.last_used_at = datetime.utcnow()
    db.session.commit()
    return user



_SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|access[_-]?key)", re.IGNORECASE
)


def _get_user_from_request():
    """Authenticate GET API requests without putting tokens in URLs."""
    authorization = (request.headers.get('Authorization') or '').strip()
    token = ''
    if authorization.lower().startswith('bearer '):
        token = authorization[7:].strip()
    if not token:
        token = (request.headers.get('X-API-Token') or '').strip()
    return _get_user_by_token(token)


def _owns_test_case(user, test_case):
    return bool(
        user and test_case and test_case.project
        and test_case.project.user_id == user.id
    )


@api_bp.route('/test-cases/<int:test_case_id>/data-sets', methods=['GET'])
def api_test_case_data_sets(test_case_id):
    """List data sets and variable metadata for an owned test case."""
    user = _get_user_from_request()
    if not user:
        return _error('Неверный или отсутствующий API-токен', 401)

    test_case = TestCase.query.get(test_case_id)
    if not test_case:
        return _error('Тест-кейс не найден', 404)
    if not _owns_test_case(user, test_case):
        return _error('Доступ запрещён', 403)

    datasets = TestDataSet.query.filter_by(test_case_id=test_case.id).order_by(
        TestDataSet.id.asc()
    ).all()
    return jsonify({
        "ok": True,
        "test_case_id": test_case.id,
        "data_sets": [
            {
                "id": dataset.id,
                "name": dataset.name,
                "columns": [
                    {
                        "key": column.key,
                        "label": column.label,
                        "is_secret": bool(
                            column.is_secret or _SENSITIVE_KEY_RE.search(column.key or '')
                        ),
                    }
                    for column in dataset.columns
                ],
                "active_rows_count": sum(1 for row in dataset.rows if row.is_enabled),
            }
            for dataset in datasets
        ],
    })


@api_bp.route('/data-sets/<int:dataset_id>/rows', methods=['GET'])
def api_data_set_rows(dataset_id):
    """Return active rows with ordinary values only; never expose secret-like columns."""
    user = _get_user_from_request()
    if not user:
        return _error('Неверный или отсутствующий API-токен', 401)

    dataset = TestDataSet.query.get(dataset_id)
    if not dataset:
        return _error('Набор данных не найден', 404)
    test_case = TestCase.query.get(dataset.test_case_id)
    if not _owns_test_case(user, test_case):
        return _error('Доступ запрещён', 403)

    safe_columns = [
        column for column in dataset.columns
        if not column.is_secret and not _SENSITIVE_KEY_RE.search(column.key or '')
    ]
    rows = TestDataRow.query.filter_by(
        dataset_id=dataset.id, is_enabled=True
    ).order_by(TestDataRow.position.asc(), TestDataRow.id.asc()).all()

    return jsonify({
        "ok": True,
        "data_set_id": dataset.id,
        "test_case_id": test_case.id,
        "data_set_name": dataset.name,
        "columns": [
            {"key": column.key, "label": column.label}
            for column in safe_columns
        ],
        "rows": [
            {
                "id": row.id,
                "name": row.name,
                "values": {
                    column.key: (row.values_json or {}).get(column.key, "")
                    for column in safe_columns
                },
            }
            for row in rows
        ],
    })


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
