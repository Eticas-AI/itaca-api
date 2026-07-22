"""Auth tests — validate the OIDC dependency without a live Keycloak.

Tokens are signed with a locally generated RSA key; key retrieval
(:func:`app.auth.get_signing_key`) is monkeypatched to return the matching
public key, exactly what the JWKS lookup would produce.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app import auth as auth_module


@pytest.fixture()
def rsa_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture()
def auth_settings(tmp_path, monkeypatch):
    s = Settings(
        data_dir=tmp_path / "datasets",
        results_dir=tmp_path / "results",
        auth_enabled=True,
        keycloak_server_url="http://keycloak.test",
        keycloak_realm="datapact-dev",
        keycloak_client_id="itaca-api",
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
def auth_client(auth_settings, rsa_keys, monkeypatch):
    _, public_key = rsa_keys
    monkeypatch.setattr("app.auth.get_signing_key", lambda token: public_key)
    return TestClient(create_app())


def _token(private_key, settings, *, aud="itaca-api", exp_offset=3600,
           issuer=None):
    now = int(time.time())
    claims = {
        "iss": issuer or settings.keycloak_issuer,
        "aud": aud,
        "sub": "service-account-test",
        "iat": now,
        "exp": now + exp_offset,
    }
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_missing_token_rejected(auth_client):
    assert auth_client.get("/info").status_code == 401


def test_health_open_without_token(auth_client):
    assert auth_client.get("/health").status_code == 200


def test_valid_token_accepted(auth_client, rsa_keys, auth_settings):
    private_key, _ = rsa_keys
    token = _token(private_key, auth_settings)
    r = auth_client.get("/info", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["auth_enabled"] is True


def test_expired_token_rejected(auth_client, rsa_keys, auth_settings):
    private_key, _ = rsa_keys
    token = _token(private_key, auth_settings, exp_offset=-60)
    r = auth_client.get("/info", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_wrong_audience_rejected(auth_client, rsa_keys, auth_settings):
    private_key, _ = rsa_keys
    token = _token(private_key, auth_settings, aud="another-client")
    r = auth_client.get("/info", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_wrong_issuer_rejected(auth_client, rsa_keys, auth_settings):
    private_key, _ = rsa_keys
    token = _token(private_key, auth_settings,
                   issuer="http://evil.test/realms/datapact-dev")
    r = auth_client.get("/info", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_wrong_key_rejected(auth_client, auth_settings):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _token(other, auth_settings)
    r = auth_client.get("/info", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


@pytest.fixture()
def split_horizon_settings(tmp_path, monkeypatch):
    """Split-horizon: the API reaches Keycloak at an internal URL while
    tokens carry a different public issuer (KEYCLOAK_ISSUER_URL override)."""
    s = Settings(
        data_dir=tmp_path / "datasets",
        results_dir=tmp_path / "results",
        auth_enabled=True,
        keycloak_server_url="http://keycloak:8080",
        keycloak_realm="datapact-dev",
        keycloak_client_id="itaca-api",
        keycloak_issuer_url="http://localhost:8081/realms/datapact-dev",
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
def split_horizon_client(split_horizon_settings, rsa_keys, monkeypatch):
    _, public_key = rsa_keys
    monkeypatch.setattr("app.auth.get_signing_key", lambda token: public_key)
    return TestClient(create_app())


def test_split_horizon_public_issuer_accepted(
    split_horizon_client, rsa_keys, split_horizon_settings
):
    # A token stamped with the public issuer must be accepted even though
    # the API reaches Keycloak over an internal (different) URL.
    private_key, _ = rsa_keys
    token = _token(
        private_key,
        split_horizon_settings,
        issuer="http://localhost:8081/realms/datapact-dev",
    )
    r = split_horizon_client.get(
        "/info", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200


def test_split_horizon_jwks_url_uses_server_url(split_horizon_settings):
    # JWKS is fetched from the internal server URL, never from the public
    # issuer (which the API may not resolve on the internal network).
    s = split_horizon_settings
    assert s.keycloak_issuer == "http://localhost:8081/realms/datapact-dev"
    assert s.keycloak_jwks_url == (
        "http://keycloak:8080/realms/datapact-dev"
        "/protocol/openid-connect/certs"
    )


def test_empty_issuer_url_derives_from_server(tmp_path):
    # An explicitly empty override (compose can inject "") is treated as
    # unset, so the issuer falls back to the server URL.
    s = Settings(
        data_dir=tmp_path / "datasets",
        results_dir=tmp_path / "results",
        keycloak_server_url="http://keycloak:8080",
        keycloak_realm="datapact-dev",
        keycloak_issuer_url="",
    )
    assert s.keycloak_issuer == "http://keycloak:8080/realms/datapact-dev"
