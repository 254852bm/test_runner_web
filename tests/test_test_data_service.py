import pytest

from app import create_app, db
from app.models import (
    Project, TestCase, TestDataColumn, TestDataRow, TestDataSet,
    TestStep, User,
)
from app.test_data import prepare_test_data


@pytest.fixture()
def app(tmp_path):
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    database_path = tmp_path / "parameterization-service.sqlite"
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


def _objects():
    user = User(email="service@example.test", password="not-a-real-password")
    db.session.add(user)
    db.session.flush()
    project = Project(name="Service project", user_id=user.id)
    db.session.add(project)
    db.session.flush()
    case = TestCase(
        title="Parameterized login",
        precondition="Open {{base_url}}",
        steps="Enter {{login}}",
        expected_result="",
        project_id=project.id,
    )
    db.session.add(case)
    db.session.flush()
    step = TestStep(
        test_case_id=case.id, position=1,
        action="Enter {{login}} and {{pin_code}}",
        expected_result="See {{expected_message}}",
    )
    db.session.add(step)
    db.session.flush()
    dataset = TestDataSet(test_case_id=case.id, name="Login data")
    db.session.add(dataset)
    db.session.flush()
    columns = [
        TestDataColumn(dataset_id=dataset.id, key=key, label=key, position=index)
        for index, key in enumerate(
            ["base_url", "login", "pin_code", "expected_message"]
        )
    ]
    db.session.add_all(columns)
    db.session.flush()
    row = TestDataRow(
        dataset_id=dataset.id,
        name="Valid account",
        values_json={
            "base_url": "https://example.test",
            "login": "qa@example.test",
            "pin_code": "sample-pin-code",
            "expected_message": "Welcome",
        },
    )
    db.session.add(row)
    db.session.commit()
    return case, dataset, row, columns


def test_prepare_test_data_substitutes_precondition_action_and_expected_result(app):
    with app.app_context():
        case, dataset, row, columns = _objects()
        result = prepare_test_data(case, dataset, row)

        assert result["precondition"] == "Open https://example.test"
        assert result["steps"][0]["action"] == (
            "Enter qa@example.test and sample-pin-code"
        )
        assert result["steps"][0]["expected_result"] == "See Welcome"
        assert result["values_snapshot"]["login"] == "qa@example.test"
        assert result["dataset_name_snapshot"] == "Login data"
        assert result["row_name_snapshot"] == "Valid account"


def test_prepare_test_data_rejects_unknown_placeholder(app):
    with app.app_context():
        case, dataset, row, columns = _objects()
        case.precondition = "Open {{missing_variable}}"
        with pytest.raises(ValueError, match="неизвестные переменные"):
            prepare_test_data(case, dataset, row)


def test_prepare_test_data_rejects_missing_used_value(app):
    with app.app_context():
        case, dataset, row, columns = _objects()
        row.values_json = dict(row.values_json, login="")
        with pytest.raises(ValueError, match="Не заполнены значения"):
            prepare_test_data(case, dataset, row)


def test_prepare_test_data_rejects_dataset_from_another_test_case(app):
    with app.app_context():
        case, dataset, row, columns = _objects()
        other_case = TestCase(
            title="Other", steps="other", project_id=case.project_id
        )
        db.session.add(other_case)
        db.session.commit()
        with pytest.raises(ValueError, match="не относится к выбранному тест-кейсу"):
            prepare_test_data(other_case, dataset, row)


def test_prepare_test_data_rejects_row_from_another_dataset(app):
    with app.app_context():
        case, dataset, row, columns = _objects()
        other_dataset = TestDataSet(test_case_id=case.id, name="Other data")
        db.session.add(other_dataset)
        db.session.flush()
        other_row = TestDataRow(
            dataset_id=other_dataset.id, name="Foreign row", values_json={}
        )
        db.session.add(other_row)
        db.session.commit()
        with pytest.raises(ValueError, match="не относится к выбранному набору"):
            prepare_test_data(case, dataset, other_row)


def test_prepare_test_data_refuses_secret_columns_until_encryption_is_available(app):
    with app.app_context():
        case, dataset, row, columns = _objects()
        columns[2].is_secret = True
        db.session.commit()
        with pytest.raises(ValueError, match="секретные поля"):
            prepare_test_data(case, dataset, row)


def test_prepare_test_data_does_not_evaluate_template_expressions(app):
    with app.app_context():
        case, dataset, row, columns = _objects()
        row.values_json = dict(
            row.values_json,
            login="<script>alert(1)</script>",
        )
        db.session.commit()
        result = prepare_test_data(case, dataset, row)
        assert result["steps"][0]["action"] == (
            "Enter <script>alert(1)</script> and sample-pin-code"
        )


def test_prepare_test_data_rejects_malformed_placeholder(app):
    with app.app_context():
        case, dataset, row, columns = _objects()
        case.precondition = "Open {{base url}}"
        with pytest.raises(ValueError, match="Некорректный формат переменной"):
            prepare_test_data(case, dataset, row)


def test_deleting_test_case_cascades_its_data_sets_and_rows(app):
    with app.app_context():
        case, dataset, row, columns = _objects()
        case_id, dataset_id, row_id = case.id, dataset.id, row.id
        db.session.delete(case)
        db.session.commit()
        assert db.session.get(TestDataSet, dataset_id) is None
        assert db.session.get(TestDataRow, row_id) is None


def test_prepare_test_data_rejects_password_like_column_name(app):
    with app.app_context():
        case, dataset, row, columns = _objects()
        columns[2].key = "password"
        values = dict(row.values_json)
        values.pop("pin_code", None)
        values["password"] = "plain-text-password"
        row.values_json = values
        db.session.commit()
        with pytest.raises(ValueError, match="секретные поля"):
            prepare_test_data(case, dataset, row)
