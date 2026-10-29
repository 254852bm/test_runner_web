from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file, abort, current_app
from flask_login import login_required, current_user
from markdown import markdown
from markdown.extensions.toc import slugify_unicode
from app import db
from app.models import Project, TestCase, TestCaseVersion, TestRun, TestStep, TestStepScreenshot, StepRun, StepRunScreenshot, ApiToken, FeedbackTicket, FeedbackMessage, User
from datetime import datetime
import secrets
import os
from pathlib import Path
from werkzeug.utils import secure_filename

main_bp = Blueprint('main', __name__)


STATUS_LABELS = {
    'PASS': 'Пройден',
    'FAIL': 'Не пройден',
    'SKIP': 'Пропущен',
}


def user_project(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id:
        flash('Доступ запрещён', 'danger')
        return None
    return project


def ensure_test_steps(test):
    """Создаёт структурированные шаги для старых тест-кейсов."""
    steps = TestStep.query.filter_by(test_case_id=test.id).order_by(TestStep.position).all()
    if steps:
        return steps

    step_lines = [line.strip() for line in (test.steps or '').splitlines() if line.strip()]
    expected_lines = [line.strip() for line in (test.expected_result or '').splitlines() if line.strip()]

    if not step_lines:
        return []

    for position, action in enumerate(step_lines, start=1):
        expected = expected_lines[position - 1] if position <= len(expected_lines) else ''
        db.session.add(TestStep(
            test_case_id=test.id,
            position=position,
            action=action,
            expected_result=expected
        ))
    db.session.commit()
    return TestStep.query.filter_by(test_case_id=test.id).order_by(TestStep.position).all()


def save_test_steps(test, actions, expected_results, source_step_ids=None):
    """
    Rebuild current steps while keeping historical StepRun snapshots intact.
    source_step_ids identifies the existing step represented by each submitted
    row; blank IDs represent newly added steps. This prevents reordering or
    deleting a step from silently changing which current step a historical FK
    points to. If its original step was removed, use the first remaining step
    only to satisfy the non-null FK; history display must use StepRun snapshots.
    """
    normalized_pairs = [
        (action.strip(), expected.strip())
        for action, expected in zip(actions, expected_results)
        if action and action.strip()
    ]
    if not normalized_pairs:
        raise ValueError('Тест-кейс должен содержать хотя бы один шаг.')

    old_steps = TestStep.query.filter_by(test_case_id=test.id).order_by(TestStep.position).all()
    old_by_id = {step.id: step for step in old_steps}
    source_step_ids = list(source_step_ids or [])
    new_steps = []
    source_to_new = {}
    for position, (action, expected) in enumerate(normalized_pairs, start=1):
        step = TestStep(
            test_case_id=test.id,
            position=position,
            action=action,
            expected_result=expected
        )
        db.session.add(step)
        new_steps.append(step)
        source_id = source_step_ids[position - 1] if position - 1 < len(source_step_ids) else None
        if source_id in old_by_id and source_id not in source_to_new:
            source_to_new[source_id] = step

    db.session.flush()
    fallback_step_id = new_steps[0].id if new_steps else None
    for old_step in old_steps:
        replacement = source_to_new.get(old_step.id)
        replacement_id = replacement.id if replacement is not None else fallback_step_id
        if replacement_id is not None:
            StepRun.query.filter_by(test_step_id=old_step.id).update(
                {StepRun.test_step_id: replacement_id},
                synchronize_session=False
            )
        for screenshot in old_step.screenshots:
            db.session.delete(screenshot)
        db.session.delete(old_step)


def save_uploaded_screenshots(uploads, user_id, step_run_id=None, test_step_id=None):
    """Проверяет изображения до записи и сохраняет их вне репозитория."""
    uploads = [item for item in uploads if item and item.filename]
    if len(uploads) > 5:
        raise ValueError('Для одного шага можно прикрепить не более 5 изображений.')

    prepared = []
    for upload in uploads:
        data = upload.read(5 * 1024 * 1024 + 1)
        if not data:
            continue
        if len(data) > 5 * 1024 * 1024:
            raise ValueError('Размер одного изображения не должен превышать 5 МБ.')
        if data[:3] == bytes([255, 216, 255]):
            image_type = 'jpeg'
        elif data.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10])):
            image_type = 'png'
        elif data.startswith((b'GIF87a', b'GIF89a')):
            image_type = 'gif'
        elif len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            image_type = 'webp'
        else:
            raise ValueError('Разрешены только изображения PNG, JPEG, GIF и WEBP.')
        mime_types = {'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp'}
        extension = 'jpg' if image_type == 'jpeg' else image_type
        original_name = secure_filename(upload.filename or '')[:255] or f'screenshot.{extension}'
        prepared.append((data, extension, original_name, mime_types[image_type]))

    upload_dir = Path(current_app.instance_path) / 'step-screenshots'
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    try:
        for data, extension, original_name, mime_type in prepared:
            stored_name = secrets.token_hex(24) + '.' + extension
            file_path = upload_dir / stored_name
            file_path.write_bytes(data)
            saved_paths.append(file_path)
            if step_run_id is not None:
                db.session.add(StepRunScreenshot(
                    step_run_id=step_run_id, user_id=user_id, stored_name=stored_name,
                    original_name=original_name, mime_type=mime_type, size_bytes=len(data)
                ))
            elif test_step_id is not None:
                db.session.add(TestStepScreenshot(
                    test_step_id=test_step_id, user_id=user_id, stored_name=stored_name,
                    original_name=original_name, mime_type=mime_type, size_bytes=len(data)
                ))
    except Exception:
        for file_path in saved_paths:
            file_path.unlink(missing_ok=True)
        raise
    return saved_paths


def step_status_summary(step_runs):
    statuses = [step_run.status for step_run in step_runs]
    if 'FAIL' in statuses:
        return 'FAIL'
    if 'SKIP' in statuses:
        return 'SKIP'
    return 'PASS'


def ensure_test_version(test):
    """Создаёт v1 для существующего теста, если история версий ещё пустая."""
    version = TestCaseVersion.query.filter_by(test_case_id=test.id).order_by(
        TestCaseVersion.version_number.desc()
    ).first()
    if version:
        return version

    version = TestCaseVersion(
        test_case_id=test.id,
        version_number=1,
        title=test.title,
        precondition=test.precondition or '',
        steps=test.steps or '',
        expected_result=test.expected_result or '',
        user_id=current_user.id,
    )
    db.session.add(version)
    db.session.commit()
    return version


def create_test_version(test):
    latest = TestCaseVersion.query.filter_by(test_case_id=test.id).order_by(
        TestCaseVersion.version_number.desc()
    ).first()
    version_number = (latest.version_number + 1) if latest else 1
    version = TestCaseVersion(
        test_case_id=test.id,
        version_number=version_number,
        title=test.title,
        precondition=test.precondition or '',
        steps=test.steps or '',
        expected_result=test.expected_result or '',
        user_id=current_user.id,
    )
    db.session.add(version)
    return version


@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')


@main_bp.route('/docs')
@login_required
def documentation():
    page = request.args.get('page', 'guide')
    if page not in ['guide', 'faq', 'selenium']:
        page = 'guide'

    documents = {
        'guide': ('📘 Руководство пользователя', 'docs/user-guide.md'),
        'faq': ('❓ Частые вопросы', 'docs/faq.md'),
        'selenium': ('🤖 Автоматизация (Selenium)', 'docs/selenium-guide.md'),
    }

    title, path = documents[page]

    try:
        with open(path, 'r', encoding='utf-8') as file:
            source = file.read()
    except FileNotFoundError:
        flash('Документация временно недоступна.', 'warning')
        return redirect(url_for('main.dashboard'))

    content = markdown(
    source,
    extensions=['extra', 'toc'],
    extension_configs={'toc': {'slugify': slugify_unicode}}
)
    return render_template('documentation.html', title=title, content=content, current_page=page)


@main_bp.route('/dashboard')
@login_required
def dashboard():
    projects = Project.query.filter_by(user_id=current_user.id).order_by(Project.created_at.desc()).all()
    status_filter = request.args.get('status', '').upper()
    if status_filter not in ['PASS', 'FAIL', 'SKIP']:
        status_filter = None

    runs_query = TestRun.query.filter_by(user_id=current_user.id)
    if status_filter:
        runs_query = runs_query.filter_by(status=status_filter)
    runs = runs_query.order_by(TestRun.timestamp.desc()).limit(20).all()

    stats = {
        'PASS': TestRun.query.filter_by(user_id=current_user.id, status='PASS').count(),
        'FAIL': TestRun.query.filter_by(user_id=current_user.id, status='FAIL').count(),
        'SKIP': TestRun.query.filter_by(user_id=current_user.id, status='SKIP').count(),
    }
    stats['TOTAL'] = sum(stats.values())
    return render_template('dashboard.html', projects=projects, runs=runs, stats=stats,
                           status_filter=status_filter)


@main_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        company_name = request.form.get('company_name', '').strip()
        if len(company_name) > 100:
            flash('Название компании должно быть не длиннее 100 символов.', 'danger')
        else:
            current_user.company_name = company_name or None
            db.session.commit()
            flash('Профиль сохранён.', 'success')
            return redirect(url_for('main.profile'))

    projects = Project.query.filter_by(user_id=current_user.id).order_by(Project.created_at.desc()).all()
    project_ids = [project.id for project in projects]
    test_count = TestCase.query.filter(TestCase.project_id.in_(project_ids)).count() if project_ids else 0
    stats = {
        'PASS': TestRun.query.filter_by(user_id=current_user.id, status='PASS').count(),
        'FAIL': TestRun.query.filter_by(user_id=current_user.id, status='FAIL').count(),
        'SKIP': TestRun.query.filter_by(user_id=current_user.id, status='SKIP').count(),
    }
    stats['TOTAL'] = sum(stats.values())
    recent_tickets = FeedbackTicket.query.filter_by(user_id=current_user.id).order_by(
        FeedbackTicket.updated_at.desc()
    ).limit(5).all()
    return render_template(
        'profile.html', projects=projects, test_count=test_count,
        stats=stats, recent_tickets=recent_tickets
    )


@main_bp.route('/projects')
@login_required
def projects():
    user_projects = Project.query.filter_by(user_id=current_user.id).all()
    return render_template('projects.html', projects=user_projects)


@main_bp.route('/projects/create', methods=['GET', 'POST'])
@login_required
def create_project():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if name:
            project = Project(name=name, user_id=current_user.id)
            db.session.add(project)
            db.session.commit()
            flash('Проект создан!', 'success')
            return redirect(url_for('main.projects'))
        flash('Введите название', 'danger')
    return render_template('create_project.html')


@main_bp.route('/project/<int:project_id>')
@login_required
def project_detail(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    tests = TestCase.query.filter_by(project_id=project.id).all()
    for test in tests:
        ensure_test_version(test)
    return render_template('project_detail.html', project=project, tests=tests)


@main_bp.route('/project/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))

    # Collect all related screenshot paths before bulk deletes, which bypass ORM cascades.
    test_ids = [
        test_id for (test_id,) in db.session.query(TestCase.id)
        .filter_by(project_id=project.id).all()
    ]
    screenshot_names = []
    if test_ids:
        step_ids = [
            step_id for (step_id,) in db.session.query(TestStep.id)
            .filter(TestStep.test_case_id.in_(test_ids)).all()
        ]
        run_ids = [
            run_id for (run_id,) in db.session.query(TestRun.id)
            .filter(TestRun.test_case_id.in_(test_ids)).all()
        ]
        step_run_ids = []
        if run_ids:
            step_run_ids = [
                step_run_id for (step_run_id,) in db.session.query(StepRun.id)
                .filter(StepRun.test_run_id.in_(run_ids)).all()
            ]

        if step_ids:
            screenshot_names.extend(
                name for (name,) in db.session.query(TestStepScreenshot.stored_name)
                .filter(TestStepScreenshot.test_step_id.in_(step_ids)).all()
            )
            TestStepScreenshot.query.filter(
                TestStepScreenshot.test_step_id.in_(step_ids)
            ).delete(synchronize_session=False)

        if step_run_ids:
            screenshot_names.extend(
                name for (name,) in db.session.query(StepRunScreenshot.stored_name)
                .filter(StepRunScreenshot.step_run_id.in_(step_run_ids)).all()
            )
            StepRunScreenshot.query.filter(
                StepRunScreenshot.step_run_id.in_(step_run_ids)
            ).delete(synchronize_session=False)
            StepRun.query.filter(StepRun.id.in_(step_run_ids)).delete(synchronize_session=False)

        if run_ids:
            TestRun.query.filter(TestRun.id.in_(run_ids)).delete(synchronize_session=False)
        if step_ids:
            TestStep.query.filter(TestStep.id.in_(step_ids)).delete(synchronize_session=False)
        TestCaseVersion.query.filter(
            TestCaseVersion.test_case_id.in_(test_ids)
        ).delete(synchronize_session=False)
        TestCase.query.filter(TestCase.id.in_(test_ids)).delete(synchronize_session=False)

    db.session.delete(project)
    db.session.commit()

    # Remove files only after the database transaction succeeds.
    upload_dir = Path(current_app.instance_path) / 'step-screenshots'
    for stored_name in set(screenshot_names):
        if not stored_name or Path(stored_name).name != stored_name:
            current_app.logger.warning('Skipping invalid screenshot filename during project deletion')
            continue
        try:
            (upload_dir / stored_name).unlink(missing_ok=True)
        except OSError:
            current_app.logger.exception(
                'Could not remove screenshot file after project deletion'
            )

    flash('Проект и все его тест-кейсы удалены.', 'success')
    return redirect(url_for('main.projects'))


@main_bp.route('/project/<int:project_id>/test/<int:test_id>')
@login_required
def test_detail(project_id, test_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    test = TestCase.query.filter_by(id=test_id, project_id=project.id).first_or_404()
    steps = ensure_test_steps(test)
    current_version = ensure_test_version(test)
    versions = TestCaseVersion.query.filter_by(test_case_id=test.id).order_by(
        TestCaseVersion.version_number.desc()
    ).all()
    return render_template('test_detail.html', project=project, test=test, steps=steps,
                           status_labels=STATUS_LABELS, current_version=current_version,
                           versions=versions)


@main_bp.route('/project/<int:project_id>/test/<int:test_id>/versions/<int:version_number>')
@login_required
def test_version_detail(project_id, test_id, version_number):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    test = TestCase.query.filter_by(id=test_id, project_id=project.id).first_or_404()
    version = TestCaseVersion.query.filter_by(
        test_case_id=test.id, version_number=version_number
    ).first_or_404()
    version_steps = [line.strip() for line in (version.steps or '').splitlines() if line.strip()]
    version_expected = [line.strip() for line in (version.expected_result or '').splitlines() if line.strip()]
    return render_template('test_version_detail.html', project=project, test=test,
                           version=version, version_steps=version_steps,
                           version_expected=version_expected)


@main_bp.route('/project/<int:project_id>/test/<int:test_id>/versions/compare')
@login_required
def compare_test_versions(project_id, test_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    test = TestCase.query.filter_by(id=test_id, project_id=project.id).first_or_404()
    versions = TestCaseVersion.query.filter_by(test_case_id=test.id).order_by(
        TestCaseVersion.version_number.asc()
    ).all()
    if len(versions) < 2:
        flash('Для сравнения нужны как минимум две версии тест-кейса.', 'warning')
        return redirect(url_for('main.test_detail', project_id=project.id, test_id=test.id))

    version_by_number = {version.version_number: version for version in versions}
    try:
        old_number = int(request.args.get('older', ''))
        new_number = int(request.args.get('newer', ''))
    except (TypeError, ValueError):
        old_number, new_number = versions[-2].version_number, versions[-1].version_number

    if old_number == new_number or old_number not in version_by_number or new_number not in version_by_number:
        flash('Выберите две разные существующие версии.', 'danger')
        return redirect(url_for('main.test_detail', project_id=project.id, test_id=test.id))

    older = version_by_number[old_number]
    newer = version_by_number[new_number]
    fields = [
        {'label': 'Название', 'older': older.title or '', 'newer': newer.title or ''},
        {'label': 'Предусловие', 'older': older.precondition or '', 'newer': newer.precondition or ''},
    ]
    for field in fields:
        field['changed'] = field['older'] != field['newer']

    old_actions = [line.strip() for line in (older.steps or '').splitlines() if line.strip()]
    new_actions = [line.strip() for line in (newer.steps or '').splitlines() if line.strip()]
    old_expected = [line.strip() for line in (older.expected_result or '').splitlines() if line.strip()]
    new_expected = [line.strip() for line in (newer.expected_result or '').splitlines() if line.strip()]
    step_comparisons = []
    for index in range(max(len(old_actions), len(new_actions), len(old_expected), len(new_expected))):
        old_action = old_actions[index] if index < len(old_actions) else ''
        new_action = new_actions[index] if index < len(new_actions) else ''
        old_result = old_expected[index] if index < len(old_expected) else ''
        new_result = new_expected[index] if index < len(new_expected) else ''
        if index >= len(old_actions) and index >= len(old_expected):
            state = 'added'
        elif index >= len(new_actions) and index >= len(new_expected):
            state = 'removed'
        elif old_action != new_action or old_result != new_result:
            state = 'changed'
        else:
            state = 'same'
        step_comparisons.append({
            'number': index + 1,
            'older_action': old_action,
            'newer_action': new_action,
            'older_expected': old_result,
            'newer_expected': new_result,
            'state': state,
        })

    return render_template(
        'test_version_compare.html', project=project, test=test, versions=versions,
        older=older, newer=newer, fields=fields, step_comparisons=step_comparisons
    )


@main_bp.route('/project/<int:project_id>/create_test', methods=['GET', 'POST'])
@login_required
def create_test(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        precondition = request.form.get('precondition', '').strip()
        actions = request.form.getlist('step_action[]')
        expected_results = request.form.getlist('step_expected[]')
        pairs = [(a.strip(), e.strip()) for a, e in zip(actions, expected_results) if a.strip()]

        if title and pairs:
            steps_text = '\n'.join(action for action, _ in pairs)
            expected_text = '\n'.join(expected for _, expected in pairs)
            test = TestCase(title=title, precondition=precondition,
                            steps=steps_text, expected_result=expected_text,
                            project_id=project.id)
            db.session.add(test)
            db.session.flush()
            save_test_steps(test, [a for a, _ in pairs], [e for _, e in pairs])
            db.session.flush()
            saved_paths = []
            try:
                for index, step in enumerate(test.step_items):
                    saved_paths.extend(save_uploaded_screenshots(
                        request.files.getlist(f'test_step_screenshot_{index}[]'),
                        user_id=current_user.id, test_step_id=step.id
                    ))
                create_test_version(test)
                db.session.commit()
            except ValueError as error:
                db.session.rollback()
                for path in saved_paths:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception(
                            'Could not remove temporary screenshot after validation failure'
                        )
                flash(str(error), 'danger')
                return render_template('create_test.html', project_id=project.id)
            except Exception:
                db.session.rollback()
                for path in saved_paths:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception(
                            'Could not remove temporary screenshot after failed test creation'
                        )
                raise
            flash('Тест добавлен!', 'success')
            return redirect(url_for('main.project_detail', project_id=project.id))
        flash('Заполните заголовок и добавьте хотя бы один шаг', 'danger')

    return render_template('create_test.html', project_id=project.id)


@main_bp.route('/project/<int:project_id>/test/<int:test_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_test(project_id, test_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    test = TestCase.query.filter_by(id=test_id, project_id=project.id).first_or_404()
    steps = ensure_test_steps(test)
    ensure_test_version(test)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        actions = request.form.getlist('step_action[]')
        expected_results = request.form.getlist('step_expected[]')
        submitted_step_ids = request.form.getlist('step_id[]')
        if len(submitted_step_ids) != len(actions) or len(expected_results) != len(actions):
            flash('Некорректный список шагов. Обновите страницу и попробуйте снова.', 'danger')
            return redirect(url_for('main.edit_test', project_id=project.id, test_id=test.id))

        old_steps = TestStep.query.filter_by(test_case_id=test.id).order_by(TestStep.position).all()
        old_ids = {step.id for step in old_steps}
        pairs = []
        for action, expected, raw_step_id in zip(actions, expected_results, submitted_step_ids):
            action, expected = action.strip(), expected.strip()
            raw_step_id = raw_step_id.strip()
            if raw_step_id:
                try:
                    source_id = int(raw_step_id)
                except ValueError:
                    flash('Некорректный идентификатор шага.', 'danger')
                    return redirect(url_for('main.edit_test', project_id=project.id, test_id=test.id))
                if source_id not in old_ids:
                    flash('Список шагов устарел. Обновите страницу и попробуйте снова.', 'danger')
                    return redirect(url_for('main.edit_test', project_id=project.id, test_id=test.id))
            else:
                source_id = None
            if action:
                pairs.append((action, expected, source_id))

        submitted_existing_ids = [source_id for _, _, source_id in pairs if source_id is not None]
        if len(submitted_existing_ids) != len(set(submitted_existing_ids)):
            flash('Один и тот же существующий шаг указан несколько раз. Обновите страницу и попробуйте снова.', 'danger')
            return redirect(url_for('main.edit_test', project_id=project.id, test_id=test.id))

        if not title or not pairs:
            flash('Заголовок и хотя бы один шаг обязательны', 'danger')
        else:
            test.title = title
            test.precondition = request.form.get('precondition', '').strip()
            test.steps = '\n'.join(action for action, _, _ in pairs)
            test.expected_result = '\n'.join(expected for _, expected, _ in pairs)
            old_screenshots_by_id = {
                step.id: [
                    {
                        'stored_name': screenshot.stored_name,
                        'original_name': screenshot.original_name,
                        'mime_type': screenshot.mime_type,
                        'size_bytes': screenshot.size_bytes,
                        'created_at': screenshot.created_at,
                    }
                    for screenshot in step.screenshots
                ]
                for step in old_steps
            }
            old_screenshot_paths_to_remove = []
            save_test_steps(
                test, [a for a, _, _ in pairs], [e for _, e, _ in pairs],
                source_step_ids=[source_id for _, _, source_id in pairs]
            )
            db.session.flush()
            saved_paths = []
            try:
                upload_dir = Path(current_app.instance_path) / 'step-screenshots'
                retained_source_ids = {source_id for _, _, source_id in pairs if source_id is not None}
                for index, step in enumerate(test.step_items):
                    source_id = pairs[index][2]
                    uploads = [item for item in request.files.getlist(f'test_step_screenshot_{index}[]')
                               if item and item.filename]
                    old_items = old_screenshots_by_id.get(source_id, [])
                    if uploads:
                        old_screenshot_paths_to_remove.extend(upload_dir / item['stored_name'] for item in old_items)
                        saved_paths.extend(save_uploaded_screenshots(
                            uploads, user_id=current_user.id, test_step_id=step.id
                        ))
                    else:
                        # Сохраняем вложения именно исходного шага, даже если шаги переставили местами.
                        for item in old_items:
                            old_path = upload_dir / item['stored_name']
                            if not old_path.is_file():
                                continue
                            extension = old_path.suffix.lstrip('.') or 'img'
                            new_name = secrets.token_hex(24) + '.' + extension
                            new_path = upload_dir / new_name
                            new_path.write_bytes(old_path.read_bytes())
                            saved_paths.append(new_path)
                            db.session.add(TestStepScreenshot(
                                test_step_id=step.id,
                                user_id=current_user.id,
                                stored_name=new_name,
                                original_name=item['original_name'],
                                mime_type=item['mime_type'],
                                size_bytes=item['size_bytes'],
                                created_at=item['created_at'],
                            ))
                            old_screenshot_paths_to_remove.append(old_path)
                # Вложения шагов, удалённых из формы, удаляем только после успешного commit.
                for old_id, items in old_screenshots_by_id.items():
                    if old_id not in retained_source_ids:
                        old_screenshot_paths_to_remove.extend(upload_dir / item['stored_name'] for item in items)
                create_test_version(test)
                db.session.commit()
                for old_path in old_screenshot_paths_to_remove:
                    try:
                        old_path.unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception(
                            'Could not remove replaced screenshot after test case update'
                        )
            except ValueError as error:
                db.session.rollback()
                for path in saved_paths:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception(
                            'Could not remove temporary screenshot after validation failure'
                        )
                flash(str(error), 'danger')
                return redirect(url_for('main.edit_test', project_id=project.id, test_id=test.id))
            except Exception:
                db.session.rollback()
                for path in saved_paths:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception(
                            'Could not remove temporary screenshot after failed test case update'
                        )
                raise
            flash('Тест-кейс обновлён! Создана новая версия.', 'success')
            return redirect(url_for('main.test_detail', project_id=project.id, test_id=test.id))

    return render_template('edit_test.html', project=project, test=test, steps=steps)


@main_bp.route('/project/<int:project_id>/test/<int:test_id>/delete', methods=['POST'])
@login_required
def delete_test(project_id, test_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    test = TestCase.query.filter_by(id=test_id, project_id=project.id).first_or_404()

    # Collect related IDs and filenames before bulk-deleting rows. Bulk deletes
    # bypass SQLAlchemy ORM cascades, so screenshot records need explicit cleanup.
    step_ids = [
        step_id for (step_id,) in db.session.query(TestStep.id)
        .filter_by(test_case_id=test.id).all()
    ]
    run_ids = [
        run_id for (run_id,) in db.session.query(TestRun.id)
        .filter_by(test_case_id=test.id).all()
    ]
    step_run_ids = []
    if run_ids:
        step_run_ids = [
            step_run_id for (step_run_id,) in db.session.query(StepRun.id)
            .filter(StepRun.test_run_id.in_(run_ids)).all()
        ]

    screenshot_names = []
    if step_ids:
        screenshot_names.extend(
            name for (name,) in db.session.query(TestStepScreenshot.stored_name)
            .filter(TestStepScreenshot.test_step_id.in_(step_ids)).all()
        )
        TestStepScreenshot.query.filter(
            TestStepScreenshot.test_step_id.in_(step_ids)
        ).delete(synchronize_session=False)

    if step_run_ids:
        screenshot_names.extend(
            name for (name,) in db.session.query(StepRunScreenshot.stored_name)
            .filter(StepRunScreenshot.step_run_id.in_(step_run_ids)).all()
        )
        StepRunScreenshot.query.filter(
            StepRunScreenshot.step_run_id.in_(step_run_ids)
        ).delete(synchronize_session=False)
        StepRun.query.filter(StepRun.id.in_(step_run_ids)).delete(synchronize_session=False)

    if run_ids:
        TestRun.query.filter(TestRun.id.in_(run_ids)).delete(synchronize_session=False)
    if step_ids:
        TestStep.query.filter(TestStep.id.in_(step_ids)).delete(synchronize_session=False)
    TestCaseVersion.query.filter_by(test_case_id=test.id).delete(synchronize_session=False)
    db.session.delete(test)
    db.session.commit()

    # Delete physical files only after the database transaction succeeds.
    upload_dir = Path(current_app.instance_path) / 'step-screenshots'
    for stored_name in set(screenshot_names):
        if not stored_name or Path(stored_name).name != stored_name:
            current_app.logger.warning('Skipping invalid screenshot filename during test deletion')
            continue
        try:
            (upload_dir / stored_name).unlink(missing_ok=True)
        except OSError:
            current_app.logger.exception(
                'Could not remove screenshot file after test case deletion'
            )

    flash('Тест-кейс удалён вместе с его результатами.', 'success')
    return redirect(url_for('main.project_detail', project_id=project.id))


@main_bp.route('/project/<int:project_id>/run', methods=['GET', 'POST'])
@login_required
def run_tests(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))

    selected_test_id = request.args.get('test_id', type=int)
    if selected_test_id:
        selected_test = TestCase.query.filter_by(id=selected_test_id, project_id=project.id).first_or_404()
        tests = [selected_test]
        single_test = True
    else:
        tests = TestCase.query.filter_by(project_id=project.id).all()
        single_test = False

    if not tests:
        flash('В этом проекте нет тестов для прогона', 'warning')
        return redirect(url_for('main.project_detail', project_id=project.id))

    current_index = request.args.get('index', 0, type=int)
    current_index = max(0, min(current_index, len(tests) - 1))
    test = tests[current_index]
    steps = ensure_test_steps(test)

    if request.method == 'POST':
        statuses = request.form.getlist('step_status[]')
        comments = request.form.getlist('step_comment[]')

        if len(statuses) != len(steps) or len(comments) != len(steps):
            flash('Укажите статус и комментарий для каждого шага', 'danger')
        elif any(status not in STATUS_LABELS for status in statuses):
            flash('Некорректный статус шага', 'danger')
        else:
            # Pin each run to the exact test-case snapshot that was current when it started.
            version = ensure_test_version(test)
            overall_status = step_status_summary([
                type('StepStatus', (), {'status': status})() for status in statuses
            ])
            run = TestRun(
                status=overall_status,
                test_case_id=test.id,
                version_id=version.id,
                user_id=current_user.id,
                comment=''
            )
            db.session.add(run)
            db.session.flush()
            uploaded_paths = []
            try:
                for index, (step, status, comment) in enumerate(zip(steps, statuses, comments)):
                    step_run = StepRun(
                        test_run_id=run.id,
                        test_step_id=step.id,
                        status=status,
                        comment=comment.strip(),
                        step_text=step.action,
                        expected_result=step.expected_result or ''
                    )
                    db.session.add(step_run)
                    db.session.flush()

                    uploads = request.files.getlist(f'step_screenshot_{index}[]')
                    uploads = [item for item in uploads if item and item.filename]
                    if len(uploads) > 5:
                        raise ValueError(f'Для шага {index + 1} можно прикрепить не более 5 изображений.')

                    for upload in uploads:
                        data = upload.read(5 * 1024 * 1024 + 1)
                        if not data:
                            continue
                        if len(data) > 5 * 1024 * 1024:
                            raise ValueError('Размер одного изображения не должен превышать 5 МБ.')
                        if data.startswith(b'\xff\xd8\xff'):
                            image_type = 'jpeg'
                        elif data.startswith(b'\x89PNG\r\n\x1a\n'):
                            image_type = 'png'
                        elif data.startswith((b'GIF87a', b'GIF89a')):
                            image_type = 'gif'
                        else:
                            image_type = None
                        mime_types = {'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif'}
                        if image_type not in mime_types:
                            # WEBP: RIFF....WEBP signature.
                            if not (len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP'):
                                raise ValueError('Разрешены только изображения PNG, JPEG, GIF и WEBP.')
                            mime_type = 'image/webp'
                            extension = 'webp'
                        else:
                            mime_type = mime_types[image_type]
                            extension = 'jpg' if image_type == 'jpeg' else image_type

                        stored_name = secrets.token_hex(24) + '.' + extension
                        upload_dir = Path(current_app.instance_path) / 'step-screenshots'
                        upload_dir.mkdir(parents=True, exist_ok=True)
                        file_path = upload_dir / stored_name
                        file_path.write_bytes(data)
                        uploaded_paths.append(file_path)

                        original_name = secure_filename(upload.filename or '')[:255] or f'screenshot.{extension}'
                        db.session.add(StepRunScreenshot(
                            step_run_id=step_run.id,
                            user_id=current_user.id,
                            stored_name=stored_name,
                            original_name=original_name,
                            mime_type=mime_type,
                            size_bytes=len(data)
                        ))

                db.session.commit()
            except ValueError as error:
                db.session.rollback()
                for file_path in uploaded_paths:
                    try:
                        file_path.unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception('Could not remove a temporary screenshot after validation failure')
                flash(str(error), 'danger')
                return redirect(url_for('main.run_tests', project_id=project.id,
                                        test_id=(test.id if single_test else None), index=current_index))
            except Exception:
                db.session.rollback()
                for file_path in uploaded_paths:
                    try:
                        file_path.unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception('Could not remove a screenshot after a failed test-run save')
                raise

            next_index = current_index + 1
            if next_index < len(tests):
                if single_test:
                    return redirect(url_for('main.run_tests', project_id=project.id,
                                            test_id=test.id, index=next_index))
                return redirect(url_for('main.run_tests', project_id=project.id, index=next_index))
            return redirect(url_for('main.run_stats', project_id=project.id))

    return render_template('run.html', project=project, test=test, steps=steps,
                           current_index=current_index, total=len(tests),
                           single_test=single_test, status_labels=STATUS_LABELS)


@main_bp.route('/test-step-screenshots/<int:screenshot_id>')
@login_required
def view_test_step_screenshot(screenshot_id):
    screenshot = TestStepScreenshot.query.filter_by(
        id=screenshot_id, user_id=current_user.id
    ).first_or_404()
    step = TestStep.query.get_or_404(screenshot.test_step_id)
    test = TestCase.query.get_or_404(step.test_case_id)
    project = Project.query.get_or_404(test.project_id)
    if project.user_id != current_user.id:
        abort(404)
    file_path = Path(current_app.instance_path) / 'step-screenshots' / screenshot.stored_name
    if not file_path.is_file():
        abort(404)
    return send_file(file_path, mimetype=screenshot.mime_type, as_attachment=False,
                     download_name=screenshot.original_name, max_age=0)


@main_bp.route('/screenshots/<int:screenshot_id>')
@login_required
def view_step_screenshot(screenshot_id):
    screenshot = StepRunScreenshot.query.filter_by(
        id=screenshot_id, user_id=current_user.id
    ).first_or_404()
    upload_dir = Path(current_app.instance_path) / 'step-screenshots'
    file_path = upload_dir / screenshot.stored_name
    if not file_path.is_file():
        abort(404)
    return send_file(file_path, mimetype=screenshot.mime_type, as_attachment=False,
                     download_name=screenshot.original_name, max_age=0)


@main_bp.route('/project/<int:project_id>/stats')
@login_required
def run_stats(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    runs = TestRun.query.join(TestCase).filter(
        TestCase.project_id == project.id,
        TestRun.user_id == current_user.id
    ).order_by(TestRun.timestamp.desc()).all()
    stats = {
        'PASS': sum(1 for r in runs if r.status == 'PASS'),
        'FAIL': sum(1 for r in runs if r.status == 'FAIL'),
        'SKIP': sum(1 for r in runs if r.status == 'SKIP'),
        'TOTAL': len(runs)
    }
    return render_template('stats.html', project=project, runs=runs, stats=stats,
                           status_labels=STATUS_LABELS)


@main_bp.route('/project/<int:project_id>/history')
@login_required
def run_history(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    runs = TestRun.query.join(TestCase).filter(
        TestCase.project_id == project.id,
        TestRun.user_id == current_user.id
    ).order_by(TestRun.timestamp.desc()).all()
    for run in runs:
        run.step_runs = sorted(run.step_runs, key=lambda item: item.id)
    return render_template('history.html', project=project, runs=runs,
                           status_labels=STATUS_LABELS)


@main_bp.route('/project/<int:project_id>/export_pdf')
@login_required
def export_pdf(project_id):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.enums import TA_LEFT
    from xml.sax.saxutils import escape
    from io import BytesIO
    import os

    project = user_project(project_id)
    if project is None:
        return redirect(url_for('main.projects'))

    from_date = request.args.get('from_date', '').strip()
    to_date = request.args.get('to_date', '').strip()

    runs_query = TestRun.query.join(TestCase).filter(
        TestCase.project_id == project.id,
        TestRun.user_id == current_user.id
    )
    if from_date:
        runs_query = runs_query.filter(TestRun.timestamp >= from_date)
    if to_date:
        runs_query = runs_query.filter(TestRun.timestamp <= to_date + ' 23:59:59')
    runs = runs_query.order_by(TestRun.timestamp.desc()).all()

    if not runs:
        flash('Нет результатов для экспорта за выбранный период', 'warning')
        return redirect(url_for('main.project_detail', project_id=project.id))

    # Поиск и регистрация шрифта с поддержкой кириллицы (Windows + Linux)
    font_candidates = [
        'C:/Windows/Fonts/arial.ttf',
        '/mnt/c/Windows/Fonts/arial.ttf',
        '/usr/share/fonts/truetype/msttcorefonts/Arial.ttf',
        '/usr/share/fonts/truetype/msttcorefonts/arial.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]

    font_name = 'Helvetica'
    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont('CyrillicFont', font_path))
                font_name = 'CyrillicFont'
                break
            except Exception:
                continue

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=72, leftMargin=72,
                            topMargin=72, bottomMargin=72)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Title'], fontName=font_name)
    heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'], fontName=font_name)
    normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'], fontName=font_name)
    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontName=font_name,
                                fontSize=7, leading=9, alignment=TA_LEFT)

    elements = [Paragraph('Отчёт по проекту: ' + escape(project.name), title_style),
                Spacer(1, 0.25 * inch),
                Paragraph('Пользователь: ' + escape(current_user.email), normal_style),
                Paragraph('Дата: ' + datetime.now().strftime('%d.%m.%Y %H:%M'), normal_style)]

    if from_date or to_date:
        period_text = 'Период: ' + (from_date or '...') + ' — ' + (to_date or '...')
        elements.append(Paragraph(period_text, normal_style))

    elements.append(Spacer(1, 0.25 * inch))

    stats = {s: sum(1 for r in runs if r.status == s) for s in ['PASS', 'FAIL', 'SKIP']}
    elements.extend([Paragraph('Всего прогонов: ' + str(len(runs)), heading_style),
                     Paragraph('PASS: ' + str(stats['PASS']), normal_style),
                     Paragraph('FAIL: ' + str(stats['FAIL']), normal_style),
                     Paragraph('SKIP: ' + str(stats['SKIP']), normal_style),
                     Spacer(1, 0.25 * inch)])

    data = [[Paragraph('#', cell_style), Paragraph('Тест', cell_style),
             Paragraph('Версия', cell_style), Paragraph('Статус', cell_style),
             Paragraph('Комментарий', cell_style), Paragraph('Дата', cell_style)]]
    NL = chr(10)
    for idx, run in enumerate(runs, start=1):
        # Prefer the historical snapshot title; the live test case may have been renamed later.
        test_title = (
            run.version.title if run.version
            else (run.test_case.title if run.test_case else ('Тест #' + str(run.test_case_id)))
        )
        version_label = 'v' + str(run.version.version_number) if run.version else '—'
        comment = run.comment or ''
        comment = escape(comment).replace(NL, '<br/>')
        data.append([
            Paragraph(str(idx), cell_style),
            Paragraph(escape(test_title).replace(NL, '<br/>'), cell_style),
            Paragraph(escape(version_label), cell_style),
            Paragraph(escape(STATUS_LABELS.get(run.status, run.status)), cell_style),
            Paragraph(comment, cell_style),
            Paragraph(run.timestamp.strftime('%d.%m.%Y %H:%M'), cell_style)
        ])

        if run.step_runs:
            data.append([Paragraph('', cell_style), Paragraph('<b>Шаги</b>', cell_style),
                         Paragraph('', cell_style), Paragraph('Статус', cell_style),
                         Paragraph('Комментарий', cell_style), Paragraph('Ожидаемый результат', cell_style)])
            for step_run in sorted(run.step_runs, key=lambda item: item.id):
                data.append([
                    Paragraph('', cell_style),
                    Paragraph(escape(step_run.step_text).replace(NL, '<br/>'), cell_style),
                    Paragraph('', cell_style),
                    Paragraph(escape(STATUS_LABELS.get(step_run.status, step_run.status)), cell_style),
                    Paragraph(escape(step_run.comment or '').replace(NL, '<br/>'), cell_style),
                    Paragraph(escape(step_run.expected_result or '').replace(NL, '<br/>'), cell_style)
                ])
                # В исторический PDF включаем только снимки, прикреплённые к этому прогону.
                # Скриншоты ожидаемого результата относятся к текущей версии тест-кейса
                # и не должны подменять вложения старого прогона.
                related_screenshots = list(step_run.screenshots)
                for screenshot in related_screenshots:
                    screenshot_path = Path(current_app.instance_path) / 'step-screenshots' / screenshot.stored_name
                    if os.path.isfile(screenshot_path):
                        try:
                            screenshot_image = Image(screenshot_path, width=1.25 * inch, height=0.9 * inch, kind='proportional')
                            data.append([
                                Paragraph('', cell_style),
                                Paragraph('Скриншот: ' + escape(screenshot.original_name), cell_style),
                                Paragraph('', cell_style),
                                Paragraph('', cell_style),
                                Paragraph(escape(step_run.comment or '').replace(NL, '<br/>'), cell_style),
                                screenshot_image
                            ])
                        except Exception:
                            current_app.logger.exception('Could not add screenshot %s to PDF', screenshot.id)

    table = Table(data, colWidths=[0.25*inch, 1.5*inch, 0.45*inch, 0.6*inch, 1.35*inch, 1.35*inch], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f'отчёт_{project.name}_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf',
                     mimetype='application/pdf')
# ===== API-ТОКЕНЫ =====

@main_bp.route('/settings/api')
@login_required
def api_tokens():
    tokens = ApiToken.query.filter_by(user_id=current_user.id).order_by(ApiToken.created_at.desc()).all()
    return render_template('api_tokens.html', tokens=tokens)


@main_bp.route('/settings/api/create', methods=['POST'])
@login_required
def api_token_create():
    name = request.form.get('name', '').strip() or 'Без названия'
    token_value = secrets.token_urlsafe(48)
    token = ApiToken(
        user_id=current_user.id,
        token=token_value,
        name=name
    )
    db.session.add(token)
    db.session.commit()
    flash(f'Токен «{name}» создан. Скопируйте его — он больше не будет показан.', 'success')
    return redirect(url_for('main.api_tokens'))


@main_bp.route('/settings/api/delete/<int:token_id>', methods=['POST'])
@login_required
def api_token_delete(token_id):
    token = ApiToken.query.get_or_404(token_id)
    if token.user_id != current_user.id:
        flash('Доступ запрещён', 'danger')
        return redirect(url_for('main.api_tokens'))
    db.session.delete(token)
    db.session.commit()
    flash('Токен удалён', 'success')
    return redirect(url_for('main.api_tokens'))
