from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from app import create_app, db
from app.models import Project, TestCase, TestStep, TestStepScreenshot, User
from app.routes import save_uploaded_screenshots


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
    db.session.commit()
    return user, step


def test_upload_saves_png_to_isolated_instance_and_database(app):
    with app.app_context():
        user, step = _user_and_step()
        saved = save_uploaded_screenshots([_upload(PNG_HEADER + b"test-payload")], user.id, test_step_id=step.id)
        db.session.commit()

        screenshot = TestStepScreenshot.query.one()
        assert len(saved) == 1
        assert saved[0].is_file()
        assert saved[0].parent == (app.instance_path and __import__("pathlib").Path(app.instance_path) / "step-screenshots")
        assert screenshot.original_name == "evidence.png"
        assert screenshot.mime_type == "image/png"
        assert screenshot.size_bytes == len(PNG_HEADER + b"test-payload")


def test_upload_rejects_non_image_and_does_not_create_file(app):
    with app.app_context():
        user, step = _user_and_step()
        with pytest.raises(ValueError, match="Разрешены только изображения"):
            save_uploaded_screenshots([_upload(b"not an image")], user.id, test_step_id=step.id)
        assert TestStepScreenshot.query.count() == 0
        upload_dir = __import__("pathlib").Path(app.instance_path) / "step-screenshots"
        assert not upload_dir.exists()


def test_upload_rejects_file_over_five_megabytes(app):
    with app.app_context():
        user, step = _user_and_step()
        too_large = PNG_HEADER + b"x" * (5 * 1024 * 1024)
        with pytest.raises(ValueError, match="5 МБ"):
            save_uploaded_screenshots([_upload(too_large)], user.id, test_step_id=step.id)
        assert TestStepScreenshot.query.count() == 0


def test_upload_rejects_more_than_five_images(app):
    with app.app_context():
        user, step = _user_and_step()
        uploads = [_upload(PNG_HEADER + bytes([i])) for i in range(6)]
        with pytest.raises(ValueError, match="не более 5"):
            save_uploaded_screenshots(uploads, user.id, test_step_id=step.id)
        assert TestStepScreenshot.query.count() == 0
