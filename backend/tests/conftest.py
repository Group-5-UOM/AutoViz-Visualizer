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
