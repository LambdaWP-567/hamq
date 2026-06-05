"""
HAMq Consumer — FastAPI Application Entry Point
==================================================
Wires together all application components and starts the HTTP/WebSocket server.

Startup sequence:
  1. FastAPI lifespan hook initialises ConsumerService (opens SQLite, creates tasks).
  2. The Kafka consume loop is NOT started automatically — call POST /api/start.
  3. Static React SPA files are served from the `static/` directory if present.

Shutdown sequence:
  1. FastAPI lifespan hook calls ConsumerService.shutdown() which:
     - Stops the Kafka consumer and commits final offsets.
     - Cancels background stats/cleanup tasks.
     - Closes the SQLite connection.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router, set_service
from .config import settings
from .consumer_service import ConsumerService

# Configure logging before anything else so all modules inherit the config.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Application lifespan
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    FastAPI lifespan context manager — replaces the deprecated @app.on_event
    pattern.

    Everything before ``yield`` runs at startup; everything after at shutdown.
    """
    # ------------------------------------------------------------------ startup
    logger.info(
        "HAMq Consumer starting (id=%s, db=%s)",
        settings.CONSUMER_ID,
        settings.DB_PATH,
    )
    svc = ConsumerService()
    await svc.initialize()

    # Inject the service into the route handlers.
    set_service(svc)

    # Store on app.state for potential middleware access.
    app.state.consumer_service = svc

    logger.info("ConsumerService ready — call POST /api/start to begin consuming")

    yield  # <-- application runs here

    # --------------------------------------------------------------- shutdown
    logger.info("HAMq Consumer shutting down")
    await svc.shutdown()
    logger.info("Shutdown complete")


# --------------------------------------------------------------------------- #
#  FastAPI application
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="HAMq Consumer",
    description=(
        "HAMq Consumer — receives messages from Kafka, persists them to SQLite, "
        "and exposes a REST + WebSocket API for the Arbiter and the React SPA."
    ),
    version=os.getenv("APP_VERSION", "1.0.0"),
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# --------------------------------------------------------------------------- #
#  CORS
# --------------------------------------------------------------------------- #
# Allow the React SPA (served from a different origin during development) to
# reach the API.  In production, restrict CORS_ORIGINS to the actual domain.

cors_origins = (
    ["*"]
    if settings.CORS_ORIGINS == "*"
    else [o.strip() for o in settings.CORS_ORIGINS.split(",")]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
#  API routes
# --------------------------------------------------------------------------- #

app.include_router(router)

# --------------------------------------------------------------------------- #
#  Static files (React SPA)
# --------------------------------------------------------------------------- #
# The Dockerfile builds the frontend into backend/static.  If the directory
# doesn't exist (e.g., in CI) we skip mounting it gracefully.

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")

if os.path.isdir(_STATIC_DIR):
    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        candidate = os.path.join(_STATIC_DIR, full_path)
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_STATIC_DIR, "index.html"))

    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
    logger.info("Serving React SPA from %s", _STATIC_DIR)
else:
    logger.info(
        "No static/ directory found at %s — React SPA not served", _STATIC_DIR
    )


# --------------------------------------------------------------------------- #
#  Dev-server entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
        log_level="info",
    )
