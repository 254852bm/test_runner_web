from io import BytesIO
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from app import create_app, db
from app.models import Project, TestCase, TestRun, TestStep, StepRun, User
from app.routes import save_test_steps, save_uploaded_screenshots


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    database_path = tmp_path / "test.sqlite"
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "INSTANCE_PATH": str(instance_path),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _upload(data, filename="evidence.png"):
    return FileStorage(stream=BytesIO(data), filename=filename, content_type="image/png")


def _user_and_step():
    user = User(email="qa@example.test", password="not-a-real-password")
    db.session.add(user)
    db.session.flush()
    project = Project(name="Isolated test project", user_id=user.id)
    db.session.add(project)
    db.session.flush()
    case = TestCase(title="Screenshot test", steps="step", project_id=project.id)
    db.session.add(case)
    db.session.flush()
    step = TestStep(test_case_id=case.id, position=1, action="Open page", expected_result="Page appears")
    db.session.add(step)
    db.session.flush()
    run = TestRun(status="PASS", test_case_id=case.id, user_id=user.id)
    db.session.add(run)
    db.session.flush()
    step_run = StepRun(
        test_run_id=run.id, test_step_id=step.id, status="PASS",
        step_text="Open page", expected_result="Page appears", comment="original comment"
    )
    db.session.add(step_run)
    db.session.commit()
    return user, case, step, run, step_run


def test_upload_saves_png_to_isolated_instance_and_database(app):
    with app.app_context():
        user, case, step, run, step_run = _user_and_step()
        saved = save_uploaded_screenshots([_upload(PNG_HEADER + b"test-payload")], user.id, test_step_id=step.id)
        db.session.commit()

        from app.models import TestStepScreenshot
        screenshot = TestStepScreenshot.query.one()
        assert len(saved) == 1
        assert saved[0].is_file()
        assert saved[0].parent == Path(app.instance_path) / "step-screenshots"
        assert screenshot.original_name == "evidence.png"
        assert screenshot.mime_type == "image/png"
        assert screenshot.size_bytes == len(PNG_HEADER + b"test-payload")


def test_upload_rejects_non_image_and_does_not_create_file(app):
    with app.app_context():
        user, case, step, run, step_run = _user_and_step()
        with pytest.raises(ValueError, match="Разрешены только изображения"):
            save_uploaded_screenshots([_upload(b"not an image")], user.id, test_step_id=step.id)
        assert not Path(app.instance_path, "step-screenshots").exists()


def test_upload_rejects_file_over_five_megabytes(app):
    with app.app_context():
        user, case, step, run, step_run = _user_and_step()
        too_large = PNG_HEADER + b"x" * (5 * 1024 * 1024)
        with pytest.raises(ValueError, match="5 МБ"):
            save_uploaded_screenshots([_upload(too_large)], user.id, test_step_id=step.id)


def test_upload_rejects_more_than_five_images(app):
    with app.app_context():
        user, case, step, run, step_run = _user_and_step()
        uploads = [_upload(PNG_HEADER + bytes([i])) for i in range(6)]
        with pytest.raises(ValueError, match="не более 5"):
            save_uploaded_screenshots(uploads, user.id, test_step_id=step.id)


def test_editing_steps_preserves_run_history_and_foreign_keys(app):
    with app.app_context():
        user, case, old_step, run, step_run = _user_and_step()
        old_id = old_step.id
        original_step_run_id = step_run.id

        save_test_steps(case, ["Renamed action", "Second action"], ["New expected", "Second expected"])
        db.session.commit()

        new_steps = TestStep.query.filter_by(test_case_id=case.id).order_by(TestStep.position).all()
        preserved_run = db.session.get(StepRun, original_step_run_id)
        assert len(new_steps) == 2
        assert preserved_run is not None
        assert preserved_run.test_step_id == new_steps[0].id
        assert preserved_run.test_step_id != old_id
        assert preserved_run.status == "PASS"
        assert preserved_run.comment == "original comment"
        assert preserved_run.step_text == "Open page"
        assert preserved_run.expected_result == "Page appears"
        assert TestRun.query.filter_by(id=run.id).one().status == "PASS"


def test_removing_extra_steps_keeps_old_run_linked_to_remaining_step(app):
    with app.app_context():
        user, case, first_step, run, first_step_run = _user_and_step()
        second_step = TestStep(test_case_id=case.id, position=2, action="Old second", expected_result="Old second result")
        db.session.add(second_step)
        db.session.flush()
        second_run = StepRun(
            test_run_id=run.id, test_step_id=second_step.id, status="FAIL",
            step_text="Old second", expected_result="Old second result", comment="keep this"
        )
        db.session.add(second_run)
        db.session.commit()
        second_run_id = second_run.id

        save_test_steps(case, ["Only remaining action"], ["Only remaining expected"])
        db.session.commit()

        remaining = TestStep.query.filter_by(test_case_id=case.id).one()
        preserved = db.session.get(StepRun, second_run_id)
        assert preserved is not None
        assert preserved.test_step_id == remaining.id
        assert preserved.status == "FAIL"
        assert preserved.comment == "keep this"
        assert preserved.step_text == "Old second"
        assert preserved.expected_result == "Old second result"



def test_step_reordering_keeps_historical_run_attached_to_same_logical_step(app):
    with app.app_context():
        user, case, first_step, run, first_run = _user_and_step()
        second_step = TestStep(
            test_case_id=case.id, position=2,
            action="Second logical step", expected_result="Second result"
        )
        db.session.add(second_step)
        db.session.flush()
        second_run = StepRun(
            test_run_id=run.id, test_step_id=second_step.id, status="FAIL",
            step_text="Second logical step", expected_result="Second result",
            comment="historical second"
        )
        db.session.add(second_run)
        db.session.commit()
        first_id, second_id = first_step.id, second_step.id
        first_run_id, second_run_id = first_run.id, second_run.id

        save_test_steps(
            case,
            ["Second logical step", "Open page"],
            ["Second result", "Page appears"],
            source_step_ids=[second_id, first_id],
        )
        db.session.commit()

        current_steps = TestStep.query.filter_by(test_case_id=case.id).order_by(TestStep.position).all()
        preserved_first = db.session.get(StepRun, first_run_id)
        preserved_second = db.session.get(StepRun, second_run_id)
        assert [step.action for step in current_steps] == ["Second logical step", "Open page"]
        assert preserved_second.test_step_id == current_steps[0].id
        assert preserved_first.test_step_id == current_steps[1].id
        assert preserved_first.step_text == "Open page"
        assert preserved_first.expected_result == "Page appears"
        assert preserved_second.step_text == "Second logical step"
        assert preserved_second.expected_result == "Second result"
        assert preserved_second.comment == "historical second"


def test_save_test_steps_rejects_empty_steps_without_deleting_existing_data(app):
    with app.app_context():
        user, case, old_step, run, step_run = _user_and_step()
        old_step_id = old_step.id
        with pytest.raises(ValueError, match="хотя бы один шаг"):
            save_test_steps(case, ["  ", ""], ["", ""])
        db.session.rollback()

        assert db.session.get(TestStep, old_step_id) is not None
        assert db.session.get(StepRun, step_run.id).test_step_id == old_step_id



def test_pdf_export_uses_instance_screenshot_and_contains_image(app):
    import base64
    from app.models import StepRunScreenshot

    # Valid 1x1 PNG, so ReportLab exercises the real image embedding path.
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/"
        "l1sAAAAASUVORK5CYII="
    )
    with app.app_context():
        user, case, step, run, step_run = _user_and_step()
        project = db.session.get(Project, case.project_id)
        project.name = "Проект с кириллицей"
        case.title = "Тест с изображением"
        image_path = Path(app.instance_path) / "step-screenshots" / "history.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(png)
        db.session.add(StepRunScreenshot(
            step_run_id=step_run.id,
            user_id=user.id,
            stored_name=image_path.name,
            original_name="Скриншот.png",
            mime_type="image/png",
            size_bytes=len(png),
        ))
        db.session.commit()
        user_id, project_id = user.id, project.id

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True

    response = client.get(f"/project/{project_id}/export_pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.data.startswith(b"%PDF")
    assert b"/Subtype /Image" in response.data
