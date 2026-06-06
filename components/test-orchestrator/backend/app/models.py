from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class HistoryPoint(BaseModel):
    time: str
    sent: int
    received: Optional[int]
    send_rate: float
    recv_rate: float
    missing_count: int


class MissingEntry(BaseModel):
    number: int
    first_seen: str


class OrchestratorStatus(BaseModel):
    running: bool
    cycle: int
    # producer
    sent_counter: int
    total_sent: int
    send_rate: float
    # consumer
    recv_counter: Optional[int]
    total_received: int
    recv_rate: float
    # judge
    counter_max: int
    freq_hz: float
    missing_count: int
    completion_pct: float
    missing_sample: list[MissingEntry]
    # chart history
    history: list[HistoryPoint]


class ConfigUpdate(BaseModel):
    freq_hz: Optional[float] = None
    counter_max: Optional[int] = None
