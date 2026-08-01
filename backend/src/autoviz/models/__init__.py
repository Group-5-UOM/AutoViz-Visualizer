"""SQLAlchemy ORM models — import all models here so Alembic sees them."""

from autoviz.core.database import Base  # noqa: F401
from autoviz.models.user import User  # noqa: F401
from autoviz.models.session import UserSession  # noqa: F401
from autoviz.models.oauth_account import OAuthAccount  # noqa: F401
from autoviz.models.password_reset import PasswordResetToken  # noqa: F401
from autoviz.models.dataset import UserDataset  # noqa: F401
from autoviz.models.dataset_blob import DatasetBlob  # noqa: F401
from autoviz.models.chart import SavedChart  # noqa: F401
from autoviz.models.dashboard import Dashboard, DashboardWidget  # noqa: F401

__all__ = [
    "Base",
    "User",
    "UserSession",
    "OAuthAccount",
    "PasswordResetToken",
    "UserDataset",
    "DatasetBlob",
    "SavedChart",
    "Dashboard",
    "DashboardWidget",
]
