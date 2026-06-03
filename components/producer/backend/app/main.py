"""
FastAPI application factory and lifecycle management for the HAMq Producer.

Startup sequence
----------------
1. MessageBuffer.initialize() — open/create SQLite DB
2. ResilientKafkaProducer.start() — launch background reconnect + flush tasks
3. ProducerService.__init__ — wired to kafka_producer + buffer
4. If PRODUCER_AUTOSTART=true → ProducerService.start_producing()

Shutdown sequence (SIGTERM from Kubernetes)
-------------------------------------------
1. ProducerService.stop_producing()
2. ResilientKafkaProducer.stop() — flushes remaining buffer, closes aiokafka
3. MessageBuffer.close() — closes SQLite connection

Static files
------------
The React frontend is built into ``./static/`` by the Docker multi-stage
build.  If the directory exists it is served at ``/`` so that the single
container serves both the API and the UI.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.buffer import MessageBuffer
from app.config import settings
from app.kafka_producer import ResilientKafkaProducer
from app.producer_service import ProducerService

# Configure root logger — uvicorn will re-configure at startup, but having
# a basic config here helps during testing.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan context manager.

    Everything before ``yield`` runs at startup; everything after runs at
    shutdown.  This replaces the deprecated ``on_event`` decorators.
    """
    # ------------------------------------------------------------------
    # STARTUP
    # ------------------------------------------------------------------
    logger.info("HAMq Producer starting (id=%s)", settings.PRODUCER_ID)

    # 1. Initialise local SQLite buffer
    buffer = MessageBuffer()
    await buffer.initialize()

    # 2. Start the resilient Kafka producer (connects in background)
    kafka_producer = ResilientKafkaProducer(buffer=buffer)
    await kafka_producer.start()

    # 3. Wire up the producer service
    producer_service = ProducerService(
        kafka_producer=kafka_producer,
        buffer=buffer,
    )

    # 4. Attach shared instances to app.state so routes can access them
    app.state.buffer = buffer
    app.state.kafka_producer = kafka_producer
    app.state.producer_service = producer_service

    # 5. Auto-start if configured
    if settings.PRODUCER_AUTOSTART:
        logger.info("PRODUCER_AUTOSTART=true — starting production immediately")
        await producer_service.start_producing()

    logger.info("HAMq Producer startup complete")

    yield  # ← application runs here

    # ------------------------------------------------------------------
    # SHUTDOWN
    # ------------------------------------------------------------------
    logger.info("HAMq Producer shutting down …")

    # Stop message generation first so no new messages are generated
    # while we're flushing the buffer.
    await producer_service.stop_producing()

    # Stop Kafka producer (attempts final buffer flush before closing)
    await kafka_producer.stop()

    # Close SQLite
    await buffer.close()

    logger.info("HAMq Producer shutdown complete")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns
    -------
    FastAPI
        Fully configured application instance, ready to be served by uvicorn.
    """
    app = FastAPI(
        title="HAMq Producer",
        description=(
            "Highly Available Message Queue — resilient Kafka producer with "
            "SQLite-backed local buffer, real-time WebSocket status streaming, "
            "and a React management UI."
        ),
        version="1.0.0",
        lifespan=lifespan,
        # Disable automatic /docs redirect so it doesn't conflict with the
        # React SPA served at /
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------

    # Parse CORS_ORIGINS: "*" → ["*"], otherwise split on commas
    cors_origins_raw = settings.CORS_ORIGINS.strip()
    if cors_origins_raw == "*":
        cors_origins = ["*"]
    else:
        cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Routers
    # ------------------------------------------------------------------
    app.include_router(router)

    # ------------------------------------------------------------------
    # Static files (React frontend)
    # ------------------------------------------------------------------
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        logger.info("Serving React frontend from %s", static_dir)
        # Mount the React app at "/" — must come LAST so API routes take priority.
        # The "html=True" flag enables SPA fallback (serves index.html for
        # unknown paths so client-side routing works).
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:
        logger.warning(
            "Static directory %s not found — frontend not available. "
            "Run 'npm run build' in the frontend directory.",
            static_dir,
        )

    return app


# Module-level app instance consumed by uvicorn
app = create_app()
