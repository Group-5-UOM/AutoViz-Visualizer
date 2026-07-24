"""Session-isolated upload storage (Proposal §4.7).

Each user's uploads live under ``backend/uploads/<user_id>/<uuid>.csv``. A
best-effort TTL sweep removes stale session directories on demand. The absolute
saved path is handed to ``services.dataset.register_dataset`` (absolute paths are
accepted and bypass the data-root restriction), and recorded in ``DatasetMeta``.
"""

import os
import shutil
import time
import uuid
from pathlib import Path

from autoviz.core.config import settings

# Session-isolated upload root; defaults to backend/uploads/ (settings.UPLOAD_DIR).
UPLOAD_ROOT = Path(settings.UPLOAD_DIR)


def _ttl_hours() -> float:
    try:
        value = float(os.environ.get("AUTOVIZ_UPLOAD_TTL_HOURS", "24"))
    except ValueError:
        return 24.0
    return value if value > 0 else 24.0


def session_dir(owner_id: str) -> Path:
    path = UPLOAD_ROOT / owner_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(owner_id: str, filename: str, data: bytes) -> Path:
    """Persist uploaded bytes under the owner's session dir and return the path."""
    suffix = Path(filename or "").suffix or ".csv"
    dest = session_dir(owner_id) / f"{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(data)
    return dest


def sweep_stale(now: float | None = None) -> list[str]:
    """Delete upload dirs older than the TTL. Returns the owner_ids swept.

    Best-effort — filesystem errors are ignored. Returns the affected owner_ids
    so the caller can cascade DatasetMeta / registry cleanup if desired.
    """
    now = now if now is not None else time.time()
    cutoff = now - _ttl_hours() * 3600
    swept: list[str] = []
    if not UPLOAD_ROOT.exists():
        return swept
    for child in UPLOAD_ROOT.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                swept.append(child.name)
        except OSError:
            continue
    return swept
