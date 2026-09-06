from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import Project, TestCase, Step, StepRun, TestRun
from datetime import datetime

main_bp = Blueprint('main', __name__)


def user_project(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id:
        flash('Доступ запрещён', 'danger')
        return None
    return project


# ===== ГЛАВНАЯ =====
@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')


# ===== ДАШБОРД =====
@main_bp.route('/dashboard')
@login_required
def dashboard():
    projects_count = Project.query.filter_by(user_id=current_user.id).count()
    tests_count = TestCase.query.join(Project).filter(Project.user_id == current_user.id).count()
    today = datetime.utcnow().date()
    runs_today = TestRun.query.filter(
        TestRun.user_id == current_user.id,
        TestRun.timestamp >= today
    ).count()
    runs_total = TestRun.query.filter_by(user_id=current_user.id).count()
    recent_runs = TestRun.query.filter_by(user_id=current_user.id).order_by(TestRun.timestamp.desc()).limit(5).all()
    return render_template('dashboard.html',
                           projects_count=projects_count,
                           tests_count=tests_count,
                           runs_today=runs_today,
                           runs_total=runs_total,
                           recent_runs=recent_runs)


# ===== ПРОЕКТЫ =====
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
        else:
            flash('Введите название', 'danger')
    return render_template('create_project.html')


# ===== СТРАНИЦА ПРОЕКТА =====
@main_bp.route('/project/<int:project_id>')
@login_required
def project_detail(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    tests = TestCase.query.filter_by(project_id=project.id).all()
    return render_template('project_detail.html', project=project, tests=tests)


# ===== СОЗДАНИЕ ТЕСТА С ШАГАМИ =====
@main_bp.route('/project/<int:project_id>/create_test', methods=['GET', 'POST'])
@login_required
def create_test(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        precondition = request.form.get('precondition', '').strip()
        descriptions = request.form.getlist('step_description[]')
        expecteds = request.form.getlist('step_expected[]')

        if not title:
            flash('Введите заголовок теста', 'danger')
            return render_template('create_test.html', project_id=project.id)

        test = TestCase(
            title=title,
            precondition=precondition,
            steps='',
            project_id=project.id
        )
        db.session.add(test)
        db.session.flush()

        for i, (desc, exp) in enumerate(zip(descriptions, expecteds), start=1):
            if desc and exp:
                step = Step(
                    order=i,
                    description=desc.strip(),
                    expected_result=exp.strip(),
                    test_case_id=test.id
                )
                db.session.add(step)

        db.session.commit()
        flash('Тест и шаги добавлены!', 'success')
        return redirect(url_for('main.project_detail', project_id=project.id))

    return render_template('create_test.html', project_id=project.id)


# ===== ПРОГОН ТЕСТОВ (ПОШАГОВЫЙ) =====
@main_bp.route('/project/<int:project_id>/run', methods=['GET', 'POST'])
@login_required
def run_tests(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))

    tests = TestCase.query.filter_by(project_id=project.id).all()
    if not tests:
        flash('В этом проекте нет тестов для прогона', 'warning')
        return redirect(url_for('main.project_detail', project_id=project.id))

    current_index = request.args.get('index', 0, type=int)
    if current_index < 0 or current_index >= len(tests):
        flash('Некорректный индекс теста', 'danger')
        return redirect(url_for('main.project_detail', project_id=project.id))

    test = tests[current_index]

    if request.method == 'POST':
        for step in test.step_list:
            status_key = f'status_{step.id}'
            actual_key = f'actual_{step.id}'
            status = request.form.get(status_key)
            actual_result = request.form.get(actual_key, '').strip()
            if status in ['PASS', 'FAIL', 'SKIP']:
                step_run = StepRun(
                    status=status,
                    actual_result=actual_result,
                    comment='',
                    step_id=step.id,
                    user_id=current_user.id
                )
                db.session.add(step_run)
        db.session.commit()
        flash(f'Тест "{test.title}" пройден!', 'success')

        next_index = current_index + 1
        if next_index < len(tests):
            return redirect(url_for('main.run_tests', project_id=project.id, index=next_index))
        else:
            return redirect(url_for('main.run_stats_all', project_id=project.id))

    return render_template('run.html', project=project, test=test,
                           current_index=current_index, total=len(tests))


# ===== СТАТИСТИКА ПОСЛЕ ОДНОГО ТЕСТА =====
@main_bp.route('/project/<int:project_id>/stats/<int:test_id>')
@login_required
def run_stats(project_id, test_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    test = TestCase.query.get_or_404(test_id)
    if test.project_id != project.id:
        flash('Доступ запрещён', 'danger')
        return redirect(url_for('main.projects'))

    step_runs = StepRun.query.join(Step).filter(
        Step.test_case_id == test.id,
        StepRun.user_id == current_user.id
    ).order_by(StepRun.timestamp.desc()).all()

    if step_runs:
        last_timestamp = step_runs[0].timestamp
        last_runs = [sr for sr in step_runs if sr.timestamp == last_timestamp]
        stats = {
            'PASS': sum(1 for sr in last_runs if sr.status == 'PASS'),
            'FAIL': sum(1 for sr in last_runs if sr.status == 'FAIL'),
            'SKIP': sum(1 for sr in last_runs if sr.status == 'SKIP'),
            'TOTAL': len(last_runs)
        }
    else:
        stats = {'PASS': 0, 'FAIL': 0, 'SKIP': 0, 'TOTAL': 0}

    return render_template('stats.html', project=project, test=test,
                           step_runs=step_runs, stats=stats)


# ===== ИТОГОВАЯ СТАТИСТИКА ПОСЛЕ ВСЕХ ТЕСТОВ =====
@main_bp.route('/project/<int:project_id>/stats_all')
@login_required
def run_stats_all(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))

    step_runs = StepRun.query.join(Step).join(TestCase).filter(
        TestCase.project_id == project.id,
        StepRun.user_id == current_user.id
    ).order_by(StepRun.timestamp.desc()).all()

    if step_runs:
        last_timestamp = step_runs[0].timestamp
        last_runs = [sr for sr in step_runs if sr.timestamp == last_timestamp]
        stats = {
            'PASS': sum(1 for sr in last_runs if sr.status == 'PASS'),
            'FAIL': sum(1 for sr in last_runs if sr.status == 'FAIL'),
            'SKIP': sum(1 for sr in last_runs if sr.status == 'SKIP'),
            'TOTAL': len(last_runs)
        }
    else:
        stats = {'PASS': 0, 'FAIL': 0, 'SKIP': 0, 'TOTAL': 0}

    return render_template('stats_all.html', project=project, stats=stats, runs=step_runs)


# ===== ИСТОРИЯ ПРОГОНОВ =====
@main_bp.route('/project/<int:project_id>/history')
@login_required
def run_history(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    runs = StepRun.query.join(Step).join(TestCase).filter(
        TestCase.project_id == project.id,
        StepRun.user_id == current_user.id
    ).order_by(StepRun.timestamp.desc()).all()
    return render_template('history.html', project=project, runs=runs)


# ===== ЭКСПОРТ PDF (с шагами) =====
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
    from io import BytesIO
    from flask import send_file
    import os

    font_paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'
    ]
    font_registered = False
    for path in font_paths:
        if os.path.exists(path):
            pdfmetrics.registerFont(TTFont('CustomFont', path))
            font_registered = True
            break
    if not font_registered:
        font_name = 'Helvetica'
    else:
        font_name = 'CustomFont'

    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))

    tests = TestCase.query.filter_by(project_id=project.id).all()
    if not tests:
        flash('Нет тестов для экспорта', 'warning')
        return redirect(url_for('main.project_detail', project_id=project.id))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=72, leftMargin=72,
                            topMargin=72, bottomMargin=72)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Title'], fontName=font_name)
    heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'], fontName=font_name)
    normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'], fontName=font_name)

    elements = []

    elements.append(Paragraph(f"Отчёт по проекту: {project.name}", title_style))
    elements.append(Spacer(1, 0.25 * inch))
    elements.append(Paragraph(f"Пользователь: {current_user.email}", normal_style))
    elements.append(Paragraph(f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}", normal_style))
    elements.append(Spacer(1, 0.25 * inch))

    for test in tests:
        elements.append(Paragraph(f"Тест: {test.title}", heading_style))
        if test.precondition:
            elements.append(Paragraph(f"Предусловие: {test.precondition}", normal_style))
        if test.step_list:
            elements.append(Paragraph("Шаги:", normal_style))
            data = [['#', 'Описание', 'Ожидаемый результат']]
            for step in test.step_list:
                data.append([str(step.order), step.description, step.expected_result])
            table = Table(data, colWidths=[0.5*inch, 3*inch, 2.5*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, -1), font_name),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ]))
            elements.append(table)
        elements.append(Spacer(1, 0.2 * inch))

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f'отчёт_{project.name}_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf',
                     mimetype='application/pdf')
