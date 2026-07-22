from autoviz.services.dataset import (
    get_dataset_profile,
    get_dataset_schema,
    list_datasets,
    preview_dataset,
    register_dataset,
    unregister_dataset,
)
from tests.conftest import data_path


def test_register_iris(registry):
    result = register_dataset(data_path("general-testing", "iris.csv"), registry)
    assert result["row_count"] == 150
    assert result["column_count"] == 5
    assert result["dataset_id"].startswith("ds_")


def test_register_missing_file_is_structured_error(registry):
    result = register_dataset("no/such/file.csv", registry)
    assert "error" in result
    assert "hint" in result  # tells the caller about approved data roots


def test_register_relative_to_test_data_root(registry):
    result = register_dataset("general-testing/iris.csv", registry)
    assert result.get("row_count") == 150


def test_register_relative_to_repo_root(registry):
    result = register_dataset("test-data/general-testing/iris.csv", registry)
    assert result.get("row_count") == 150


def test_register_rejects_traversal_out_of_roots(registry):
    result = register_dataset("../.gitignore", registry)
    assert "error" in result


def test_iris_schema_types(registry, iris_id):
    schema = get_dataset_schema(iris_id, registry)
    types = {c["name"]: c["type"] for c in schema["columns"]}
    assert types["sepal_length"] == "number"
    assert types["species"] == "string"


def test_weather_date_column_detected(registry, weather_id):
    schema = get_dataset_schema(weather_id, registry)
    types = {c["name"]: c["type"] for c in schema["columns"]}
    assert types["date"] == "datetime"


def test_titanic_profile_reports_real_nulls(registry, titanic_id):
    profile = get_dataset_profile(titanic_id, registry)
    assert profile["null_counts"]["age"] > 0
    assert profile["null_counts"]["deck"] > 0
    assert profile["cardinality"]["sex"] == 2
    assert "age" in profile["summary_stats"]


def test_penguins_profile_nulls(registry):
    dataset_id = register_dataset(data_path("general-testing", "penguins.csv"), registry)["dataset_id"]
    profile = get_dataset_profile(dataset_id, registry)
    assert any(count > 0 for count in profile["null_counts"].values())


def test_preview_limit_and_nan_sanitization(registry, titanic_id):
    preview = preview_dataset(titanic_id, limit=5, registry=registry)
    assert len(preview["rows"]) == 5
    # Titanic has NaN ages in early rows across the file; every value must be JSON-safe.
    for row in preview["rows"]:
        for value in row.values():
            assert value is None or isinstance(value, (str, int, float, bool))


def test_preview_unknown_dataset(registry):
    assert "error" in preview_dataset("ds_nope", registry=registry)


def test_list_datasets_reflects_registrations(registry, iris_id, titanic_id):
    listing = list_datasets(registry)["datasets"]
    ids = {d["dataset_id"] for d in listing}
    assert {iris_id, titanic_id} <= ids
    iris_entry = next(d for d in listing if d["dataset_id"] == iris_id)
    assert iris_entry["row_count"] == 150
    assert iris_entry["source"].endswith("iris.csv")


def test_unregister_dataset_removes_it(registry, iris_id):
    assert unregister_dataset(iris_id, registry)["removed"] is True
    assert "error" in get_dataset_schema(iris_id, registry)
    assert "error" in unregister_dataset(iris_id, registry)
