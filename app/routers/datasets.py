"""Dataset management endpoints.

Datasets are uploaded as multipart files (CSV or Parquet), stored under
``DATA_DIR`` and referenced by ``dataset_id`` in audit requests. The
underlying library reads datasets from local file paths, so the upload
step is what bridges HTTP clients to the library's file-based interface.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from ..auth import require_auth
from ..config import get_settings
from ..schemas import DatasetInfo
from ..services.storage import DatasetStorage

router = APIRouter(prefix="/datasets", tags=["datasets"])


def get_dataset_storage() -> DatasetStorage:
    return DatasetStorage()


@router.post("", response_model=DatasetInfo,
             status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    file: UploadFile,
    storage: DatasetStorage = Depends(get_dataset_storage),
    _claims: dict = Depends(require_auth),
) -> DatasetInfo:
    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds MAX_UPLOAD_MB={settings.max_upload_mb}",
        )
    try:
        meta = storage.save(file.filename or "dataset", content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    return DatasetInfo(**{k: v for k, v in meta.items() if k != "path"})


@router.get("", response_model=list[DatasetInfo])
def list_datasets(
    storage: DatasetStorage = Depends(get_dataset_storage),
    _claims: dict = Depends(require_auth),
) -> list[DatasetInfo]:
    return [
        DatasetInfo(**{k: v for k, v in m.items() if k != "path"})
        for m in storage.list()
    ]


@router.get("/{dataset_id}", response_model=DatasetInfo)
def get_dataset(
    dataset_id: str,
    storage: DatasetStorage = Depends(get_dataset_storage),
    _claims: dict = Depends(require_auth),
) -> DatasetInfo:
    meta = storage.get_meta(dataset_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return DatasetInfo(**{k: v for k, v in meta.items() if k != "path"})


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    dataset_id: str,
    storage: DatasetStorage = Depends(get_dataset_storage),
    _claims: dict = Depends(require_auth),
) -> None:
    if not storage.delete(dataset_id):
        raise HTTPException(status_code=404, detail="Dataset not found")
