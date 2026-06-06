from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import settings
from app.counter_producer import CounterProducer
from app.counter_consumer import CounterConsumer
from app.judge import Judge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("HAMq Test Orchestrator starting")

    judge = Judge(max_val=settings.COUNTER_MAX)
    prod = CounterProducer()
    cons = CounterConsumer(judge=judge)

    app.state.judge = judge
    app.state.prod = prod
    app.state.cons = cons
    app.state.running = False
    app.state.freq_hz = settings.FREQ_HZ
    app.state.counter_max = settings.COUNTER_MAX
    app.state.history = []
    app.state.history_tick = 0

    if settings.AUTOSTART:
        logger.info("AUTOSTART=true — starting test immediately")
        app.state.running = True
        await prod.start(settings.FREQ_HZ, settings.COUNTER_MAX)
        await cons.start()

    logger.info("HAMq Test Orchestrator ready")
    yield

    logger.info("Shutting down …")
    if app.state.running:
        await prod.stop()
        await cons.stop()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="HAMq Test Orchestrator",
        description="End-to-end counter integrity test for the HAMq databus.",
        version=os.getenv("APP_VERSION", "1.0.0"),
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    cors_raw = settings.CORS_ORIGINS.strip()
    cors_origins = ["*"] if cors_raw == "*" else [o.strip() for o in cors_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        logger.info("Serving React frontend from %s", static_dir)
        index = static_dir / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def _spa_fallback(full_path: str) -> FileResponse:
            candidate = static_dir / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(index))

        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_app()
