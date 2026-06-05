"""
FastAPI route definitions for the HAMq Producer API.

Route summary
-------------
POST   /api/auth/login       — Authenticate and receive a JWT token (public)
GET    /api/health           — Liveness check (public)
GET    /metrics              — Prometheus metrics (public, scraped by Prometheus)
GET    /api/status           — Current ProducerStatus (protected)
POST   /api/start            — Start the message generation loop (protected)
POST   /api/stop             — Stop the message generation loop (protected)
PUT    /api/frequency        — Update the message frequency (protected)
GET    /api/messages/recent  — Last 100 generated messages (protected)
WS     /ws                   — Real-time status stream (protected via query param token)

All protected routes require the ``Authorization: Bearer <token>`` header
obtained from ``/api/auth/login``.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.auth import get_current_user, login_for_access_token
from app.api.websocket import websocket_status_handler
from app.models import (
    FrequencyUpdate,
    LoginRequest,
    ProducerStatus,
    TokenResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------

@router.post(
    "/api/auth/login",
    response_model=TokenResponse,
    summary="Authenticate and receive a JWT token",
    tags=["auth"],
)
async def login(request: LoginRequest) -> TokenResponse:
    """
    Validate username/password and return a JWT bearer token.

    The token is valid for ``AUTH_TOKEN_EXPIRE_MINUTES`` minutes (default 24h).
    """
    return await login_for_access_token(request)


@router.get(
    "/api/health",
    summary="Liveness check",
    tags=["ops"],
)
async def health(request: Request) -> Dict[str, str]:
    """
    Returns ``{"status": "ok"}`` unconditionally.

    Used by Kubernetes liveness and readiness probes.  No auth required so
    probes do not need credentials.
    """
    producer_service = request.app.state.producer_service
    return {
        "status": "ok",
        "producer_id": producer_service._producer_id,
    }


@router.get(
    "/api/version",
    summary="Component version",
    tags=["ops"],
)
async def get_version() -> Dict[str, str]:
    return {"version": os.getenv("APP_VERSION", "1.0.0")}


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    tags=["ops"],
)
async def prometheus_metrics() -> Response:
    """
    Expose Prometheus metrics in text format.

    Scraped by Prometheus via the ``prometheus.io/scrape: "true"`` pod
    annotation.  No auth required (metrics do not contain secrets).
    """
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Protected routes (require Bearer token)
# ---------------------------------------------------------------------------

@router.get(
    "/api/status",
    response_model=ProducerStatus,
    summary="Get current producer status",
    tags=["producer"],
)
@router.get(
    "/api/v1/producer/status",
    response_model=ProducerStatus,
    include_in_schema=False,
)
async def get_status(
    request: Request,
    _: str = Depends(get_current_user),
) -> ProducerStatus:
    """
    Return a snapshot of the producer's current state including:
    - running/stopped
    - current frequency
    - sequence counter
    - buffered message count
    - cumulative sent/error counts
    - Kafka connection health
    """
    producer_service = request.app.state.producer_service
    return await producer_service.async_get_status()


@router.post(
    "/api/start",
    response_model=ProducerStatus,
    summary="Start the message generation loop",
    tags=["producer"],
)
@router.post("/api/v1/producer/start", response_model=ProducerStatus, include_in_schema=False)
async def start_producer(
    request: Request,
    _: str = Depends(get_current_user),
) -> ProducerStatus:
    """
    Begin producing messages at the currently configured frequency.

    Idempotent — calling start when already running is safe.
    Returns the current ProducerStatus after the operation.
    """
    producer_service = request.app.state.producer_service
    await producer_service.start_producing()
    return await producer_service.async_get_status()


@router.post(
    "/api/stop",
    response_model=ProducerStatus,
    summary="Stop the message generation loop",
    tags=["producer"],
)
@router.post("/api/v1/producer/stop", response_model=ProducerStatus, include_in_schema=False)
async def stop_producer(
    request: Request,
    _: str = Depends(get_current_user),
) -> ProducerStatus:
    """
    Halt message generation.

    Messages already in the local buffer continue to be delivered to Kafka
    in the background even after the producer is stopped.
    Returns the current ProducerStatus after the operation.
    """
    producer_service = request.app.state.producer_service
    await producer_service.stop_producing()
    return await producer_service.async_get_status()


@router.put(
    "/api/frequency",
    response_model=ProducerStatus,
    summary="Update message generation frequency",
    tags=["producer"],
)
@router.put("/api/v1/producer/frequency", response_model=ProducerStatus, include_in_schema=False)
async def update_frequency(
    body: FrequencyUpdate,
    request: Request,
    _: str = Depends(get_current_user),
) -> ProducerStatus:
    """
    Change the message generation rate to *frequency_hz* messages per second.

    Valid range: 1–1000 Hz.  The new rate takes effect on the very next loop
    iteration without restarting the producer.
    Returns the current ProducerStatus reflecting the new frequency.
    """
    if not (1.0 <= body.frequency_hz <= 1000.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="frequency_hz must be between 1.0 and 1000.0",
        )
    producer_service = request.app.state.producer_service
    await producer_service.set_frequency(body.frequency_hz)
    return await producer_service.async_get_status()


@router.get(
    "/api/messages/recent",
    summary="Get the last N generated messages",
    tags=["producer"],
)
async def get_recent_messages(
    request: Request,
    _: str = Depends(get_current_user),
    limit: int = 50,
) -> List[Dict[str, Any]]:
    producer_service = request.app.state.producer_service
    return producer_service.get_recent_messages()[-limit:]


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
) -> None:
    """
    WebSocket endpoint — streams ProducerStatus JSON every second.

    Authentication: pass the JWT token as a query parameter ``token``
    (e.g. ``ws://host/ws?token=<jwt>``).  This is necessary because
    browser WebSocket APIs cannot set custom headers.

    The connection is closed with code 4001 if the token is missing or
    invalid.
    """
    from jose import JWTError, jwt
    from app.config import settings as cfg

    # Validate JWT from query parameter
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001)
        return

    try:
        payload = jwt.decode(token, cfg.AUTH_SECRET_KEY, algorithms=["HS256"])
        if payload.get("sub") is None:
            raise JWTError("no sub claim")
    except JWTError:
        await websocket.close(code=4001)
        return

    producer_service = websocket.app.state.producer_service
    await websocket_status_handler(websocket, producer_service)
