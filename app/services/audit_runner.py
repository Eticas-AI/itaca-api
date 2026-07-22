"""Audit execution service.

Builds an :class:`eticas.model.ml_model.MLModel` from the request's
``model`` block, dispatches to the matching ``run_*_audit`` entry point,
and persists results.

Two result views are persisted per audit:

- ``raw``: the library's per-audit result dict
  (``labeled_results`` / ``production_results`` / ``impacted_results`` /
  ``drift_results``), i.e. the actual metric values.
- ``normalized``: ``MLModel.json_results(norm_values=True)`` — the
  library's 0 (bad) to 100 (good) normalisation, when available for the
  audit type.

Pre-flight validation checks that referenced datasets exist and that every
column named in the request (audit params and sensitive attributes) exists
in the dataset, so obvious mistakes fail fast with a clear message instead
of a traceback deep inside the audit.
"""

import logging
import traceback
from datetime import datetime, timezone
from typing import Any

import numpy as np

from eticas.model.ml_model import MLModel

from .storage import AuditStorage, DatasetStorage

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert numpy/pandas scalars and arrays to JSON types."""
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_to_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def _sensitive_attribute_columns(sensitive_attributes: dict) -> list[str]:
    """Extract raw dataset column names referenced by sensitive attributes.

    Only ``simple`` attributes reference dataset columns directly;
    ``complex`` attributes reference other attribute groups.
    """
    cols = []
    for attr in (sensitive_attributes or {}).values():
        for col in attr.get("columns", []) or []:
            name = col.get("name")
            if name:
                cols.append(name)
    return cols


class AuditValidationError(ValueError):
    pass


def validate_request(payload: dict, datasets: DatasetStorage) -> None:
    """Pre-flight checks. Raises :class:`AuditValidationError` on failure."""
    params = payload["params"]
    audit_type = params["audit_type"]

    if audit_type == "drift":
        refs = [
            (params["dataset_id_dev"],
             [params["output_column_dev"]]),
            (params["dataset_id_prod"],
             [params["output_column_prod"]]),
        ]
    else:
        cols = [params["output_column"]]
        if audit_type == "labeled":
            cols.append(params["label_column"])
        refs = [(params["dataset_id"], cols)]

    sens_cols = _sensitive_attribute_columns(
        payload["model"].get("sensitive_attributes") or {}
    )

    for dataset_id, cols in refs:
        meta = datasets.get_meta(dataset_id)
        if meta is None or datasets.get_path(dataset_id) is None:
            raise AuditValidationError(f"Dataset '{dataset_id}' not found")
        available = set(meta["columns"])
        missing = [c for c in cols + sens_cols if c not in available]
        if missing:
            raise AuditValidationError(
                f"Column(s) {missing} not found in dataset '{dataset_id}' "
                f"(available: {sorted(available)})"
            )


def run_audit_job(
    audit_id: str,
    payload: dict,
    audits: AuditStorage,
    datasets: DatasetStorage,
) -> None:
    """Execute one audit end to end. Designed to run as a background task."""
    audits.update(audit_id, status="running", started_at=_now())
    try:
        model_cfg = payload["model"]
        params = payload["params"]
        audit_type = params["audit_type"]

        model = MLModel(
            model_name=model_cfg["model_name"],
            description=model_cfg.get("description"),
            country=model_cfg.get("country"),
            state=model_cfg.get("state"),
            sensitive_attributes=model_cfg.get("sensitive_attributes"),
            distribution_ref=model_cfg.get("distribution_ref"),
            features=model_cfg.get("features"),
        )

        if audit_type == "labeled":
            model.run_labeled_audit(
                dataset_path=datasets.get_path(params["dataset_id"]),
                label_column=params["label_column"],
                output_column=params["output_column"],
                positive_output=params["positive_output"],
            )
            raw = model.labeled_results
        elif audit_type == "production":
            model.run_production_audit(
                dataset_path=datasets.get_path(params["dataset_id"]),
                output_column=params["output_column"],
                positive_output=params["positive_output"],
            )
            raw = model.production_results
        elif audit_type == "impacted":
            model.run_impacted_audit(
                dataset_path=datasets.get_path(params["dataset_id"]),
                output_column=params["output_column"],
                positive_output=params["positive_output"],
            )
            raw = model.impacted_results
        elif audit_type == "drift":
            model.run_drift_audit(
                dataset_path_dev=datasets.get_path(params["dataset_id_dev"]),
                output_column_dev=params["output_column_dev"],
                positive_output_dev=params["positive_output_dev"],
                dataset_path_prod=datasets.get_path(params["dataset_id_prod"]),
                output_column_prod=params["output_column_prod"],
                positive_output_prod=params["positive_output_prod"],
            )
            raw = model.drift_results
        else:  # pragma: no cover — schema validation makes this unreachable
            raise AuditValidationError(f"Unknown audit type '{audit_type}'")

        # The library's normalized aggregation covers labeled/production/
        # impacted; compute it best-effort and never fail the audit over it.
        normalized = None
        try:
            normalized = model.json_results(norm_values=True)
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "Normalized aggregation unavailable for %s (%s)", audit_id, exc
            )

        audits.save_results(
            audit_id,
            {
                "audit_id": audit_id,
                "audit_type": audit_type,
                "raw": _to_jsonable(raw),
                "normalized": _to_jsonable(normalized),
            },
        )
        audits.update(audit_id, status="completed", finished_at=_now())
        logger.info("Audit %s completed", audit_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Audit %s failed: %s\n%s",
                     audit_id, exc, traceback.format_exc())
        audits.update(
            audit_id, status="failed", finished_at=_now(), error=str(exc)
        )
