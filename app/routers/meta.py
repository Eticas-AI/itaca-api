"""Service metadata endpoints: liveness and capability discovery."""

from importlib.metadata import PackageNotFoundError, version as pkg_version

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from ..auth import require_auth
from ..config import get_settings
from ..schemas import InfoResponse
from ..version import __version__

router = APIRouter(tags=["meta"])


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Convenience redirect: the interactive API docs live at /docs."""
    return RedirectResponse(url="/docs")


@router.get("/health")
def health() -> dict:
    """Liveness probe. Unauthenticated by design (container orchestration)."""
    return {"status": "ok"}


@router.get("/info", response_model=InfoResponse)
def info(_claims: dict = Depends(require_auth)) -> InfoResponse:
    try:
        lib_version = pkg_version("eticas-audit")
    except PackageNotFoundError:
        lib_version = "unknown"
    return InfoResponse(
        version=__version__,
        eticas_audit_version=lib_version,
        auth_enabled=get_settings().auth_enabled,
    )
