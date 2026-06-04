"""
Pydantic data models for the HAMq Producer.

These models are shared between the API layer, the business logic,
and the Kafka serialisation layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class MessagePayload(BaseModel):
    """
    Inner payload carried inside every HAMq message.

    The `data` field holds the actual content (base64-encoded bytes or a
    plain string); `checksum` is the SHA-256 hex digest of `data` and is
    verified by consumers to detect corruption in transit.
    """

    data: str = Field(..., description="Message content (base64 or plain string)")
    checksum: str = Field(
        ...,
        description="SHA-256 hex digest of the data field"
    )


class Message(BaseModel):
    """
    A single HAMq message as published to Kafka.

    The combination of (producer_id, sequence) is unique per producer
    instance and can be used by consumers for deduplication.
    """

    id: str = Field(..., description="UUID4 message identifier")
    sequence: int = Field(
        ...,
        ge=1,
        description="Monotonically increasing counter, unique within the producer"
    )
    producer_id: str = Field(
        ...,
        description="Identifier of the producer instance that generated this message"
    )
    timestamp: str = Field(
        ...,
        description="ISO-8601 UTC timestamp of message creation (millisecond precision)"
    )
    frequency_hz: float = Field(
        ...,
        description="Configured frequency (msg/s) at the time of message generation"
    )
    payload: MessagePayload = Field(..., description="Inner payload with data + checksum")

    @field_validator("sequence")
    @classmethod
    def sequence_must_be_positive(cls, v: int) -> int:
        """Ensure the sequence counter is strictly positive."""
        if v < 1:
            raise ValueError("sequence must be a positive integer (>= 1)")
        return v


class ProducerStatus(BaseModel):
    """
    Snapshot of the current producer state, returned by GET /api/status
    and streamed over the WebSocket connection.
    """

    producer_id: str = Field(..., description="This producer's unique ID")
    running: bool = Field(..., description="True while the message-generation loop is active")
    frequency_hz: float = Field(..., description="Current message generation frequency")
    sequence_counter: int = Field(
        ...,
        description="Last sequence number used (0 means no messages sent yet)"
    )
    buffered_count: int = Field(
        ...,
        description="Number of messages currently in the local SQLite buffer awaiting delivery"
    )
    sent_count: int = Field(
        ...,
        description="Total messages successfully delivered to Kafka in this session"
    )
    error_count: int = Field(
        ...,
        description="Total send errors encountered in this session"
    )
    kafka_connected: bool = Field(
        ...,
        description="True when the Kafka producer is connected and healthy"
    )


class FrequencyUpdate(BaseModel):
    """Request body for PUT /api/frequency."""

    frequency_hz: float = Field(
        ...,
        ge=1.0,
        le=1000.0,
        description="New message generation frequency in messages per second"
    )


class StartStopRequest(BaseModel):
    """Request body for POST /api/start and POST /api/stop."""

    action: Literal["start", "stop"] = Field(
        ...,
        description="'start' to begin producing, 'stop' to halt"
    )


class TokenResponse(BaseModel):
    """JWT token response returned after a successful login."""

    access_token: str = Field(..., description="Signed JWT bearer token")
    token_type: str = Field(default="bearer", description="Always 'bearer'")


class LoginRequest(BaseModel):
    """Credentials submitted to POST /api/auth/login."""

    username: str = Field(..., description="API username")
    password: str = Field(..., description="API password (plain text, transmitted over TLS)")
