"""Application settings.

All runtime configuration is externalised here and loaded from environment
variables (or a local ``.env`` file for development). Nothing in the code
base hardcodes deployment-specific values: the deployment operator (ASSIST,
for the DataPACT shared deployment) only needs to change environment
variables — see ``example.env`` at the repo root for the full contract.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    log_level: str = "INFO"
    cors_origins: str = "*"  # comma-separated list; "*" only for dev

    # --- Storage ---
    data_dir: Path = Path("data/datasets")
    results_dir: Path = Path("data/results")
    max_upload_mb: int = 200

    # --- Auth (what ASSIST repoints for the shared deployment) ---
    auth_enabled: bool = False
    keycloak_server_url: str = "http://localhost:8081"
    keycloak_realm: str = "datapact-dev"
    keycloak_client_id: str = "itaca-api"
    keycloak_verify_aud: bool = True
    # Expected token issuer, when it differs from the URL the API uses to
    # reach Keycloak (split-horizon: e.g. tokens issued at a public URL
    # while the API fetches JWKS over an internal network). Empty/unset →
    # derived from keycloak_server_url.
    keycloak_issuer_url: Optional[str] = None

    @field_validator("keycloak_issuer_url", mode="before")
    @classmethod
    def _empty_string_as_none(cls, v):
        # compose can inject "" for an unset override; treat it as None so
        # the issuer falls back to keycloak_server_url.
        return v or None

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def keycloak_issuer(self) -> str:
        # Explicit override wins (split-horizon: public issuer ≠ internal
        # fetch URL); otherwise derive from the server URL as before.
        if self.keycloak_issuer_url:
            return self.keycloak_issuer_url.rstrip("/")
        return f"{self.keycloak_server_url.rstrip('/')}/realms/{self.keycloak_realm}"

    @property
    def keycloak_jwks_url(self) -> str:
        # Always derived from the URL the API actually uses to reach
        # Keycloak — never from the (possibly public) issuer, which the API
        # may not be able to resolve on the internal network.
        base = self.keycloak_server_url.rstrip("/")
        return f"{base}/realms/{self.keycloak_realm}/protocol/openid-connect/certs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
