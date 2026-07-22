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
    """Upload a dataset (CSV or Parquet) and get a `dataset_id` to
    reference in audit requests.

    **Trying it out?** Download one of ITACA's example datasets and
    upload it here — their column names match the examples in
    `POST /audits`:

    - [example_training_binary_2.csv](https://raw.githubusercontent.com/Eticas-AI/itaca/main/files/example_training_binary_2.csv)
      — for **labeled** audits (and the *dev* side of **drift**)
    - [example_operational_binary_2.csv](https://raw.githubusercontent.com/Eticas-AI/itaca/main/files/example_operational_binary_2.csv)
      — for **production** audits (and the *prod* side of **drift**)
    - [example_impact_binary_2.csv](https://raw.githubusercontent.com/Eticas-AI/itaca/main/files/example_impact_binary_2.csv)
      — for **impacted** audits

    The response echoes the detected columns, so you can verify the
    dataset before launching an audit. Note: `.pkl` files are rejected
    by design (unpickling uploads is a code-execution risk); convert to
    CSV or Parquet first.
    """
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
