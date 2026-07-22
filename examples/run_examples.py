#!/usr/bin/env python3
"""End-to-end example for the ITACA API.

Mirrors the ITACA library's own ``example.ipynb`` — same datasets, same
model configuration — but through the REST API:

1. Downloads the binary-classifier example datasets from the ITACA
   repository (training / operational / impact).
2. Uploads them as API datasets.
3. Runs all four audit types (labeled, production, impacted, drift).
4. Polls until completion and prints a summary of the normalized scores.

Usage::

    # Against a local no-auth server:
    #   AUTH_ENABLED=false uvicorn app.main:app --port 8080
    python examples/run_examples.py

    # Against an authenticated deployment:
    ITACA_API_URL=https://itaca.example.org ITACA_API_TOKEN=$TOKEN \
        python examples/run_examples.py

Only dependency: ``requests``.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

API_URL = os.getenv("ITACA_API_URL", "http://localhost:8080").rstrip("/")
TOKEN = os.getenv("ITACA_API_TOKEN")

# Canonical example datasets, maintained in the ITACA library repository.
ITACA_RAW = "https://raw.githubusercontent.com/Eticas-AI/itaca/main/files"
DATASETS = {
    "training": "example_training_binary_2.csv",     # labeled + drift (dev)
    "operational": "example_operational_binary_2.csv",  # production + drift (prod)
    "impact": "example_impact_binary_2.csv",         # impacted
}

HERE = Path(__file__).parent
MODEL_CONFIG = json.loads((HERE / "model_config.json").read_text())


def session() -> requests.Session:
    s = requests.Session()
    if TOKEN:
        s.headers["Authorization"] = f"Bearer {TOKEN}"
    return s


def download_examples(dest: Path) -> dict[str, Path]:
    dest.mkdir(exist_ok=True)
    paths = {}
    for role, filename in DATASETS.items():
        path = dest / filename
        if not path.exists():
            print(f"↓ downloading {filename} …")
            r = requests.get(f"{ITACA_RAW}/{filename}", timeout=60)
            r.raise_for_status()
            path.write_bytes(r.content)
        paths[role] = path
    return paths


def upload(s: requests.Session, path: Path) -> str:
    with open(path, "rb") as fh:
        r = s.post(f"{API_URL}/datasets",
                   files={"file": (path.name, fh, "text/csv")})
    r.raise_for_status()
    meta = r.json()
    print(f"↑ uploaded {path.name} → {meta['dataset_id']} "
          f"({meta['rows']} rows)")
    return meta["dataset_id"]


def run_audit(s: requests.Session, params: dict) -> str:
    r = s.post(f"{API_URL}/audits",
               json={"model": MODEL_CONFIG, "params": params})
    r.raise_for_status()
    audit_id = r.json()["audit_id"]
    print(f"▶ {params['audit_type']} audit → {audit_id}")
    return audit_id


def wait(s: requests.Session, audit_id: str, timeout_s: int = 300) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        record = s.get(f"{API_URL}/audits/{audit_id}").json()
        if record["status"] in ("completed", "failed"):
            return record
        time.sleep(1)
    raise TimeoutError(f"Audit {audit_id} did not finish in {timeout_s}s")


def summarize(s: requests.Session, audit_id: str, audit_type: str) -> None:
    r = s.get(f"{API_URL}/audits/{audit_id}/results",
              params={"normalized": True})
    r.raise_for_status()
    normalized = r.json()["results"]
    print(f"\n=== {audit_type} — normalized scores (0 bad … 100 good) ===")
    if not normalized:
        print("  (no normalized view for this audit type — "
              "fetch ?normalized=false for raw metrics)")
        return
    # Structure: {attribute: {group: {metric: value}}}, e.g.
    # {"sex": {"fairness": {"labeled_equity": 99.0, ...}, ...}, ...}
    for attribute, groups in sorted(normalized.items()):
        if not isinstance(groups, dict):
            continue
        parts = []
        for group in ("fairness", "benchmarking", "performance"):
            metrics = groups.get(group) or {}
            values = {k: v for k, v in metrics.items()
                      if isinstance(v, (int, float)) and k != "ref"}
            if values:
                first = list(values.items())[:2]
                parts.append(", ".join(f"{k}={v:.1f}" for k, v in first))
        print(f"  {attribute}: {'; '.join(parts) if parts else 'see raw view'}")


def main() -> int:
    s = session()

    info = s.get(f"{API_URL}/info")
    if info.status_code == 401:
        print("401 from /info — set ITACA_API_TOKEN (or run the server "
              "with AUTH_ENABLED=false for local testing).")
        return 1
    info.raise_for_status()
    print(f"Connected: itaca-api {info.json()['version']} "
          f"(eticas-audit {info.json()['eticas_audit_version']})\n")

    files = download_examples(HERE / "data")
    ds = {role: upload(s, path) for role, path in files.items()}
    print()

    audits = [
        {"audit_type": "labeled", "dataset_id": ds["training"],
         "label_column": "outcome", "output_column": "predicted_outcome",
         "positive_output": [1]},
        {"audit_type": "production", "dataset_id": ds["operational"],
         "output_column": "predicted_outcome", "positive_output": [1]},
        {"audit_type": "impacted", "dataset_id": ds["impact"],
         "output_column": "recorded_outcome", "positive_output": [1]},
        {"audit_type": "drift",
         "dataset_id_dev": ds["training"],
         "output_column_dev": "predicted_outcome",
         "positive_output_dev": [1],
         "dataset_id_prod": ds["operational"],
         "output_column_prod": "predicted_outcome",
         "positive_output_prod": [1]},
    ]

    failures = 0
    for params in audits:
        audit_id = run_audit(s, params)
        record = wait(s, audit_id)
        if record["status"] == "failed":
            failures += 1
            print(f"✗ {params['audit_type']} failed: {record['error']}")
        else:
            summarize(s, audit_id, params["audit_type"])
        print()

    print("Done." if not failures else f"Done with {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
