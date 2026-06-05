"""
FastAPI application entry point for the HAMq Arbiter.

Lifecycle
---------
  startup:
    1. Open SQLite audit database and run schema migrations.
    2. Inject AuditStore and Reconciler into app.state so routes can
       access them via the Request object (no global singletons in routes).
    3. If PRODUCER_AUTOSTART is not explicitly False, start the background
       reconcile loop automatically.

  shutdown:
    1. Stop the reconcile loop gracefully (cancel task + wait).
    2. Close the SQLite connection.

CORS
----
  CORS_ORIGINS env var controls allowed origins.  Default "*" is suitable for
  development; set to specific origins in production to prevent CSRF.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.audit_store import AuditStore
from app.config import settings
from app.reconciler import Reconciler

# ---------------------------------------------------------------------------
# Logging — structured log lines for easy parsing by log aggregators
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan (replaces deprecated on_event handlers)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Async context manager executed by FastAPI on startup and shutdown.

    Everything before the ``yield`` runs on startup; everything after runs on
    shutdown.  Using the lifespan pattern ensures resources are always cleaned
    up, even when the process is killed with SIGTERM.
    """
    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------
    logger.info("HAMq Arbiter %s starting up", settings.ARBITER_ID)

    # Ensure the data directory exists (Kubernetes PVC may be empty on first start)
    db_dir = os.path.dirname(settings.DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        logger.info("Created data directory: %s", db_dir)

    # Initialise the audit store (opens connection + creates table if needed)
    audit_store = AuditStore(settings.DB_PATH)
    await audit_store.initialize()

    # Create the reconciler and inject both objects into app.state so routes
    # can retrieve them from the Request object.
    reconciler = Reconciler(audit_store)
    app.state.audit_store = audit_store
    app.state.reconciler = reconciler

    # Auto-start the reconcile loop.  Operators can POST /api/stop to pause
    # and POST /api/start to resume without redeploying.
    logger.info(
        "Auto-starting reconcile loop (interval=%.1fs, producers=%s)",
        settings.RECONCILE_INTERVAL_S,
        settings.PRODUCER_API_URLS,
    )
    await reconciler.start()

    logger.info(
        "HAMq Arbiter ready — listening on %s:%d",
        settings.API_HOST,
        settings.API_PORT,
    )

    yield  # <-- application runs here

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    logger.info("HAMq Arbiter shutting down")
    await reconciler.stop()
    await audit_store.close()
    logger.info("HAMq Arbiter shutdown complete")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HAMq Arbiter",
    description=(
        "The HAMq Arbiter reconciles sent and received message sequences "
        "to detect message loss and compute per-producer loss rates."
    ),
    version=os.getenv("APP_VERSION", "1.0.0"),
    lifespan=lifespan,
    # Disable automatic redirection of /path/ → /path to avoid surprises behind
    # Kubernetes Ingress controllers that may not follow redirects.
    redirect_slashes=False,
)

# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------
# Parse the CORS_ORIGINS setting: "*" → allow all, otherwise split on comma
_cors_origins = (
    ["*"]
    if settings.CORS_ORIGINS.strip() == "*"
    else [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Include routes
# ---------------------------------------------------------------------------
app.include_router(router)

# ---------------------------------------------------------------------------
# Serve React SPA (must be mounted AFTER API routes)
# ---------------------------------------------------------------------------
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        candidate = _static_dir / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_static_dir / "index.html"))

    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
else:
    logging.getLogger(__name__).warning("No static/ directory — React SPA not served (%s)", _static_dir)


# ---------------------------------------------------------------------------
# Dev entrypoint — not used in production (uvicorn is called by the Dockerfile CMD)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,  # hot-reload in development only
        log_level="info",
    )
