import pytest
from pydantic import ValidationError

from app.schemas import AuditRequest


MODEL = {
    "model_name": "m",
    "sensitive_attributes": {
        "gender": {
            "columns": [{"name": "sex", "underprivileged": [2]}],
            "type": "simple",
        }
    },
}


def test_labeled_params_valid():
    req = AuditRequest(
        model=MODEL,
        params={
            "audit_type": "labeled",
            "dataset_id": "ds_1",
            "label_column": "y",
            "output_column": "p",
            "positive_output": [1],
        },
    )
    assert req.params.audit_type == "labeled"


def test_labeled_missing_label_column_rejected():
    with pytest.raises(ValidationError):
        AuditRequest(
            model=MODEL,
            params={
                "audit_type": "labeled",
                "dataset_id": "ds_1",
                "output_column": "p",
                "positive_output": [1],
            },
        )


def test_drift_requires_both_datasets():
    with pytest.raises(ValidationError):
        AuditRequest(
            model=MODEL,
            params={
                "audit_type": "drift",
                "dataset_id_dev": "ds_1",
                "output_column_dev": "p",
                "positive_output_dev": [1],
                # prod side missing
            },
        )


def test_unknown_audit_type_rejected():
    with pytest.raises(ValidationError):
        AuditRequest(
            model=MODEL,
            params={"audit_type": "quantum", "dataset_id": "ds_1"},
        )


def test_production_does_not_accept_label_column():
    req = AuditRequest(
        model=MODEL,
        params={
            "audit_type": "production",
            "dataset_id": "ds_1",
            "output_column": "p",
            "positive_output": [1],
        },
    )
    assert not hasattr(req.params, "label_column")
