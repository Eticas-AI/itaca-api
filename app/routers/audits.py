"""Audit endpoints — asynchronous job pattern.

``POST /audits`` validates the request, persists a ``pending`` record and
schedules execution as a background task, returning ``202`` with the
``audit_id``. Clients poll ``GET /audits/{id}`` until ``status`` is
``completed`` (or ``failed``) and then fetch
``GET /audits/{id}/results``.

Rationale: audits over large datasets can outlive typical reverse-proxy
timeouts in the shared deployment, so a synchronous endpoint would be
fragile. ``BackgroundTasks`` is sufficient for the expected volume; if a
real queue is ever needed, the HTTP contract stays the same.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from ..auth import require_auth
from ..schemas import AuditCreated, AuditRecord, AuditRequest
from ..services.audit_runner import (
    AuditValidationError,
    run_audit_job,
    validate_request,
)
from ..services.storage import AuditStorage, DatasetStorage

router = APIRouter(prefix="/audits", tags=["audits"])


def get_audit_storage() -> AuditStorage:
    return AuditStorage()


def get_dataset_storage() -> DatasetStorage:
    return DatasetStorage()


@router.post("", response_model=AuditCreated,
             status_code=status.HTTP_202_ACCEPTED)
def create_audit(
    request: AuditRequest,
    background: BackgroundTasks,
    audits: AuditStorage = Depends(get_audit_storage),
    datasets: DatasetStorage = Depends(get_dataset_storage),
    _claims: dict = Depends(require_auth),
) -> AuditCreated:
    payload = request.model_dump(mode="json")
    try:
        validate_request(payload, datasets)
    except AuditValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    record = audits.create(payload)
    background.add_task(
        run_audit_job, record["audit_id"], payload, audits, datasets
    )
    return AuditCreated(audit_id=record["audit_id"], status=record["status"])


@router.get("", response_model=list[AuditRecord])
def list_audits(
    audits: AuditStorage = Depends(get_audit_storage),
    _claims: dict = Depends(require_auth),
) -> list[AuditRecord]:
    return [AuditRecord(**r) for r in audits.list()]


@router.get("/{audit_id}", response_model=AuditRecord)
def get_audit(
    audit_id: str,
    audits: AuditStorage = Depends(get_audit_storage),
    _claims: dict = Depends(require_auth),
) -> AuditRecord:
    record = audits.get(audit_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Audit not found")
    return AuditRecord(**record)


@router.get("/{audit_id}/results")
def get_audit_results(
    audit_id: str,
    normalized: bool = True,
    audits: AuditStorage = Depends(get_audit_storage),
    _claims: dict = Depends(require_auth),
) -> dict:
    record = audits.get(audit_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Audit not found")
    if record["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Audit status is '{record['status']}', not 'completed'",
        )
    results = audits.get_results(audit_id)
    if results is None:
        raise HTTPException(status_code=404, detail="Results not found")
    view = "normalized" if normalized else "raw"
    return {
        "audit_id": audit_id,
        "audit_type": results["audit_type"],
        "view": view,
        "results": results.get(view),
    }


@router.delete("/{audit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_audit(
    audit_id: str,
    audits: AuditStorage = Depends(get_audit_storage),
    _claims: dict = Depends(require_auth),
) -> None:
    if not audits.delete(audit_id):
        raise HTTPException(status_code=404, detail="Audit not found")
