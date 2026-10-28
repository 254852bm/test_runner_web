from io import BytesIO
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from app import create_app, db
from app.models import Project, TestCase, TestCaseVersion, TestRun, TestStep, TestStepScreenshot, StepRunScreenshot, StepRun, User
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



def test_history_page_renders_historical_step_snapshots_after_current_steps_change(app):
    with app.app_context():
        user, case, old_step, run, step_run = _user_and_step()
        project = db.session.get(Project, case.project_id)
        user_id, project_id = user.id, project.id
        old_run_id = run.id
        old_step_run_id = step_run.id

        save_test_steps(
            case, ["Completely new current action"], ["Completely new current expectation"]
        )
        db.session.commit()

        # Ensure the stored run snapshot is still the original record.
        saved_run_step = db.session.get(StepRun, old_step_run_id)
        assert saved_run_step.step_text == "Open page"
        assert saved_run_step.expected_result == "Page appears"
        assert saved_run_step.comment == "original comment"

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True

    response = client.get(f"/project/{project_id}/history")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f"Прогон #{old_run_id}" in html
    assert "Open page" in html
    assert "Page appears" in html
    assert "original comment" in html
    assert "Completely new current action" not in html
    assert "Completely new current expectation" not in html



def test_edit_route_keeps_screenshots_with_original_steps_when_reordered(app):
    with app.app_context():
        user, case, first_step, run, first_run = _user_and_step()
        second_step = TestStep(
            test_case_id=case.id, position=2,
            action="Second logical step", expected_result="Second result"
        )
        db.session.add(second_step)
        db.session.flush()
        upload_dir = Path(app.instance_path) / "step-screenshots"
        upload_dir.mkdir(parents=True, exist_ok=True)
        first_file = upload_dir / "first.png"
        second_file = upload_dir / "second.png"
        first_file.write_bytes(PNG_HEADER + b"first")
        second_file.write_bytes(PNG_HEADER + b"second")
        db.session.add_all([
            TestStepScreenshot(
                test_step_id=first_step.id, user_id=user.id, stored_name=first_file.name,
                original_name="first.png", mime_type="image/png", size_bytes=10
            ),
            TestStepScreenshot(
                test_step_id=second_step.id, user_id=user.id, stored_name=second_file.name,
                original_name="second.png", mime_type="image/png", size_bytes=11
            )
        ])
        db.session.commit()
        user_id, project_id, case_id = user.id, case.project_id, case.id
        first_id, second_id = first_step.id, second_step.id

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True

    response = client.post(
        f"/project/{project_id}/test/{case_id}/edit",
        data={
            "title": "Screenshot identity test",
            "precondition": "",
            "step_id[]": [str(second_id), str(first_id)],
            "step_action[]": ["Second logical step", "Open page"],
            "step_expected[]": ["Second result", "Page appears"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        current_steps = TestStep.query.filter_by(test_case_id=case_id).order_by(TestStep.position).all()
        screenshots = {
            screenshot.original_name: screenshot.test_step.action
            for step in current_steps for screenshot in step.screenshots
        }
        assert screenshots == {
            "second.png": "Second logical step",
            "first.png": "Open page",
        }
        current_files = {path.name for path in upload_dir.iterdir()}
        assert first_file.name not in current_files
        assert second_file.name not in current_files
        assert len(current_files) == 2



def _login(client, user_id):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def test_create_test_route_saves_step_and_expected_result(app):
    with app.app_context():
        user, case, step, run, step_run = _user_and_step()
        project_id, user_id = case.project_id, user.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/create_test",
        data={
            "title": "New test case",
            "precondition": "User is logged in",
            "step_action[]": ["Click Save"],
            "step_expected[]": ["Success message is shown"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        created = TestCase.query.filter_by(project_id=project_id, title="New test case").one()
        created_step = TestStep.query.filter_by(test_case_id=created.id).one()
        assert created_step.action == "Click Save"
        assert created_step.expected_result == "Success message is shown"
        assert created.precondition == "User is logged in"


def test_user_cannot_edit_another_users_test_case(app):
    with app.app_context():
        owner, case, step, run, step_run = _user_and_step()
        other_user = User(email="other@example.test", password="not-a-real-password")
        db.session.add(other_user)
        db.session.commit()
        owner_project_id, case_id, other_user_id = case.project_id, case.id, other_user.id

    client = app.test_client()
    _login(client, other_user_id)
    response = client.post(
        f"/project/{owner_project_id}/test/{case_id}/edit",
        data={
            "title": "Unauthorized edit",
            "step_id[]": ["1"],
            "step_action[]": ["Changed"],
            "step_expected[]": ["Changed"],
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 403, 404)

    with app.app_context():
        saved = db.session.get(TestCase, case_id)
        assert saved.title == "Screenshot test"
        assert TestStep.query.filter_by(test_case_id=case_id).one().action == "Open page"



def test_user_cannot_fetch_another_users_run_screenshot(app):
    with app.app_context():
        owner, case, step, run, step_run = _user_and_step()
        saved_path = save_uploaded_screenshots(
            [_upload(PNG_HEADER + b"private-run-image")],
            owner.id,
            step_run_id=step_run.id,
        )[0]
        db.session.commit()
        screenshot = StepRunScreenshot.query.one()
        screenshot_id = screenshot.id
        other_user = User(email="viewer@example.test", password="not-a-real-password")
        db.session.add(other_user)
        db.session.commit()
        other_user_id = other_user.id
        assert saved_path.is_file()

    client = app.test_client()
    _login(client, other_user_id)
    response = client.get(f"/screenshots/{screenshot_id}")
    assert response.status_code == 404


def test_delete_test_route_removes_related_screenshot_records_and_files_only(app):
    with app.app_context():
        user, case, step, run, step_run = _user_and_step()
        test_step_file = save_uploaded_screenshots(
            [_upload(PNG_HEADER + b"test-step-image")],
            user.id,
            test_step_id=step.id,
        )[0]
        run_file = save_uploaded_screenshots(
            [_upload(PNG_HEADER + b"step-run-image")],
            user.id,
            step_run_id=step_run.id,
        )[0]
        project_id, case_id, user_id = case.project_id, case.id, user.id
        run_id = run.id

        other_case = TestCase(
            title="Keep this case", steps="keep", project_id=project_id
        )
        db.session.add(other_case)
        db.session.flush()
        other_step = TestStep(
            test_case_id=other_case.id,
            position=1,
            action="Keep step",
            expected_result="Keep result",
        )
        db.session.add(other_step)
        db.session.flush()
        other_file = save_uploaded_screenshots(
            [_upload(PNG_HEADER + b"other-case-image")],
            user.id,
            test_step_id=other_step.id,
        )[0]
        other_case_id = other_case.id
        db.session.commit()

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/test/{case_id}/delete",
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        assert db.session.get(TestCase, case_id) is None
        assert db.session.get(TestRun, run_id) is None
        assert TestStepScreenshot.query.filter_by(stored_name=test_step_file.name).count() == 0
        assert StepRunScreenshot.query.filter_by(stored_name=run_file.name).count() == 0
        assert not test_step_file.exists()
        assert not run_file.exists()

        assert db.session.get(TestCase, other_case_id) is not None
        assert TestStepScreenshot.query.filter_by(stored_name=other_file.name).count() == 1
        assert other_file.is_file()




def test_delete_project_route_removes_related_screenshot_records_and_files_only(app):
    with app.app_context():
        user, case, step, run, step_run = _user_and_step()
        test_step_file = save_uploaded_screenshots(
            [_upload(PNG_HEADER + b"project-test-step-image")],
            user.id,
            test_step_id=step.id,
        )[0]
        run_file = save_uploaded_screenshots(
            [_upload(PNG_HEADER + b"project-run-image")],
            user.id,
            step_run_id=step_run.id,
        )[0]
        project_id = case.project_id
        case_id = case.id
        user_id = user.id

        other_project = Project(name="Keep this project", user_id=user.id)
        db.session.add(other_project)
        db.session.flush()
        other_case = TestCase(
            title="Keep this case", steps="keep", project_id=other_project.id
        )
        db.session.add(other_case)
        db.session.flush()
        other_step = TestStep(
            test_case_id=other_case.id,
            position=1,
            action="Keep step",
            expected_result="Keep result",
        )
        db.session.add(other_step)
        db.session.flush()
        other_file = save_uploaded_screenshots(
            [_upload(PNG_HEADER + b"other-project-image")],
            user.id,
            test_step_id=other_step.id,
        )[0]
        other_project_id = other_project.id
        other_case_id = other_case.id
        db.session.commit()

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/delete",
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        assert db.session.get(Project, project_id) is None
        assert db.session.get(TestCase, case_id) is None
        assert TestStepScreenshot.query.filter_by(stored_name=test_step_file.name).count() == 0
        assert StepRunScreenshot.query.filter_by(stored_name=run_file.name).count() == 0
        assert not test_step_file.exists()
        assert not run_file.exists()

        assert db.session.get(Project, other_project_id) is not None
        assert db.session.get(TestCase, other_case_id) is not None
        assert TestStepScreenshot.query.filter_by(stored_name=other_file.name).count() == 1
        assert other_file.is_file()


def test_run_is_linked_to_the_test_case_version_used(app):
    with app.app_context():
        user, case, step, old_run, old_step_run = _user_and_step()
        project_id = case.project_id
        case_id = case.id
        user_id = user.id

        # This fixture's pre-existing run models legacy data without a version link.
        assert old_run.version_id is None

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        f"/project/{project_id}/run?test_id={case_id}",
        data={
            "step_status[]": ["PASS"],
            "step_comment[]": ["Run against current version"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        version = TestCaseVersion.query.filter_by(
            test_case_id=case_id
        ).order_by(TestCaseVersion.version_number.desc()).first()
        assert version is not None
        saved_run = TestRun.query.filter_by(
            test_case_id=case_id,
            user_id=user_id,
        ).order_by(TestRun.id.desc()).first()
        assert saved_run is not None
        assert saved_run.version_id == version.id
        assert saved_run.version.version_number == 1
