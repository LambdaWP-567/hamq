from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, Query, status

from app.auth import get_current_user, login_for_access_token
from app.config import settings
from app.models import ConfigUpdate, LoginRequest, MissingEntry, OrchestratorStatus, TokenResponse

router = APIRouter()


# ── Public ────────────────────────────────────────────────────────────────────

@router.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(request: LoginRequest) -> TokenResponse:
    return await login_for_access_token(request)


@router.get("/api/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}


@router.get("/api/version", tags=["ops"])
async def version() -> dict:
    return {"version": os.getenv("APP_VERSION", "1.0.0")}


# ── Protected ─────────────────────────────────────────────────────────────────

@router.get("/api/status", response_model=OrchestratorStatus, tags=["orchestrator"])
async def get_status(request: Request, _: str = Depends(get_current_user)) -> OrchestratorStatus:
    return _build_status(request)


@router.post("/api/start", tags=["orchestrator"])
async def start_test(request: Request, _: str = Depends(get_current_user)) -> dict:
    state = request.app.state
    if state.running:
        return {"ok": True, "message": "already running"}
    state.running = True
    freq = state.freq_hz
    max_val = state.counter_max
    state.judge.reset()
    state.prod.sent_counter = 0
    state.prod.total_sent = 0
    state.prod.send_rate = 0.0
    state.cons.recv_counter = None
    state.cons.total_received = 0
    state.cons.recv_rate = 0.0
    state.history.clear()
    state.history_tick = 0
    await state.prod.start(freq, max_val)
    await state.cons.start()
    return {"ok": True}


@router.post("/api/stop", tags=["orchestrator"])
async def stop_test(request: Request, _: str = Depends(get_current_user)) -> dict:
    state = request.app.state
    if not state.running:
        return {"ok": True, "message": "not running"}
    state.running = False
    await state.prod.stop()
    await state.cons.stop()
    return {"ok": True}


@router.put("/api/config", tags=["orchestrator"])
async def update_config(
    body: ConfigUpdate,
    request: Request,
    _: str = Depends(get_current_user),
) -> dict:
    state = request.app.state
    if body.freq_hz is not None:
        state.freq_hz = max(0.1, min(body.freq_hz, 1000.0))
        state.prod.freq_hz = state.freq_hz
    if body.counter_max is not None:
        state.counter_max = max(10, body.counter_max)
    return {"freq_hz": state.freq_hz, "counter_max": state.counter_max}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_status(websocket: WebSocket, token: Optional[str] = Query(None)) -> None:
    from app.auth import get_current_user as _gcv
    from fastapi.security import OAuth2PasswordBearer
    from jose import JWTError, jwt
    from app.config import settings as cfg

    # Validate JWT from query param
    try:
        payload = jwt.decode(token or "", cfg.AUTH_SECRET_KEY, algorithms=["HS256"])
        if payload.get("sub") is None:
            await websocket.close(code=4001)
            return
    except (JWTError, Exception):
        await websocket.close(code=4001)
        return

    await websocket.accept()
    try:
        while True:
            status_obj = _build_status(websocket)
            await websocket.send_text(status_obj.model_dump_json())
            await asyncio.sleep(1.0)
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_status(req) -> OrchestratorStatus:
    state = req.app.state
    judge = state.judge
    prod = state.prod
    cons = state.cons
    missing = judge.missing()
    now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")

    point = {
        "time": now_str,
        "sent": prod.sent_counter,
        "received": cons.recv_counter,
        "send_rate": round(prod.send_rate, 2),
        "recv_rate": round(cons.recv_rate, 2),
        "missing_count": len(missing),
    }
    history: list = state.history
    if state.running:
        state.history_tick += 1
        if state.history_tick % 4 == 0:
            history.append(point)
            if len(history) > 30:
                history.pop(0)

    return OrchestratorStatus(
        running=state.running,
        cycle=judge.cycle,
        sent_counter=prod.sent_counter,
        total_sent=prod.total_sent,
        send_rate=round(prod.send_rate, 2),
        recv_counter=cons.recv_counter,
        total_received=cons.total_received,
        recv_rate=round(cons.recv_rate, 2),
        counter_max=state.counter_max,
        freq_hz=state.freq_hz,
        missing_count=len(missing),
        completion_pct=round(judge.completion_pct(), 1),
        missing_sample=[MissingEntry(number=n, first_seen=ts) for n, ts in judge.missing_with_timestamps()[:20]],
        history=history[-30:],
    )
