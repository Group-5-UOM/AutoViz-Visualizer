from pathlib import Path

import pytest

from autoviz.services.dataset import register_dataset
from autoviz.services.registry import DatasetRegistry

# Repo root / test-data (conftest lives at backend/tests/).
TEST_DATA = Path(__file__).parent.parent.parent / "test-data"


def data_path(*parts: str) -> str:
    return str(TEST_DATA.joinpath(*parts))


@pytest.fixture()
def registry() -> DatasetRegistry:
    return DatasetRegistry()


@pytest.fixture()
def api_db(tmp_path, monkeypatch):
    """Point the storage layer at a throwaway SQLite file and create the schema.

    Portable models mean this is the same schema as the deployment Postgres, so
    the API test suites run fully offline with no database server.
    """
    from autoviz.core import database as db
    from autoviz.storage import uploads

    url = f"sqlite:///{tmp_path.as_posix()}/api_test.db"
    monkeypatch.setenv("DATABASE_URL", url)
    # Keep uploaded files out of the repo's backend/uploads during tests.
    monkeypatch.setattr(uploads, "UPLOAD_ROOT", tmp_path / "uploads")
    db.reset_engine()
    db.init_db()
    yield
    db.reset_engine()


@pytest.fixture()
def iris_id(registry: DatasetRegistry) -> str:
    return register_dataset(data_path("general-testing", "iris.csv"), registry)["dataset_id"]


@pytest.fixture()
def titanic_id(registry: DatasetRegistry) -> str:
    return register_dataset(data_path("general-testing", "titanic.csv"), registry)["dataset_id"]


@pytest.fixture()
def weather_id(registry: DatasetRegistry) -> str:
    return register_dataset(data_path("weather-climate", "seattle-weather.csv"), registry)["dataset_id"]


@pytest.fixture()
def diamonds_id(registry: DatasetRegistry) -> str:
    return register_dataset(data_path("sales-retail", "diamonds.csv"), registry)["dataset_id"]


# Controlled dataset with KNOWN null/duplicate counts, so preprocessing tests assert
# exact effects (R9 — never hardcode counts against a dataset we didn't author).
#   10 rows. cls nulls=1 (idx3); fare nulls=3 (idx1,4,7 -> 30%); age nulls=2 (idx2,6).
#   drop_nulls(["cls","fare"], how="any") removes idx{1,3,4,7} = 4 rows (40% -> gates).
#   median(age) over all rows = 5.5 (of [1,2,4,5,6,8,9,10]); mode(cls) ties a/b -> "a".
#   No exact-duplicate rows.
NULLS_CSV = (
    "cls,fare,age\n"
    "a,10,1\n"
    "a,,2\n"
    "b,20,\n"
    ",30,4\n"
    "a,,5\n"
    "b,20,6\n"
    "a,40,\n"
    "b,,8\n"
    "a,10,9\n"
    "b,20,10\n"
)


@pytest.fixture()
def nulls_csv_path(tmp_path) -> str:
    p = tmp_path / "nulls.csv"
    p.write_text(NULLS_CSV)
    return str(p)


@pytest.fixture()
def nulls_id(registry: DatasetRegistry, nulls_csv_path: str) -> str:
    return register_dataset(nulls_csv_path, registry)["dataset_id"]
