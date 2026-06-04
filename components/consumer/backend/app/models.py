"""
HAMq Consumer — Data Models
=============================
Pydantic models used by the REST API and internally between layers.
All datetime fields are serialised as ISO-8601 strings so they are
straightforward to consume from any language.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
#  Domain models
# --------------------------------------------------------------------------- #

class ReceivedMessage(BaseModel):
    """
    One message as stored in SQLite and served to the Arbiter.
    The `checksum_valid` flag indicates whether the SHA-256 checksum of
    `payload.data` matched the `payload.checksum` field in the wire message.
    """

    id: str = Field(..., description="UUID v4 message identifier from producer")
    sequence: int = Field(..., description="Monotonically increasing per-producer sequence")
    producer_id: str = Field(..., description="Kubernetes Pod name of the originating producer")
    received_at: str = Field(..., description="ISO-8601 UTC timestamp when consumer persisted this message")
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp from the producer (original)")
    frequency_hz: float = Field(..., description="Publish frequency configured on the producer at send time")
    payload_data: str = Field(..., description="Payload data field (base64 or string)")
    checksum_valid: bool = Field(..., description="True if payload checksum verified successfully")


class ConsumerStatus(BaseModel):
    """
    Live operational status of the consumer, returned by GET /api/status
    and streamed over the WebSocket endpoint.
    """

    consumer_id: str = Field(..., description="Logical identifier of this consumer instance")
    running: bool = Field(..., description="True when the Kafka consume loop is active")
    kafka_connected: bool = Field(..., description="True when the Kafka connection is healthy")
    received_count: int = Field(0, description="Total number of messages received and persisted")
    last_sequence_by_producer: Dict[str, int] = Field(
        default_factory=dict,
        description="Most recent sequence number seen per producer_id"
    )
    lag_estimate: int = Field(
        0,
        description="Estimated number of messages behind the latest Kafka offset"
    )
    checksum_errors: int = Field(0, description="Number of messages with invalid checksums since start")


class MessageQuery(BaseModel):
    """
    Filter parameters for querying persisted messages.
    Used by the Arbiter to verify which sequences have been received.
    """

    producer_id: Optional[str] = Field(None, description="Filter by producer identity (Pod name)")
    sequence_from: int = Field(1, ge=1, description="Lower bound of sequence range (inclusive)")
    sequence_to: int = Field(1_000_000_000, ge=1, description="Upper bound of sequence range (inclusive)")


class MessagePage(BaseModel):
    """
    Paginated response for GET /api/messages.
    """

    messages: List[ReceivedMessage] = Field(..., description="Messages in this page")
    total: int = Field(..., description="Total number of messages matching the query")
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Maximum messages per page")


# --------------------------------------------------------------------------- #
#  Auth models
# --------------------------------------------------------------------------- #

class LoginRequest(BaseModel):
    """Credentials supplied to POST /api/auth/login."""

    username: str = Field(..., description="Admin username (must match AUTH_USERNAME env var)")
    password: str = Field(..., description="Admin password (verified against AUTH_PASSWORD_HASH)")


class TokenResponse(BaseModel):
    """JWT response returned after successful login."""

    access_token: str = Field(..., description="Signed JWT bearer token")
    token_type: str = Field("bearer", description="Always 'bearer'")
    expires_in: int = Field(..., description="Token validity in seconds")


# --------------------------------------------------------------------------- #
#  WebSocket push model
# --------------------------------------------------------------------------- #

class StatusUpdate(BaseModel):
    """
    Message sent over the WebSocket connection every second.
    Carries the full ConsumerStatus plus a recent-messages snapshot.
    """

    type: str = Field("status_update", description="Message type discriminator")
    status: ConsumerStatus
    recent_messages: List[ReceivedMessage] = Field(
        default_factory=list,
        description="Last few messages received (up to 10)"
    )
