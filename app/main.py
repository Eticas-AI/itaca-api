"""Application entry point.

Run locally with::

    uvicorn app.main:app --reload --port 8080

Interactive OpenAPI docs at ``/docs``.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import audits, datasets, meta
from .version import __version__


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = FastAPI(
        title="ITACA API",
        description=(
            "REST API wrapper for ITACA (`eticas-audit`), the open-source "
            "AI fairness auditing library by Eticas. Developed as part of "
            "the DataPACT project (Horizon Europe GA 101189771) for "
            "integration into the DataPACT toolkit."
        ),
        version=__version__,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(meta.router)
    app.include_router(datasets.router)
    app.include_router(audits.router)
    return app


app = create_app()
