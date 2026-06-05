"""
HAMq Consumer — REST + WebSocket API Routes
============================================
All HTTP routes and the WebSocket endpoint for real-time status streaming.

Route summary:
  POST  /api/auth/login         → obtain JWT
  GET   /api/health             → liveness check (no auth required)
  GET   /metrics                → Prometheus text format (no auth required)
  GET   /api/status             → ConsumerStatus (auth required)
  GET   /api/messages           → paginated message list (auth required)
  GET   /api/messages/recent    → last 100 messages (auth required)
  GET   /api/messages/missing   → gap detection for Arbiter (auth required)
  POST  /api/start              → start consuming (auth required)
  POST  /api/stop               → stop consuming (auth required)
  WS    /ws                     → real-time status stream (auth via query param)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from ..auth import authenticate_user, create_access_token, require_auth
from ..config import settings
from ..models import (
    ConsumerStatus,
    LoginRequest,
    MessagePage,
    ReceivedMessage,
    StatusUpdate,
    TokenResponse,
)
from ..consumer_service import ConsumerService

logger = logging.getLogger(__name__)

# The router is created here and mounted on the FastAPI app in main.py.
# We use a module-level variable for the ConsumerService that is injected
# at application startup.
_service: Optional[ConsumerService] = None

router = APIRouter()


def set_service(svc: ConsumerService) -> None:
    """
    Inject the ConsumerService singleton.
    Called from main.py during the lifespan startup hook.
    """
    global _service
    _service = svc


def _get_service() -> ConsumerService:
    """FastAPI dependency — raises 503 if the service is not yet initialised."""
    if _service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Consumer service not initialised",
        )
    return _service


# --------------------------------------------------------------------------- #
#  Auth
# --------------------------------------------------------------------------- #

@router.post(
    "/api/auth/login",
    response_model=TokenResponse,
    summary="Obtain a JWT access token",
    tags=["auth"],
)
async def login(body: LoginRequest) -> TokenResponse:
    """
    Authenticate with username + password.
    Returns a signed JWT that must be included as ``Authorization: Bearer <token>``
    on all protected endpoints.
    """
    if not authenticate_user(body.username, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    expire_delta = timedelta(minutes=settings.AUTH_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(body.username, expires_delta=expire_delta)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=int(expire_delta.total_seconds()),
    )


# --------------------------------------------------------------------------- #
#  Health
# --------------------------------------------------------------------------- #

@router.get(
    "/api/health",
    summary="Liveness / readiness probe",
    tags=["health"],
)
async def health() -> dict:
    """
    Always returns HTTP 200 with basic identity info.
    Used by Kubernetes liveness and readiness probes.
    No authentication required.
    """
    return {
        "status": "ok",
        "consumer_id": settings.CONSUMER_ID,
        "version": os.getenv("APP_VERSION", "1.0.0"),
    }


@router.get(
    "/api/version",
    summary="Component version",
    tags=["health"],
)
async def get_version() -> dict:
    return {"version": os.getenv("APP_VERSION", "1.0.0")}


# --------------------------------------------------------------------------- #
#  Prometheus metrics
# --------------------------------------------------------------------------- #

@router.get(
    "/metrics",
    summary="Prometheus metrics",
    tags=["observability"],
    include_in_schema=False,
)
async def prometheus_metrics() -> Response:
    """
    Expose all registered Prometheus metrics in the text exposition format.
    No authentication required so that Prometheus can scrape without credentials.
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# --------------------------------------------------------------------------- #
#  Status
# --------------------------------------------------------------------------- #

@router.get(
    "/api/status",
    response_model=ConsumerStatus,
    summary="Consumer operational status",
    tags=["consumer"],
)
async def get_status(
    _: str = Depends(require_auth),
    svc: ConsumerService = Depends(_get_service),
) -> ConsumerStatus:
    """Return a point-in-time snapshot of the consumer's operational state."""
    return svc.get_status()


# --------------------------------------------------------------------------- #
#  Message queries
# --------------------------------------------------------------------------- #

@router.get(
    "/api/messages",
    response_model=MessagePage,
    summary="Paginated message list",
    tags=["messages"],
)
async def list_messages(
    producer_id: Optional[str] = Query(None, description="Filter by producer_id"),
    seq_from: Optional[int] = Query(None, ge=1, description="Sequence range lower bound (inclusive)"),
    seq_to: Optional[int] = Query(None, ge=1, description="Sequence range upper bound (inclusive)"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=500, description="Messages per page"),
    _: str = Depends(require_auth),
    svc: ConsumerService = Depends(_get_service),
) -> MessagePage:
    """
    Return a paginated, optionally filtered list of received messages.

    This endpoint is used by the Arbiter to cross-reference sequences and
    by the frontend table view.
    """
    rows = await svc.store.get_all_messages(
        producer_id=producer_id,
        seq_from=seq_from,
        seq_to=seq_to,
        page=page,
        page_size=page_size,
    )
    total = await svc.store.get_total_count(
        producer_id=producer_id,
        seq_from=seq_from,
        seq_to=seq_to,
    )
    messages = [_row_to_model(r) for r in rows]
    return MessagePage(
        messages=messages,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/api/messages/recent",
    response_model=List[ReceivedMessage],
    summary="Most recently received messages",
    tags=["messages"],
)
async def recent_messages(
    limit: int = Query(100, ge=1, le=500, description="Maximum number of messages to return"),
    _: str = Depends(require_auth),
    svc: ConsumerService = Depends(_get_service),
) -> List[ReceivedMessage]:
    """Return the *limit* most recently received messages (by received_at DESC)."""
    rows = await svc.store.get_recent(limit=limit)
    return [_row_to_model(r) for r in rows]


@router.get(
    "/api/messages/missing",
    response_model=List[int],
    summary="Missing sequence numbers for a producer",
    tags=["messages"],
)
async def missing_sequences(
    producer_id: str = Query(..., description="Producer identity to inspect"),
    seq_from: int = Query(..., ge=1, description="Range lower bound (inclusive)"),
    seq_to: int = Query(..., ge=1, description="Range upper bound (inclusive)"),
    _: str = Depends(require_auth),
    svc: ConsumerService = Depends(_get_service),
) -> List[int]:
    """
    Return a list of sequence numbers in [seq_from, seq_to] for which no
    message has been received from *producer_id*.

    Used by the Arbiter for loss calculation.  Avoid very large ranges to
    prevent excessive memory use — prefer 10 000-element windows.
    """
    if seq_to - seq_from > 100_000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Range too large — maximum 100 000 sequences per request",
        )
    return await svc.store.get_missing_sequences(producer_id, seq_from, seq_to)


# --------------------------------------------------------------------------- #
#  Control plane
# --------------------------------------------------------------------------- #

@router.post(
    "/api/start",
    summary="Start consuming from Kafka",
    tags=["consumer"],
)
async def start_consumer(
    _: str = Depends(require_auth),
    svc: ConsumerService = Depends(_get_service),
) -> dict:
    """
    Begin (or resume) reading messages from the Kafka topic.
    Idempotent — safe to call when already running.
    """
    await svc.start()
    return {"status": "started", "consumer_id": settings.CONSUMER_ID}


@router.post(
    "/api/stop",
    summary="Stop consuming from Kafka",
    tags=["consumer"],
)
async def stop_consumer(
    _: str = Depends(require_auth),
    svc: ConsumerService = Depends(_get_service),
) -> dict:
    """
    Pause the Kafka consume loop without losing committed offsets.
    Call /api/start to resume.
    """
    await svc.stop()
    return {"status": "stopped", "consumer_id": settings.CONSUMER_ID}


# --------------------------------------------------------------------------- #
#  WebSocket
# --------------------------------------------------------------------------- #

@router.websocket("/ws")
async def websocket_status(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="JWT bearer token"),
    svc: ConsumerService = Depends(_get_service),
) -> None:
    """
    Real-time status stream.

    The client must supply a valid JWT as the ``token`` query parameter
    (e.g. ``ws://host/ws?token=eyJ...``) because browsers cannot set the
    ``Authorization`` header on WebSocket connections.

    The server emits a JSON StatusUpdate object every second.
    """
    # Validate the token before accepting the connection.
    if token is None:
        await websocket.close(code=4001, reason="Missing token")
        return

    from ..auth import _decode_token
    try:
        _decode_token(token)
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    logger.info("WebSocket client connected from %s", websocket.client)

    try:
        while True:
            status_obj = svc.get_status()
            recent_rows = await svc.store.get_recent(limit=50)
            recent = [_row_to_model(r) for r in recent_rows]

            update = StatusUpdate(
                type="status_update",
                status=status_obj,
                recent_messages=recent,
            )
            await websocket.send_text(update.model_dump_json())
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _row_to_model(row: dict) -> ReceivedMessage:
    """Convert a raw SQLite row dict to a ReceivedMessage Pydantic model."""
    return ReceivedMessage(
        id=row["id"],
        sequence=row["sequence"],
        producer_id=row["producer_id"],
        received_at=row["received_at"],
        timestamp=row["original_timestamp"],
        frequency_hz=row["frequency_hz"],
        payload_data=row["payload_data"],
        checksum_valid=bool(row["checksum_valid"]),
    )
