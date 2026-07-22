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

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, status

from ..auth import require_auth
from ..schemas import AuditCreated, AuditRecord, AuditRequest
from ..services.audit_runner import (
    AuditValidationError,
    run_audit_job,
    validate_request,
)
from ..services.storage import AuditStorage, DatasetStorage

router = APIRouter(prefix="/audits", tags=["audits"])

# Example model configuration mirroring the ITACA library's example.ipynb
# (and examples/model_config.json). Exercises simple attributes with
# underprivileged values, simple with privileged values, and a complex
# (intersectional) attribute.
_EXAMPLE_MODEL = {
    "model_name": "ML Testing Regression",
    "description": "A logistic regression model to illustrate audits",
    "country": "USA",
    "state": "CA",
    "features": ["feature_0", "feature_1", "feature_2"],
    "sensitive_attributes": {
        "sex": {"columns": [{"name": "sex", "underprivileged": [2]}],
                "type": "simple"},
        "ethnicity": {"columns": [{"name": "ethnicity", "privileged": [1]}],
                      "type": "simple"},
        "age": {"columns": [{"name": "age", "privileged": [3, 4]}],
                "type": "simple"},
        "sex_ethnicity": {"groups": ["sex", "ethnicity"], "type": "complex"},
    },
}

# Named examples rendered as a dropdown in Swagger UI. Column names match
# the ITACA example datasets (examples/ shows how to obtain and upload
# them); replace the ds_… placeholders with real ids from POST /datasets.
_AUDIT_EXAMPLES = {
    "labeled": {
        "summary": "Labeled audit (training data with ground truth)",
        "description": "Requires a dataset with both the true label and "
                       "the model prediction. Column names match ITACA's "
                       "example_training_binary_2.csv.",
        "value": {
            "model": _EXAMPLE_MODEL,
            "params": {
                "audit_type": "labeled",
                "dataset_id": "ds_REPLACE_ME",
                "label_column": "outcome",
                "output_column": "predicted_outcome",
                "positive_output": [1],
            },
        },
    },
    "production": {
        "summary": "Production audit (predictions only)",
        "description": "Unlabeled data from a running system. Column names "
                       "match ITACA's example_operational_binary_2.csv.",
        "value": {
            "model": _EXAMPLE_MODEL,
            "params": {
                "audit_type": "production",
                "dataset_id": "ds_REPLACE_ME",
                "output_column": "predicted_outcome",
                "positive_output": [1],
            },
        },
    },
    "impacted": {
        "summary": "Impacted audit (recorded real-world outcomes)",
        "description": "Recorded outcomes after decisions were applied. "
                       "Column names match ITACA's "
                       "example_impact_binary_2.csv.",
        "value": {
            "model": _EXAMPLE_MODEL,
            "params": {
                "audit_type": "impacted",
                "dataset_id": "ds_REPLACE_ME",
                "output_column": "recorded_outcome",
                "positive_output": [1],
            },
        },
    },
    "drift": {
        "summary": "Drift audit (development vs production)",
        "description": "Compares two datasets to detect distribution and "
                       "behaviour drift; references two dataset ids.",
        "value": {
            "model": _EXAMPLE_MODEL,
            "params": {
                "audit_type": "drift",
                "dataset_id_dev": "ds_REPLACE_ME_DEV",
                "output_column_dev": "predicted_outcome",
                "positive_output_dev": [1],
                "dataset_id_prod": "ds_REPLACE_ME_PROD",
                "output_column_prod": "predicted_outcome",
                "positive_output_prod": [1],
            },
        },
    },
}


def get_audit_storage() -> AuditStorage:
    return AuditStorage()


def get_dataset_storage() -> DatasetStorage:
    return DatasetStorage()


@router.post("", response_model=AuditCreated,
             status_code=status.HTTP_202_ACCEPTED)
def create_audit(
    background: BackgroundTasks,
    request: AuditRequest = Body(openapi_examples=_AUDIT_EXAMPLES),
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
