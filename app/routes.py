from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app import db
from app.models import Project, TestCase, TestRun
from datetime import datetime

main_bp = Blueprint('main', __name__)


def user_project(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id:
        flash('Доступ запрещён', 'danger')
        return None
    return project


@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')


@main_bp.route('/dashboard')
@login_required
def dashboard():
    projects = Project.query.filter_by(user_id=current_user.id).order_by(Project.created_at.desc()).all()
    runs = TestRun.query.filter_by(user_id=current_user.id).order_by(TestRun.timestamp.desc()).limit(20).all()
    stats = {
        'PASS': TestRun.query.filter_by(user_id=current_user.id, status='PASS').count(),
        'FAIL': TestRun.query.filter_by(user_id=current_user.id, status='FAIL').count(),
        'SKIP': TestRun.query.filter_by(user_id=current_user.id, status='SKIP').count(),
    }
    stats['TOTAL'] = sum(stats.values())
    return render_template('dashboard.html', projects=projects, runs=runs, stats=stats)


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


@main_bp.route('/project/<int:project_id>/create_test', methods=['GET', 'POST'])
@login_required
def create_test(project_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        precondition = request.form.get('precondition', '').strip()
        steps = request.form.get('steps', '').strip()
        expected = request.form.get('expected', '').strip()
        if title and steps:
            test = TestCase(title=title, precondition=precondition,
                            steps=steps, expected_result=expected,
                            project_id=project.id)
            db.session.add(test)
            db.session.commit()
            flash('Тест добавлен!', 'success')
            return redirect(url_for('main.project_detail', project_id=project.id))
        flash('Заполните заголовок и шаги', 'danger')

    return render_template('create_test.html', project_id=project.id)


@main_bp.route('/project/<int:project_id>/test/<int:test_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_test(project_id, test_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    test = TestCase.query.filter_by(id=test_id, project_id=project.id).first_or_404()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        steps = request.form.get('steps', '').strip()
        if not title or not steps:
            flash('Заголовок и шаги обязательны', 'danger')
        else:
            test.title = title
            test.precondition = request.form.get('precondition', '').strip()
            test.steps = steps
            test.expected_result = request.form.get('expected', '').strip()
            db.session.commit()
            flash('Тест-кейс обновлён!', 'success')
            return redirect(url_for('main.project_detail', project_id=project.id))

    return render_template('edit_test.html', project=project, test=test)


@main_bp.route('/project/<int:project_id>/test/<int:test_id>/delete', methods=['POST'])
@login_required
def delete_test(project_id, test_id):
    project = user_project(project_id)
    if not project:
        return redirect(url_for('main.projects'))
    test = TestCase.query.filter_by(id=test_id, project_id=project.id).first_or_404()
    TestRun.query.filter_by(test_case_id=test.id).delete(synchronize_session=False)
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

    tests = TestCase.query.filter_by(project_id=project.id).all()
    if not tests:
        flash('В этом проекте нет тестов для прогона', 'warning')
        return redirect(url_for('main.project_detail', project_id=project.id))

    current_index = request.args.get('index', 0, type=int)
    current_index = max(0, min(current_index, len(tests) - 1))

    if request.method == 'POST':
        status = request.form.get('status')
        comment = request.form.get('comment', '').strip()
        if status in ['PASS', 'FAIL', 'SKIP']:
            test = tests[current_index]
            db.session.add(TestRun(status=status, test_case_id=test.id,
                                    user_id=current_user.id, comment=comment))
            db.session.commit()
            next_index = current_index + 1
            if next_index < len(tests):
                return redirect(url_for('main.run_tests', project_id=project.id, index=next_index))
            return redirect(url_for('main.run_stats', project_id=project.id))
        flash('Неверный статус', 'danger')

    test = tests[current_index]
    return render_template('run.html', project=project, test=test,
                           current_index=current_index, total=len(tests))


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
    return render_template('stats.html', project=project, runs=runs, stats=stats)


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
    return render_template('history.html', project=project, runs=runs)

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
    if project is None:
        return redirect(url_for('main.projects'))

    runs = TestRun.query.join(TestCase).filter(
        TestCase.project_id == project.id,
        TestRun.user_id == current_user.id
    ).order_by(TestRun.timestamp.desc()).all()

    if not runs:
        flash('Нет результатов для экспорта', 'warning')
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

    stats = {
        'PASS': sum(1 for r in runs if r.status == 'PASS'),
        'FAIL': sum(1 for r in runs if r.status == 'FAIL'),
        'SKIP': sum(1 for r in runs if r.status == 'SKIP')
    }
    total = len(runs)

    elements.append(Paragraph(f"Всего пройдено: {total}", heading_style))
    elements.append(Paragraph(f"✅ PASS: {stats['PASS']}", normal_style))
    elements.append(Paragraph(f"❌ FAIL: {stats['FAIL']}", normal_style))
    elements.append(Paragraph(f"⏭️ SKIP: {stats['SKIP']}", normal_style))
    elements.append(Spacer(1, 0.25 * inch))

    data = [['#', 'Тест', 'Статус', 'Комментарий', 'Дата']]
    for idx, run in enumerate(runs, start=1):
        test = TestCase.query.get(run.test_case_id)
        test_title = test.title if test else f"Тест #{run.test_case_id}"
        status_text = run.status
        if run.status == 'PASS':
            status_text = '✅ PASS'
        elif run.status == 'FAIL':
            status_text = '❌ FAIL'
        elif run.status == 'SKIP':
            status_text = '⏭️ SKIP'
        data.append([
            str(idx),
            test_title,
            status_text,
            run.comment or '',
            run.timestamp.strftime('%d.%m.%Y %H:%M')
        ])

    table = Table(data, colWidths=[0.5*inch, 2.5*inch, 0.8*inch, 2*inch, 1.2*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f'отчёт_{project.name}_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf',
                     mimetype='application/pdf')
