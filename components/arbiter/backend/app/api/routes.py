"""
API route handlers for the HAMq Arbiter.

All endpoints except /api/health, /metrics, and /api/auth/login require a
valid JWT Bearer token obtained from POST /api/auth/login.

Route map
---------
  POST   /api/auth/login        → TokenResponse (no auth required)
  GET    /api/health            → {"status": "ok"}  (no auth required)
  GET    /metrics               → Prometheus text format (no auth required)
  GET    /api/status            → ArbiterStatus
  POST   /api/reconcile         → ReconcileReport  (trigger manual pass)
  GET    /api/audits            → list[AuditSummary]  (?producer_id= &limit=)
  GET    /api/audits/{audit_id} → AuditResult  (includes missing_sequences)
  GET    /api/stats             → AuditStats
  POST   /api/start             → {"message": "..."}
  POST   /api/stop              → {"message": "..."}
  WS     /ws                    → real-time JSON status stream

The WebSocket endpoint streams the current ArbiterStatus as JSON every 2 s
and also sends a ReconcileReport JSON blob after each reconcile pass.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.security import OAuth2PasswordBearer
import bcrypt as _bcrypt
from jose import JWTError, jwt
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.audit_store import AuditStore
from app.config import settings
from app.models import (
    ArbiterStatus,
    AuditResult,
    AuditStats,
    AuditSummary,
    LoginRequest,
    ReconcileReport,
    TokenResponse,
)
from app.reconciler import Reconciler

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

ALGORITHM = "HS256"


def _verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _create_access_token(sub: str, expires_delta: timedelta) -> str:
    """
    Mint a signed JWT.

    Parameters
    ----------
    sub:
        Subject claim (typically the username).
    expires_delta:
        Token validity window.
    """
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": sub, "exp": expire}
    return jwt.encode(payload, settings.AUTH_SECRET_KEY, algorithm=ALGORITHM)


async def _get_current_user(
    token: Annotated[Optional[str], Depends(_oauth2_scheme)],
) -> str:
    """
    FastAPI dependency that validates the Bearer JWT and returns the username.

    Raises HTTP 401 if the token is missing or invalid.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_exc

    try:
        payload = jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    return username


# Type alias for the authenticated user dependency
CurrentUser = Annotated[str, Depends(_get_current_user)]


# ---------------------------------------------------------------------------
# Helper to access shared state injected by main.py
# ---------------------------------------------------------------------------

def _get_store(request: Request) -> AuditStore:
    """Extract the AuditStore from application state."""
    return request.app.state.audit_store


def _get_reconciler(request: Request) -> Reconciler:
    """Extract the Reconciler from application state."""
    return request.app.state.reconciler


# ---------------------------------------------------------------------------
# Auth endpoints (no authentication required)
# ---------------------------------------------------------------------------

@router.post(
    "/api/auth/login",
    response_model=TokenResponse,
    summary="Obtain a JWT access token",
    tags=["auth"],
)
async def login(request: LoginRequest):
    """
    Validate username + password (JSON body) and return a signed JWT.

    The token is valid for AUTH_TOKEN_EXPIRE_MINUTES minutes (default: 24 h).
    Include it in subsequent requests as ``Authorization: Bearer <token>``.
    """
    if request.username != settings.AUTH_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not _verify_password(request.password, settings.AUTH_PASSWORD_HASH):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = _create_access_token(
        sub=request.username,
        expires_delta=timedelta(minutes=settings.AUTH_TOKEN_EXPIRE_MINUTES),
    )
    return TokenResponse(access_token=token)


# ---------------------------------------------------------------------------
# Health + metrics (public, no auth)
# ---------------------------------------------------------------------------

@router.get(
    "/api/health",
    summary="Liveness/readiness probe",
    tags=["health"],
)
async def health():
    """
    Returns {"status": "ok"} if the service is running.
    Kubernetes liveness and readiness probes target this endpoint.
    """
    return {"status": "ok"}


@router.get(
    "/api/version",
    summary="Component version",
    tags=["health"],
)
async def get_version():
    return {"version": os.getenv("APP_VERSION", "1.0.0")}


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    tags=["monitoring"],
)
async def metrics():
    """
    Expose Prometheus metrics in text exposition format.

    Scraped by the Prometheus Operator's PodMonitor or a manual scrape config.
    No authentication is required (metrics should be protected at the network
    level via Kubernetes NetworkPolicy).
    """
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get(
    "/api/status",
    response_model=ArbiterStatus,
    summary="Current Arbiter status",
    tags=["arbiter"],
)
async def get_status(
    _user: CurrentUser,
    request: Request,
):
    """
    Return the current operational state of the Arbiter.

    Includes whether the reconcile loop is running, the timestamp of the most
    recent pass, the last observed overall loss rate, and the number of audits
    stored in the database.
    """
    reconciler: Reconciler = _get_reconciler(request)
    store: AuditStore = _get_store(request)

    status_snapshot = reconciler.get_status()

    # Fill in the live total_audits count from the database
    stats = await store.get_stats()
    return ArbiterStatus(
        arbiter_id=status_snapshot.arbiter_id,
        running=status_snapshot.running,
        last_reconcile_at=status_snapshot.last_reconcile_at,
        last_loss_rate=status_snapshot.last_loss_rate,
        producers_monitored=status_snapshot.producers_monitored,
        total_audits=stats["total_audits"],
    )


# ---------------------------------------------------------------------------
# Manual reconcile trigger
# ---------------------------------------------------------------------------

@router.post(
    "/api/reconcile",
    response_model=ReconcileReport,
    summary="Trigger a manual reconciliation pass",
    tags=["arbiter"],
)
async def trigger_reconcile(
    _user: CurrentUser,
    request: Request,
):
    """
    Immediately run a reconcile pass and return the resulting ReconcileReport.

    This is useful for on-demand checks without waiting for the next scheduled
    interval.  The result is also persisted to the database and metrics are updated
    just as for a scheduled pass.
    """
    reconciler: Reconciler = _get_reconciler(request)
    try:
        report = await reconciler.run_once()
    except Exception as exc:
        logger.exception("Manual reconcile failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reconcile failed: {exc}",
        )
    return report


# ---------------------------------------------------------------------------
# Audit history
# ---------------------------------------------------------------------------

@router.get(
    "/api/audits",
    response_model=list[AuditSummary],
    summary="Paginated audit history",
    tags=["audits"],
)
async def list_audits(
    _user: CurrentUser,
    request: Request,
    producer_id: Optional[str] = Query(
        default=None,
        description="Filter to a specific producer_id; omit to return all producers"
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of audit summaries to return (most-recent first)"
    ),
):
    """
    Return a paginated list of AuditSummary records, ordered by timestamp descending.

    Use the ``producer_id`` query param to filter results for a specific producer.
    Use the ``limit`` param to control page size (max 1000 per request).

    The full ``missing_sequences`` list is excluded for performance; fetch
    ``GET /api/audits/{audit_id}`` to retrieve the complete record.
    """
    store: AuditStore = _get_store(request)
    return await store.get_history(producer_id=producer_id, limit=limit)


@router.get(
    "/api/audits/{audit_id}",
    response_model=AuditResult,
    summary="Full audit result with missing sequences",
    tags=["audits"],
)
async def get_audit(
    audit_id: str,
    _user: CurrentUser,
    request: Request,
):
    """
    Return the full AuditResult for a specific audit_id, including the
    complete ``missing_sequences`` list.

    Returns HTTP 404 if the audit_id does not exist.
    """
    store: AuditStore = _get_store(request)
    result = await store.get_result(audit_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit '{audit_id}' not found",
        )
    return result


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------

@router.get(
    "/api/stats",
    response_model=AuditStats,
    summary="Aggregate audit statistics",
    tags=["audits"],
)
async def get_stats(
    _user: CurrentUser,
    request: Request,
):
    """
    Return aggregate statistics computed over all stored audit records.

    Includes total audit count, average loss rate, worst-performing producer,
    and number of distinct producers tracked.
    """
    store: AuditStore = _get_store(request)
    raw = await store.get_stats()
    return AuditStats(
        total_audits=raw["total_audits"],
        avg_loss_rate=raw["avg_loss_rate"],
        worst_producer=raw["worst_producer"],
        worst_loss_rate=raw["worst_loss_rate"],
        producers_tracked=raw["producers_tracked"],
    )


# ---------------------------------------------------------------------------
# Reconciler start / stop
# ---------------------------------------------------------------------------

@router.post(
    "/api/start",
    summary="Start the background reconcile loop",
    tags=["arbiter"],
)
async def start_reconciler(
    _user: CurrentUser,
    request: Request,
):
    """
    Start the background reconciliation loop if it is not already running.

    The loop runs every RECONCILE_INTERVAL_S seconds.  Has no effect if the
    loop is already active.
    """
    reconciler: Reconciler = _get_reconciler(request)
    if reconciler.get_status().running:
        return {"message": "Reconciler is already running"}
    await reconciler.start()
    return {"message": "Reconciler started"}


@router.post(
    "/api/stop",
    summary="Stop the background reconcile loop",
    tags=["arbiter"],
)
async def stop_reconciler(
    _user: CurrentUser,
    request: Request,
):
    """
    Stop the background reconciliation loop.

    In-flight reconcile passes are allowed to finish before the loop exits.
    A subsequent POST /api/start will resume reconciliation.
    """
    reconciler: Reconciler = _get_reconciler(request)
    if not reconciler.get_status().running:
        return {"message": "Reconciler is not running"}
    await reconciler.stop()
    return {"message": "Reconciler stopped"}


# ---------------------------------------------------------------------------
# WebSocket — real-time status stream
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    request: Request,
):
    """
    WebSocket endpoint for real-time status streaming.

    On connection, the server streams:
      - Current ArbiterStatus as JSON every 2 seconds
      - ReconcileReport JSON immediately after each completed reconcile pass

    The token can be passed as a query parameter:
      ws://host/ws?token=<jwt>

    Authentication is optional (the UI may skip it on internal networks).
    If a token is provided and invalid, the connection is rejected.
    """
    # Optional token validation via query param
    token = websocket.query_params.get("token")
    if token:
        try:
            payload = jwt.decode(token, settings.AUTH_SECRET_KEY, algorithms=[ALGORITHM])
            if not payload.get("sub"):
                await websocket.close(code=4001)
                return
        except JWTError:
            await websocket.close(code=4001)
            return

    await websocket.accept()
    reconciler: Reconciler = _get_reconciler(request)
    store: AuditStore = _get_store(request)

    last_report_id: Optional[str] = None

    try:
        while True:
            # Build current status with live audit count
            status_snap = reconciler.get_status()
            stats = await store.get_stats()
            current_status = ArbiterStatus(
                arbiter_id=status_snap.arbiter_id,
                running=status_snap.running,
                last_reconcile_at=status_snap.last_reconcile_at,
                last_loss_rate=status_snap.last_loss_rate,
                producers_monitored=status_snap.producers_monitored,
                total_audits=stats["total_audits"],
            )

            await websocket.send_json({
                "type": "status",
                "data": current_status.model_dump(),
            })

            # If a new reconcile report is available since our last push, send it
            latest_report = reconciler._last_report
            if (
                latest_report is not None
                and latest_report.report_id != last_report_id
            ):
                await websocket.send_json({
                    "type": "report",
                    "data": latest_report.model_dump(),
                })
                last_report_id = latest_report.report_id

            await asyncio.sleep(2)

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
        try:
            await websocket.close()
        except Exception:
            pass
