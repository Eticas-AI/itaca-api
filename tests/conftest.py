import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import auth as auth_module
from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    """Settings with isolated storage and auth disabled by default."""
    s = Settings(
        data_dir=tmp_path / "datasets",
        results_dir=tmp_path / "results",
        auth_enabled=False,
    )
    get_settings.cache_clear()
    monkeypatch.setattr("app.config.get_settings", lambda: s)
    monkeypatch.setattr("app.auth.get_settings", lambda: s)
    monkeypatch.setattr("app.routers.meta.get_settings", lambda: s)
    monkeypatch.setattr("app.routers.datasets.get_settings", lambda: s)
    monkeypatch.setattr("app.services.storage.get_settings", lambda: s)
    auth_module.reset_jwk_client()
    return s


@pytest.fixture()
def client(settings):
    app = create_app()
    # TestClient runs BackgroundTasks synchronously on response completion,
    # which is exactly what the e2e flow tests need.
    return TestClient(app)


@pytest.fixture()
def synthetic_csv() -> bytes:
    """Binary-classifier dataset with a sensitive attribute and known skew."""
    rng = np.random.default_rng(42)
    n = 500
    sex = rng.choice([1, 2], size=n, p=[0.6, 0.4])  # 2 = underprivileged
    y_true = rng.choice([0, 1], size=n, p=[0.5, 0.5])
    # Predictions biased against group 2
    bias = np.where(sex == 2, -0.25, 0.15)
    y_pred = (rng.random(n) + bias > 0.5).astype(int)
    age = rng.integers(18, 80, size=n)
    df = pd.DataFrame(
        {"sex": sex, "age": age, "y_true": y_true, "y_pred": y_pred}
    )
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


@pytest.fixture()
def model_config() -> dict:
    return {
        "model_name": "test-classifier",
        "description": "synthetic test model",
        "country": "NO",
        "sensitive_attributes": {
            "gender": {
                "columns": [{"name": "sex", "underprivileged": [2]}],
                "type": "simple",
            }
        },
        "features": ["age"],
    }
