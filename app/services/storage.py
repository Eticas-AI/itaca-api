"""Filesystem-backed storage for datasets and audit records.

Deliberately no database: audit records are JSON files under
``RESULTS_DIR`` and datasets are files under ``DATA_DIR``. This keeps the
deployment footprint at exactly one container plus a persistent volume —
the lightest possible artifact for the ASSIST-operated shared deployment.

Writes are atomic (temp file + ``os.replace``) so a crash mid-write never
leaves a corrupt record.

Dataset formats are restricted to **CSV and Parquet**. The underlying
library also reads pickle files, but unpickling third-party uploads is
arbitrary code execution — unacceptable on a shared consortium service —
so ``.pkl`` is deliberately not accepted at the API boundary.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from ..config import get_settings

ALLOWED_EXTENSIONS = {".csv", ".parquet"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, default=str)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

class DatasetStorage:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir or get_settings().data_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _meta_path(self, dataset_id: str) -> Path:
        return self.base_dir / f"{dataset_id}.meta.json"

    def save(self, filename: str, content: bytes) -> dict:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Unsupported format '{ext}'. Accepted: "
                f"{sorted(ALLOWED_EXTENSIONS)} "
                "(.pkl is deliberately rejected: unpickling uploads is a "
                "code-execution risk on a shared service)."
            )
        dataset_id = new_id("ds")
        file_path = self.base_dir / f"{dataset_id}{ext}"
        with open(file_path, "wb") as fh:
            fh.write(content)

        # Validate readability and capture schema now, so a broken file
        # fails at upload time instead of inside an audit run.
        try:
            df = self._read(file_path)
        except Exception as exc:
            file_path.unlink(missing_ok=True)
            raise ValueError(f"File could not be parsed as {ext}: {exc}") from exc

        meta = {
            "dataset_id": dataset_id,
            "filename": filename,
            "format": ext.lstrip("."),
            "size_bytes": len(content),
            "rows": int(df.shape[0]),
            "columns": [str(c) for c in df.columns],
            "uploaded_at": _now(),
            "path": str(file_path),
        }
        _atomic_write_json(self._meta_path(dataset_id), meta)
        return meta

    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        if path.suffix == ".csv":
            return pd.read_csv(path)
        return pd.read_parquet(path)

    def get_meta(self, dataset_id: str) -> Optional[dict]:
        p = self._meta_path(dataset_id)
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)

    def get_path(self, dataset_id: str) -> Optional[str]:
        meta = self.get_meta(dataset_id)
        if meta is None:
            return None
        return meta["path"] if Path(meta["path"]).exists() else None

    def list(self) -> list[dict]:
        metas = []
        for p in sorted(self.base_dir.glob("*.meta.json")):
            with open(p, encoding="utf-8") as fh:
                metas.append(json.load(fh))
        return metas

    def delete(self, dataset_id: str) -> bool:
        meta = self.get_meta(dataset_id)
        if meta is None:
            return False
        Path(meta["path"]).unlink(missing_ok=True)
        self._meta_path(dataset_id).unlink(missing_ok=True)
        return True


# ---------------------------------------------------------------------------
# Audit records
# ---------------------------------------------------------------------------

class AuditStorage:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir or get_settings().results_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _record_path(self, audit_id: str) -> Path:
        return self.base_dir / f"{audit_id}.json"

    def _results_path(self, audit_id: str) -> Path:
        return self.base_dir / f"{audit_id}.results.json"

    def create(self, request_payload: dict) -> dict:
        audit_id = new_id("audit")
        record = {
            "audit_id": audit_id,
            "audit_type": request_payload["params"]["audit_type"],
            "status": "pending",
            "model_name": request_payload["model"]["model_name"],
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
            "error": None,
            "request": request_payload,
        }
        _atomic_write_json(self._record_path(audit_id), record)
        return record

    def get(self, audit_id: str) -> Optional[dict]:
        p = self._record_path(audit_id)
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)

    def list(self) -> list[dict]:
        records = []
        for p in sorted(self.base_dir.glob("audit_*.json")):
            if p.name.endswith(".results.json"):
                continue
            with open(p, encoding="utf-8") as fh:
                records.append(json.load(fh))
        return records

    def update(self, audit_id: str, **fields: Any) -> Optional[dict]:
        record = self.get(audit_id)
        if record is None:
            return None
        record.update(fields)
        _atomic_write_json(self._record_path(audit_id), record)
        return record

    def save_results(self, audit_id: str, results: dict) -> None:
        _atomic_write_json(self._results_path(audit_id), results)

    def get_results(self, audit_id: str) -> Optional[dict]:
        p = self._results_path(audit_id)
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)

    def delete(self, audit_id: str) -> bool:
        existed = self._record_path(audit_id).exists()
        self._record_path(audit_id).unlink(missing_ok=True)
        self._results_path(audit_id).unlink(missing_ok=True)
        return existed
