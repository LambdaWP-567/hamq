"""
HAMq Controller — FastAPI application entry point.

Initialises shared singletons (K8sClient, EventStore, ChaosEngine),
registers API routes, and mounts the Prometheus ASGI middleware.

Start the server:
    uvicorn app.main:app --host 0.0.0.0 --port 8003
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.routes import router
from app.chaos_engine import ChaosEngine
from app.config import settings
from app.event_store import EventStore
from app.k8s_client import K8sClient

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (startup + shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    AsyncContextManager that runs initialisation on startup and cleanup
    on shutdown.

    Stores shared singletons on app.state so route handlers can access them
    without module-level global state (which complicates unit testing).
    """
    logger.info("HAMq Controller starting — controller_id=%s", settings.CONTROLLER_ID)

    # ------------------------------------------------------------------
    # Kubernetes client
    # ------------------------------------------------------------------
    k8s_client = K8sClient(settings_=settings)
    if k8s_client.is_connected:
        logger.info("Kubernetes: connected")
    else:
        logger.warning(
            "Kubernetes: NOT connected (check service account permissions or K8S_IN_CLUSTER setting)"
        )

    # ------------------------------------------------------------------
    # Event store (SQLite)
    # ------------------------------------------------------------------
    event_store = EventStore(db_path=settings.DB_PATH)
    await event_store.initialize()

    # ------------------------------------------------------------------
    # Chaos engine
    # ------------------------------------------------------------------
    chaos_engine = ChaosEngine(k8s_client=k8s_client, settings_=settings)

    # ------------------------------------------------------------------
    # Attach to app.state for dependency injection in routes
    # ------------------------------------------------------------------
    app.state.k8s_client = k8s_client
    app.state.event_store = event_store
    app.state.chaos_engine = chaos_engine
    app.state.settings = settings

    logger.info("HAMq Controller startup complete — listening on port %d", settings.API_PORT)

    yield

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    logger.info("HAMq Controller shutting down…")
    await event_store.close()
    logger.info("HAMq Controller stopped")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HAMq Controller",
    description=(
        "Chaos engineering and cluster management for the HAMq system.\n\n"
        "Provides REST endpoints to restart Kafka pods, cordon/drain nodes, "
        "inject network partitions, and run scheduled chaos experiments."
    ),
    version=os.getenv("APP_VERSION", "1.0.0"),
    lifespan=lifespan,
    # Disable the default /docs and /redoc in production if desired
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# Parse the CORS_ORIGINS setting: "*" allows all, otherwise split on ","
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
# Prometheus /metrics endpoint
# ---------------------------------------------------------------------------
@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Expose Prometheus metrics in text exposition format. No auth required."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
app.include_router(router)

# ---------------------------------------------------------------------------
# Serve React SPA (must be mounted AFTER API routes)
# ---------------------------------------------------------------------------
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
else:
    logging.getLogger(__name__).warning("No static/ directory — React SPA not served (%s)", _static_dir)


# ---------------------------------------------------------------------------
# Uvicorn entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
        log_level="info",
    )
