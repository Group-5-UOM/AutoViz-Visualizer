"""Upload staging (Proposal §4.7).

Uploaded bytes land under ``backend/uploads/<user_id>/<uuid>.csv`` only long
enough for ``services.dataset.register_dataset`` to read them; the route then
persists the parsed rows as a Parquet blob (``storage.blobs``) and deletes the
file. Nothing durable points at this directory.

There is deliberately no TTL sweep. Deleting files on a timer left the
``datasets`` rows behind, so a dataset would keep listing while every use of it
failed. ``DELETE /datasets/{id}`` is the single deletion path.
"""

import uuid
from pathlib import Path

from autoviz.core.config import settings

# Session-isolated upload root; defaults to backend/uploads/ (settings.UPLOAD_DIR).
UPLOAD_ROOT = Path(settings.UPLOAD_DIR)


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
