"""Request/response schemas.

The audit request schema maps **1:1** to the public surface of the
``eticas-audit`` library (``BaseModel.__init__`` plus the four
``MLModel.run_*_audit`` entry points). No new abstraction is introduced:
``model`` is passed through to the ``MLModel`` constructor and ``params``
to the corresponding ``run_*_audit`` call.

``AuditParams`` is a discriminated union over ``audit_type`` so that
type-specific parameters are validated statically (schema errors surface
as HTTP 422, not as tracebacks inside the audit run).
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class AuditType(str, Enum):
    labeled = "labeled"
    production = "production"
    impacted = "impacted"
    drift = "drift"


class AuditStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


# ---------------------------------------------------------------------------
# Model configuration (→ eticas.model.base_model.BaseModel.__init__)
# ---------------------------------------------------------------------------

class ModelConfig(BaseModel):
    """Metadata and fairness configuration of the audited model.

    ``sensitive_attributes`` uses ITACA's native structure and is passed
    through verbatim, e.g.::

        {
          "gender": {
            "columns": [{"name": "sex", "underprivileged": [2]}],
            "type": "simple"
          },
          "gender_ethnicity": {"groups": ["gender", "ethnicity"],
                                "type": "complex"}
        }
    """

    model_name: str
    description: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    sensitive_attributes: dict[str, Any]
    distribution_ref: Optional[dict[str, Any]] = None
    features: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Per-audit-type parameters (→ MLModel.run_*_audit)
# ---------------------------------------------------------------------------

class LabeledParams(BaseModel):
    audit_type: Literal["labeled"] = "labeled"
    dataset_id: str
    label_column: str
    output_column: str
    positive_output: list[Any]


class ProductionParams(BaseModel):
    audit_type: Literal["production"] = "production"
    dataset_id: str
    output_column: str
    positive_output: list[Any]


class ImpactedParams(BaseModel):
    audit_type: Literal["impacted"] = "impacted"
    dataset_id: str
    output_column: str
    positive_output: list[Any]


class DriftParams(BaseModel):
    audit_type: Literal["drift"] = "drift"
    dataset_id_dev: str
    output_column_dev: str
    positive_output_dev: list[Any]
    dataset_id_prod: str
    output_column_prod: str
    positive_output_prod: list[Any]


AuditParams = Annotated[
    Union[LabeledParams, ProductionParams, ImpactedParams, DriftParams],
    Field(discriminator="audit_type"),
]


class AuditRequest(BaseModel):
    model: ModelConfig
    params: AuditParams


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class DatasetInfo(BaseModel):
    dataset_id: str
    filename: str
    format: str
    size_bytes: int
    rows: int
    columns: list[str]
    uploaded_at: datetime


class AuditRecord(BaseModel):
    audit_id: str
    audit_type: AuditType
    status: AuditStatus
    model_name: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    request: AuditRequest


class AuditCreated(BaseModel):
    audit_id: str
    status: AuditStatus


class InfoResponse(BaseModel):
    name: str = "itaca-api"
    version: str
    eticas_audit_version: str
    audit_types: list[AuditType] = list(AuditType)
    dataset_formats: list[str] = ["csv", "parquet"]
    auth_enabled: bool
