def _upload(client, synthetic_csv, name="data.csv"):
    r = client.post(
        "/datasets", files={"file": (name, synthetic_csv, "text/csv")}
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_health_and_info(client):
    assert client.get("/health").json() == {"status": "ok"}
    info = client.get("/info").json()
    assert info["name"] == "itaca-api"
    assert "labeled" in info["audit_types"]
    assert info["dataset_formats"] == ["csv", "parquet"]


def test_dataset_upload_list_delete(client, synthetic_csv):
    meta = _upload(client, synthetic_csv)
    assert meta["rows"] == 500
    assert set(["sex", "age", "y_true", "y_pred"]) <= set(meta["columns"])
    assert "path" not in meta  # internal detail, never exposed

    listed = client.get("/datasets").json()
    assert any(d["dataset_id"] == meta["dataset_id"] for d in listed)

    assert client.delete(f"/datasets/{meta['dataset_id']}").status_code == 204
    assert client.get(f"/datasets/{meta['dataset_id']}").status_code == 404


def test_pickle_rejected(client):
    r = client.post(
        "/datasets", files={"file": ("evil.pkl", b"\x80\x04", "application/octet-stream")}
    )
    assert r.status_code == 422
    assert "pkl" in r.json()["detail"]


def test_audit_unknown_dataset_rejected(client, model_config):
    r = client.post(
        "/audits",
        json={
            "model": model_config,
            "params": {
                "audit_type": "labeled",
                "dataset_id": "ds_nonexistent",
                "label_column": "y_true",
                "output_column": "y_pred",
                "positive_output": [1],
            },
        },
    )
    assert r.status_code == 422
    assert "not found" in r.json()["detail"]


def test_audit_missing_column_rejected(client, synthetic_csv, model_config):
    ds = _upload(client, synthetic_csv)
    r = client.post(
        "/audits",
        json={
            "model": model_config,
            "params": {
                "audit_type": "labeled",
                "dataset_id": ds["dataset_id"],
                "label_column": "no_such_column",
                "output_column": "y_pred",
                "positive_output": [1],
            },
        },
    )
    assert r.status_code == 422
    assert "no_such_column" in r.json()["detail"]


def _run_and_wait(client, body):
    r = client.post("/audits", json=body)
    assert r.status_code == 202, r.text
    audit_id = r.json()["audit_id"]
    # TestClient executes background tasks before returning, so the job is
    # already finished here.
    record = client.get(f"/audits/{audit_id}").json()
    assert record["status"] == "completed", record.get("error")
    return audit_id


def test_labeled_audit_e2e(client, synthetic_csv, model_config):
    ds = _upload(client, synthetic_csv)
    audit_id = _run_and_wait(
        client,
        {
            "model": model_config,
            "params": {
                "audit_type": "labeled",
                "dataset_id": ds["dataset_id"],
                "label_column": "y_true",
                "output_column": "y_pred",
                "positive_output": [1],
            },
        },
    )
    raw = client.get(
        f"/audits/{audit_id}/results", params={"normalized": False}
    ).json()
    assert raw["view"] == "raw"
    # Raw structure is {metric_name: {sensitive_attribute: values}}
    assert any("gender" in v for v in raw["results"].values()
               if isinstance(v, dict))

    norm = client.get(f"/audits/{audit_id}/results").json()
    assert norm["view"] == "normalized"


def test_production_and_impacted_audits(client, synthetic_csv, model_config):
    ds = _upload(client, synthetic_csv)
    for audit_type in ("production", "impacted"):
        _run_and_wait(
            client,
            {
                "model": model_config,
                "params": {
                    "audit_type": audit_type,
                    "dataset_id": ds["dataset_id"],
                    "output_column": "y_pred",
                    "positive_output": [1],
                },
            },
        )


def test_drift_audit_e2e(client, synthetic_csv, model_config):
    ds_dev = _upload(client, synthetic_csv, "dev.csv")
    ds_prod = _upload(client, synthetic_csv, "prod.csv")
    audit_id = _run_and_wait(
        client,
        {
            "model": model_config,
            "params": {
                "audit_type": "drift",
                "dataset_id_dev": ds_dev["dataset_id"],
                "output_column_dev": "y_pred",
                "positive_output_dev": [1],
                "dataset_id_prod": ds_prod["dataset_id"],
                "output_column_prod": "y_pred",
                "positive_output_prod": [1],
            },
        },
    )
    raw = client.get(
        f"/audits/{audit_id}/results", params={"normalized": False}
    ).json()
    assert raw["results"] is not None


def test_results_conflict_when_not_completed(
        client, synthetic_csv, model_config, monkeypatch):
    ds = _upload(client, synthetic_csv)
    # Force the job to be a no-op so the record stays pending.
    monkeypatch.setattr(
        "app.routers.audits.run_audit_job", lambda *a, **k: None
    )
    r = client.post(
        "/audits",
        json={
            "model": model_config,
            "params": {
                "audit_type": "labeled",
                "dataset_id": ds["dataset_id"],
                "label_column": "y_true",
                "output_column": "y_pred",
                "positive_output": [1],
            },
        },
    )
    audit_id = r.json()["audit_id"]
    assert client.get(f"/audits/{audit_id}/results").status_code == 409


def test_root_redirects_to_docs(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/docs"
