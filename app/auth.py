"""Keycloak (OIDC) bearer-token authentication.

Design:

- Tokens are validated **offline** against the realm's JWKS (signature,
  ``exp``, ``iss`` and — unless disabled — ``aud``). No per-request call to
  Keycloak, so the API does not depend on Keycloak latency or availability
  once the signing keys are cached.
- ``AUTH_ENABLED=false`` disables authentication entirely (local development
  without a Keycloak instance). Every endpoint except ``/health`` is
  protected when it is enabled.
- Repointing to a different Keycloak server (e.g. the DataPACT shared
  instance operated by ASSIST) is a pure environment-variable change:
  ``KEYCLOAK_SERVER_URL``, ``KEYCLOAK_REALM``, ``KEYCLOAK_CLIENT_ID``.
- Fine-grained authorisation (per-endpoint roles) is deliberately out of
  scope for now; if AssessR later needs it, add a role check on
  ``claims["realm_access"]["roles"]`` inside :func:`require_auth`.
"""

import logging
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

# Lazily-created, module-cached JWKS client. PyJWKClient caches signing keys
# internally and refreshes on unknown ``kid``.
_jwk_client: Optional[jwt.PyJWKClient] = None


def _get_jwk_client() -> jwt.PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        settings = get_settings()
        _jwk_client = jwt.PyJWKClient(settings.keycloak_jwks_url, cache_keys=True)
    return _jwk_client


def reset_jwk_client() -> None:
    """Drop the cached JWKS client (used by tests and on settings change)."""
    global _jwk_client
    _jwk_client = None


def get_signing_key(token: str):
    """Resolve the signing key for a token via the realm JWKS.

    Isolated in its own function so tests can monkeypatch key retrieval
    without a live Keycloak.
    """
    return _get_jwk_client().get_signing_key_from_jwt(token).key


def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[dict]:
    """FastAPI dependency protecting an endpoint with a Keycloak JWT.

    Returns the decoded token claims (or ``None`` when auth is disabled).
    """
    settings = get_settings()
    if not settings.auth_enabled:
        return None

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        key = get_signing_key(token)
        decode_kwargs = {
            "key": key,
            "algorithms": ["RS256"],
            "issuer": settings.keycloak_issuer,
            "options": {"verify_aud": settings.keycloak_verify_aud},
        }
        if settings.keycloak_verify_aud:
            decode_kwargs["audience"] = settings.keycloak_client_id
        claims = jwt.decode(token, **decode_kwargs)
        return claims
    except jwt.PyJWTError as exc:
        logger.warning("Token rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
