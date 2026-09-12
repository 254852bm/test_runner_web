from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import Project, TestCase, TestRun, TestStep, StepRun
from datetime import datetime

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


def save_test_steps(test, actions, expected_results):
    TestStep.query.filter_by(test_case_id=test.id).delete(synchronize_session=False)
    for position, (action, expected) in enumerate(zip(actions, expected_results), start=1):
        action = action.strip()
        expected = expected.strip()
        if action:
            db.session.add(TestStep(
                test_case_id=test.id,
                position=position,
                action=action,
                expected_result=expected
            ))


def step_status_summary(step_runs):
    statuses = [step_run.status for step_run in step_runs]
    if 'FAIL' in statuses:
        return 'FAIL'
    if 'SKIP' in statuses:
        return 'SKIP'
    return 'PASS'


@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')


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
    return render_template('project_detail.html', project=project, tests=tests)


@main_bp.route('/project/<int:project_id>/delete', methods=['POST'])
@login_required
def delete_project(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))

    test_ids = [test.id for test in TestCase.query.filter_by(project_id=project.id).all()]
    if test_ids:
        run_ids = [run.id for run in TestRun.query.filter(TestRun.test_case_id.in_(test_ids)).all()]
        if run_ids:
            StepRun.query.filter(StepRun.test_run_id.in_(run_ids)).delete(synchronize_session=False)
        TestRun.query.filter(TestRun.test_case_id.in_(test_ids)).delete(synchronize_session=False)
        TestStep.query.filter(TestStep.test_case_id.in_(test_ids)).delete(synchronize_session=False)
        TestCase.query.filter(TestCase.project_id == project.id).delete(synchronize_session=False)

    db.session.delete(project)
    db.session.commit()
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
    return render_template('test_detail.html', project=project, test=test, steps=steps,
                           status_labels=STATUS_LABELS)


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
            db.session.commit()
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

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        actions = request.form.getlist('step_action[]')
        expected_results = request.form.getlist('step_expected[]')
        pairs = [(a.strip(), e.strip()) for a, e in zip(actions, expected_results) if a.strip()]

        if not title or not pairs:
            flash('Заголовок и хотя бы один шаг обязательны', 'danger')
        else:
            test.title = title
            test.precondition = request.form.get('precondition', '').strip()
            test.steps = '\n'.join(action for action, _ in pairs)
            test.expected_result = '\n'.join(expected for _, expected in pairs)
            save_test_steps(test, [a for a, _ in pairs], [e for _, e in pairs])
            db.session.commit()
            flash('Тест-кейс обновлён!', 'success')
            return redirect(url_for('main.test_detail', project_id=project.id, test_id=test.id))

    return render_template('edit_test.html', project=project, test=test, steps=steps)


@main_bp.route('/project/<int:project_id>/test/<int:test_id>/delete', methods=['POST'])
@login_required
def delete_test(project_id, test_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    test = TestCase.query.filter_by(id=test_id, project_id=project.id).first_or_404()
    run_ids = [run.id for run in TestRun.query.filter_by(test_case_id=test.id).all()]
    if run_ids:
        StepRun.query.filter(StepRun.test_run_id.in_(run_ids)).delete(synchronize_session=False)
    TestRun.query.filter_by(test_case_id=test.id).delete(synchronize_session=False)
    TestStep.query.filter_by(test_case_id=test.id).delete(synchronize_session=False)
    db.session.delete(test)
    db.session.commit()
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

        if len(statuses) != len(steps):
            flash('Укажите статус для каждого шага', 'danger')
        elif any(status not in STATUS_LABELS for status in statuses):
            flash('Некорректный статус шага', 'danger')
        else:
            overall_status = step_status_summary([
                type('StepStatus', (), {'status': status})() for status in statuses
            ])
            run = TestRun(
                status=overall_status,
                test_case_id=test.id,
                user_id=current_user.id,
                comment=''
            )
            db.session.add(run)
            db.session.flush()

            for step, status, comment in zip(steps, statuses, comments):
                db.session.add(StepRun(
                    test_run_id=run.id,
                    test_step_id=step.id,
                    status=status,
                    comment=comment.strip(),
                    step_text=step.action,
                    expected_result=step.expected_result or ''
                ))

            db.session.commit()
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
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.enums import TA_LEFT
    from xml.sax.saxutils import escape
    from io import BytesIO
    from flask import send_file
    import os

    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))

    runs = TestRun.query.join(TestCase).filter(
        TestCase.project_id == project.id,
        TestRun.user_id == current_user.id
    ).order_by(TestRun.timestamp.desc()).all()
    if not runs:
        flash('Нет результатов для экспорта', 'warning')
        return redirect(url_for('main.project_detail', project_id=project.id))

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
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36,
                            topMargin=50, bottomMargin=50)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Title'], fontName=font_name)
    heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'], fontName=font_name)
    normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'], fontName=font_name)
    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontName=font_name,
                                fontSize=7, leading=9, alignment=TA_LEFT)

    elements = [Paragraph(f'Отчёт по проекту: {escape(project.name)}', title_style),
                Spacer(1, 0.25 * inch),
                Paragraph(f'Пользователь: {escape(current_user.email)}', normal_style),
                Paragraph(f'Дата: {datetime.now().strftime("%d.%m.%Y %H:%M")}', normal_style),
                Spacer(1, 0.25 * inch)]

    stats = {s: sum(1 for r in runs if r.status == s) for s in ['PASS', 'FAIL', 'SKIP']}
    elements.extend([Paragraph(f'Всего пройдено: {len(runs)}', heading_style),
                     Paragraph(f'PASS: {stats["PASS"]}', normal_style),
                     Paragraph(f'FAIL: {stats["FAIL"]}', normal_style),
                     Paragraph(f'SKIP: {stats["SKIP"]}', normal_style),
                     Spacer(1, 0.25 * inch)])

    data = [[Paragraph('#', cell_style), Paragraph('Тест', cell_style),
             Paragraph('Статус', cell_style), Paragraph('Комментарий', cell_style),
             Paragraph('Дата', cell_style)]]
    for idx, run in enumerate(runs, start=1):
        test_title = run.test_case.title if run.test_case else f'Тест #{run.test_case_id}'
        comment = run.comment or ''
        comment = escape(comment).replace('\n', '<br/>')
        data.append([
            Paragraph(str(idx), cell_style),
            Paragraph(escape(test_title).replace('\n', '<br/>'), cell_style),
            Paragraph(escape(STATUS_LABELS.get(run.status, run.status)), cell_style),
            Paragraph(comment, cell_style),
            Paragraph(run.timestamp.strftime('%d.%m.%Y %H:%M'), cell_style)
        ])

        if run.step_runs:
            data.append([Paragraph('', cell_style), Paragraph('<b>Шаги</b>', cell_style),
                         Paragraph('Статус', cell_style), Paragraph('Комментарий', cell_style),
                         Paragraph('Ожидаемый результат', cell_style)])
            for step_run in sorted(run.step_runs, key=lambda item: item.id):
                data.append([
                    Paragraph('', cell_style),
                    Paragraph(escape(step_run.step_text).replace('\n', '<br/>'), cell_style),
                    Paragraph(escape(STATUS_LABELS.get(step_run.status, step_run.status)), cell_style),
                    Paragraph(escape(step_run.comment or '').replace('\n', '<br/>'), cell_style),
                    Paragraph(escape(step_run.expected_result or '').replace('\n', '<br/>'), cell_style)
                ])

    table = Table(data, colWidths=[0.35*inch, 2.2*inch, 0.85*inch, 2.0*inch, 1.6*inch], repeatRows=1)
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
