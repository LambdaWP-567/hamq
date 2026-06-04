"""
Pydantic data models for the HAMq Arbiter.

These models represent the domain objects used throughout the Arbiter:
audit results stored in SQLite, reconciliation reports returned from the API,
the arbiter's own operational status, and alert events sent to webhooks.

All models use strict typing so serialisation errors surface at the boundary
rather than propagating silently into storage or downstream consumers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core audit types
# ---------------------------------------------------------------------------

class AuditResult(BaseModel):
    """
    Full audit result for a single producer over one reconciliation window.

    Stored in SQLite.  The ``missing_sequences`` list may be large (up to
    RECONCILE_LOOKBACK_MESSAGES entries) so it is excluded from list views
    and returned only when fetching a specific audit by ID.
    """

    audit_id: str = Field(
        ...,
        description="UUID4 identifier for this audit record"
    )
    timestamp: str = Field(
        ...,
        description="ISO-8601 UTC timestamp when this audit was computed"
    )
    producer_id: str = Field(
        ...,
        description="Identifier of the producer this audit covers"
    )
    sent_count: int = Field(
        ...,
        ge=0,
        description="Number of messages the producer reported sending in the window"
    )
    received_count: int = Field(
        ...,
        ge=0,
        description="Number of those messages the consumer confirmed receiving"
    )
    missing_sequences: list[int] = Field(
        default_factory=list,
        description="Sorted list of sequence numbers present at producer but absent at consumer"
    )
    loss_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of sent messages that were not received (0.0 = no loss)"
    )
    status: Literal["ok", "warning", "critical"] = Field(
        ...,
        description=(
            "Severity based on loss_rate: "
            "'ok' = 0 loss, 'warning' = loss < threshold, 'critical' = loss >= threshold"
        )
    )


class AuditSummary(BaseModel):
    """
    Lightweight audit view used in list endpoints — omits missing_sequences
    to keep response payloads small when returning many records.
    """

    audit_id: str = Field(..., description="UUID4 identifier for this audit record")
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp of the audit")
    producer_id: str = Field(..., description="Producer this audit covers")
    sent_count: int = Field(..., ge=0, description="Messages sent by producer")
    received_count: int = Field(..., ge=0, description="Messages confirmed received")
    loss_rate: float = Field(..., ge=0.0, le=1.0, description="Loss fraction")
    status: Literal["ok", "warning", "critical"] = Field(..., description="Severity label")


# ---------------------------------------------------------------------------
# Per-producer result used inside a ReconcileReport
# ---------------------------------------------------------------------------

class ProducerAuditResult(BaseModel):
    """
    Per-producer summary embedded inside a ``ReconcileReport``.

    A ReconcileReport covers all producers polled in a single reconcile pass;
    each producer gets one ProducerAuditResult.
    """

    audit_id: str = Field(..., description="Audit ID persisted to the database")
    producer_id: str = Field(..., description="Producer identifier")
    producer_url: str = Field(..., description="Base URL of the producer API that was polled")
    sent_count: int = Field(..., ge=0, description="Sequences seen at producer")
    received_count: int = Field(..., ge=0, description="Sequences confirmed at consumer")
    missing_count: int = Field(..., ge=0, description="Number of missing sequences")
    missing_sequences: list[int] = Field(
        default_factory=list,
        description="Sorted list of missing sequence numbers (may be large)"
    )
    loss_rate: float = Field(..., ge=0.0, le=1.0, description="Loss fraction for this producer")
    status: Literal["ok", "warning", "critical"] = Field(..., description="Severity label")


# ---------------------------------------------------------------------------
# Reconcile report — top-level result of one reconcile pass
# ---------------------------------------------------------------------------

class ReconcileReport(BaseModel):
    """
    Aggregated result of a single reconciliation pass across all producers.

    One report is generated per reconcile pass (triggered either by the
    background loop or by POST /api/reconcile).  It is returned immediately
    from the manual reconcile endpoint and broadcast over the WebSocket.
    """

    report_id: str = Field(
        ...,
        description="UUID4 identifier for this report"
    )
    timestamp: str = Field(
        ...,
        description="ISO-8601 UTC timestamp when the reconcile pass started"
    )
    producers: list[ProducerAuditResult] = Field(
        default_factory=list,
        description="Per-producer audit results included in this pass"
    )
    total_sent: int = Field(
        ...,
        ge=0,
        description="Sum of sent_count across all producers"
    )
    total_received: int = Field(
        ...,
        ge=0,
        description="Sum of received_count across all producers"
    )
    total_missing: int = Field(
        ...,
        ge=0,
        description="Sum of missing_count across all producers"
    )
    overall_loss_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Total missing / total sent (0.0 when nothing was sent)"
    )
    duration_ms: float = Field(
        ...,
        ge=0.0,
        description="Wall-clock time in milliseconds to complete the reconcile pass"
    )


# ---------------------------------------------------------------------------
# Arbiter operational status
# ---------------------------------------------------------------------------

class ArbiterStatus(BaseModel):
    """
    Live operational snapshot of the Arbiter, returned by GET /api/status
    and streamed periodically over the WebSocket channel.
    """

    arbiter_id: str = Field(..., description="This arbiter's unique ID")
    running: bool = Field(
        ...,
        description="True while the background reconcile loop is active"
    )
    last_reconcile_at: Optional[str] = Field(
        default=None,
        description="ISO-8601 UTC timestamp of the most recent reconcile pass (None if not run yet)"
    )
    last_loss_rate: Optional[float] = Field(
        default=None,
        description="overall_loss_rate from the most recent reconcile pass"
    )
    producers_monitored: int = Field(
        ...,
        ge=0,
        description="Number of producer URLs currently being polled"
    )
    total_audits: int = Field(
        ...,
        ge=0,
        description="Total audit records stored in the database"
    )


# ---------------------------------------------------------------------------
# Alert event
# ---------------------------------------------------------------------------

class AlertEvent(BaseModel):
    """
    Payload POSTed to the configured ALERT_WEBHOOK_URL when loss rate
    exceeds the configured threshold.  A webhook receiver (e.g., PagerDuty,
    Slack incoming-webhooks, Alertmanager) can parse this JSON body.
    """

    timestamp: str = Field(
        ...,
        description="ISO-8601 UTC timestamp when the alert was generated"
    )
    producer_id: str = Field(
        ...,
        description="Producer that triggered the alert"
    )
    loss_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Observed loss rate that exceeded the threshold"
    )
    missing_count: int = Field(
        ...,
        ge=0,
        description="Number of missing messages in this reconcile window"
    )
    threshold: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="The configured ALERT_LOSS_RATE_THRESHOLD that was crossed"
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    """JWT token returned after a successful login."""

    access_token: str = Field(..., description="Signed JWT bearer token")
    token_type: str = Field(default="bearer", description="Always 'bearer'")


class LoginRequest(BaseModel):
    """Credentials submitted to POST /api/auth/login."""

    username: str = Field(..., description="API username")
    password: str = Field(..., description="API password (plain text, transmitted over TLS)")


# ---------------------------------------------------------------------------
# Aggregate stats
# ---------------------------------------------------------------------------

class AuditStats(BaseModel):
    """
    Aggregated statistics across all stored audit records.
    Returned by GET /api/stats.
    """

    total_audits: int = Field(..., ge=0, description="Total number of audit records in the database")
    avg_loss_rate: float = Field(
        ...,
        ge=0.0,
        description="Average loss_rate across all stored audits"
    )
    worst_producer: Optional[str] = Field(
        default=None,
        description="producer_id with the highest average loss rate (None when no data)"
    )
    worst_loss_rate: float = Field(
        default=0.0,
        description="Highest average loss_rate observed for any single producer"
    )
    producers_tracked: int = Field(
        ...,
        ge=0,
        description="Number of distinct producer IDs in the database"
    )
