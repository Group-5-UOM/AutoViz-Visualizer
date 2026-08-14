"""Dataset routes — thin adapters over services.dataset, scoped to the
authenticated user (MCP tools 1-6 plus a multipart upload the frontend needs).

    POST   /datasets/upload               multipart CSV -> session dir -> register (owned)
    POST   /datasets                       register by file_ref (owned)
    GET    /datasets                       list the caller's datasets
    DELETE /datasets/{dataset_id}          unregister + delete file (owner only)
    GET    /datasets/{dataset_id}/schema   column schema
    GET    /datasets/{dataset_id}/profile  profile
    GET    /datasets/{dataset_id}/preview  first rows (limit)
    POST   /datasets/{dataset_id}/cleaned  apply a cleaning block, keep the result (owned)

Ownership is enforced on every id: a caller can only see/act on their own
datasets (403 otherwise, 404 for an unknown id).
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from autoviz.api.deps import get_current_user, get_db, get_registry
from autoviz.api.errors import respond
from autoviz.models import User
from autoviz.services import dataset as dataset_service
from autoviz.services import execution
from autoviz.services.registry import DatasetRegistry
from autoviz.storage import blobs, repository, uploads

router = APIRouter()


class RegisterRequest(BaseModel):
    file_ref: str


def _persist(
    db: Session,
    user: User,
    res: dict,
    filename: str,
    file_path: str,
    registry: DatasetRegistry,
):
    """Record the metadata and persist the dataset itself.

    The Parquet blob is what makes the dataset durable — the file on disk is only
    the staging area ``register_dataset`` read from. Metadata is written first so
    the blob's FK to ``datasets.dataset_id`` resolves.
    """
    repository.add_dataset_meta(
        db,
        dataset_id=res["dataset_id"],
        user_id=user.id,
        filename=filename,
        file_path=file_path,
        row_count=res["row_count"],
        column_count=res["column_count"],
    )
    record = registry.get(res["dataset_id"])
    if record is not None:
        blobs.store(db, record, source=filename)
    return {**res, "logical_name": filename}


@router.post("/upload", status_code=201)
async def upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: DatasetRegistry = Depends(get_registry),
):
    data = await file.read()
    path = uploads.save_upload(user.id, file.filename or "upload.csv", data)
    res = dataset_service.register_dataset(str(path), registry)
    if "error" in res:  # e.g. RESOURCE_LIMIT (413) or unreadable CSV (400)
        path.unlink(missing_ok=True)
        return respond(res)
    body = _persist(db, user, res, file.filename or path.name, str(path), registry)
    # The rows now live in the database; the staged CSV has served its purpose.
    # Nothing durable references it, so the API no longer depends on local disk.
    path.unlink(missing_ok=True)
    return respond(body, ok_status=201)


@router.post("", status_code=201)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: DatasetRegistry = Depends(get_registry),
):
    res = dataset_service.register_dataset(body.file_ref, registry)
    if "error" in res:
        return respond(res)
    logical = body.file_ref.replace("\\", "/").rsplit("/", 1)[-1]
    # The source file belongs to the caller, not to us — persist a copy as a blob
    # but leave the file itself alone.
    return respond(
        _persist(db, user, res, logical, body.file_ref, registry), ok_status=201
    )


@router.get("")
def list_datasets(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "datasets": [
            {
                "dataset_id": m.dataset_id,
                "logical_name": m.filename,
                "row_count": m.row_count,
                "column_count": m.column_count,
                "created_at": m.created_at.isoformat(),
            }
            for m in repository.list_dataset_meta(db, user.id)
        ]
    }


class MaterializeRequest(BaseModel):
    preprocessing: list[dict]
    # Echo back confirmation.preprocessing_hash to approve a large row removal.
    approved_preprocessing_hash: str | None = None


@router.post("/{dataset_id}/cleaned", status_code=201)
def materialize_cleaned(
    dataset_id: str,
    body: MaterializeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: DatasetRegistry = Depends(get_registry),
):
    """Apply a cleaning block once and keep the result as a dataset of its own.

    The cleaned copy is persisted like any upload rather than left in the
    in-memory registry: it is a dataset the user now owns and will come back to,
    and a derived frame that vanished on eviction would be worse than one that
    was never offered. The parent is untouched.
    """
    _resolve(db, registry, dataset_id, user)  # ownership + lazy reload
    res = execution.materialize_cleaned_dataset(
        dataset_id,
        body.preprocessing,
        registry,
        approved_preprocessing_hash=body.approved_preprocessing_hash,
    )
    if "error" in res:
        return respond(res)
    parent = _owned_meta(db, dataset_id, user)
    name = f"{parent.filename} (cleaned {res['version_id']})"
    return respond(
        _persist(db, user, res, name, "", registry) | {"parent_id": dataset_id,
                                                       "version_id": res["version_id"]},
        ok_status=201,
    )


class ApplyRecipeRequest(BaseModel):
    # A dataset produced by POST /datasets/{id}/cleaned — its stored lineage is
    # the recipe.
    recipe_dataset_id: str
    approved_preprocessing_hash: str | None = None


@router.post("/{dataset_id}/apply-recipe", status_code=201)
def apply_recipe(
    dataset_id: str,
    body: ApplyRecipeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: DatasetRegistry = Depends(get_registry),
):
    """Clean this dataset the same way an earlier one was cleaned.

    Both ids are ownership-checked: a recipe is derived from someone's data and
    reveals its column names, so reading one is as privileged as reading the
    dataset it came from.
    """
    _resolve(db, registry, dataset_id, user)
    _resolve(db, registry, body.recipe_dataset_id, user)
    res = execution.apply_cleaning_recipe(
        body.recipe_dataset_id,
        dataset_id,
        registry,
        approved_preprocessing_hash=body.approved_preprocessing_hash,
    )
    if "error" in res:
        return respond(res)
    parent = _owned_meta(db, dataset_id, user)
    name = f"{parent.filename} (cleaned {res['version_id']})"
    return respond(
        _persist(db, user, res, name, "", registry)
        | {"parent_id": dataset_id, "version_id": res["version_id"],
           "recipe_from": res["recipe_from"]},
        ok_status=201,
    )


def _owned_meta(db: Session, dataset_id: str, user: User):
    meta = repository.get_dataset_meta(db, dataset_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown dataset_id: {dataset_id}")
    if meta.user_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this dataset")
    return meta


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: DatasetRegistry = Depends(get_registry),
):
    meta = _owned_meta(db, dataset_id, user)
    registry.remove(dataset_id)
    # Deletion is now the only way a dataset goes away, so it has to clear every
    # copy: the cached frame, the stored rows, any staged file, then the metadata.
    blobs.delete(db, dataset_id)
    if meta.file_path:
        from pathlib import Path

        Path(meta.file_path).unlink(missing_ok=True)
    repository.delete_dataset_meta(db, dataset_id)
    return {"removed": True, "dataset_id": dataset_id}


def _resolve(db: Session, registry: DatasetRegistry, dataset_id: str, user: User):
    """Ownership + lazy reload; raises the right HTTP error, or returns the record."""
    record, error = repository.resolve_dataset(db, registry, dataset_id, user.id)
    if error is not None:
        status = 403 if error.get("error_code") == repository.FORBIDDEN else 404
        raise HTTPException(status_code=status, detail=error["error"])
    return record


@router.get("/{dataset_id}/schema")
def schema(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: DatasetRegistry = Depends(get_registry),
):
    _resolve(db, registry, dataset_id, user)
    return respond(dataset_service.get_dataset_schema(dataset_id, registry))


@router.get("/{dataset_id}/profile")
def profile(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: DatasetRegistry = Depends(get_registry),
):
    _resolve(db, registry, dataset_id, user)
    return respond(dataset_service.get_dataset_profile(dataset_id, registry))


@router.get("/{dataset_id}/preview")
def preview(
    dataset_id: str,
    limit: int = 10,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    registry: DatasetRegistry = Depends(get_registry),
):
    _resolve(db, registry, dataset_id, user)
    return respond(dataset_service.preview_dataset(dataset_id, limit, registry))
