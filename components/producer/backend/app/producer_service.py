"""
ProducerService — message generation orchestration for HAMq Producer.

Responsibilities
----------------
- Runs an asyncio loop that generates messages at the configured frequency.
- Maintains a monotonically increasing per-producer sequence counter.
- Delegates Kafka delivery (with buffering) to ResilientKafkaProducer.
- Maintains an in-memory ring buffer of the last 100 sent messages for
  the /api/messages/recent endpoint.
- Exposes a get_status() method consumed by the REST API and WebSocket handler.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from app.config import settings
from app.metrics import messages_sent_rate
from app.models import Message, MessagePayload, ProducerStatus

logger = logging.getLogger(__name__)

# In-memory ring buffer capacity for recent messages
_RECENT_MESSAGES_CAPACITY = 50


class ProducerService:
    """
    Manages the message generation loop for a single producer instance.

    The service is intentionally decoupled from the Kafka/buffer layer:
    it hands each generated message to the injected ``kafka_producer`` and
    the ``kafka_producer`` is responsible for buffering + delivery.

    Parameters
    ----------
    kafka_producer:
        A :class:`~app.kafka_producer.ResilientKafkaProducer` instance
        that has already been started.
    buffer:
        The shared :class:`~app.buffer.MessageBuffer` instance (used only
        to report buffered_count in get_status()).
    """

    def __init__(self, kafka_producer: Any, buffer: Any) -> None:
        self._kafka_producer = kafka_producer
        self._buffer = buffer

        # Configuration (mutable at runtime via set_frequency())
        self._producer_id: str = settings.PRODUCER_ID
        self._frequency_hz: float = settings.PRODUCER_FREQUENCY_HZ

        # Runtime state
        self._running: bool = False
        self._sequence_counter: int = 0
        self._sent_count: int = 0
        self._error_count: int = 0

        # Background task handle
        self._produce_task: Optional[asyncio.Task] = None

        # In-memory ring buffer for /api/messages/recent
        self._recent_messages: Deque[Dict[str, Any]] = deque(
            maxlen=_RECENT_MESSAGES_CAPACITY
        )

        # Rate tracking (exponential moving average, α=0.1)
        self._ema_rate: float = 0.0
        self._last_sent_count: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_producing(self) -> None:
        """
        Start the message generation loop.

        If already running, this is a no-op.
        """
        if self._running:
            logger.info("Producer already running — ignoring start request")
            return

        logger.info(
            "Starting producer %s at %.1f Hz",
            self._producer_id,
            self._frequency_hz,
        )
        self._running = True
        self._produce_task = asyncio.create_task(
            self._produce_loop(), name=f"produce-{self._producer_id}"
        )

    async def stop_producing(self) -> None:
        """
        Stop the message generation loop gracefully.

        Waits for the current produce_loop iteration to finish before
        returning.
        """
        if not self._running:
            logger.info("Producer not running — ignoring stop request")
            return

        logger.info("Stopping producer %s", self._producer_id)
        self._running = False

        if self._produce_task and not self._produce_task.done():
            self._produce_task.cancel()
            try:
                await self._produce_task
            except asyncio.CancelledError:
                pass
        self._produce_task = None

    def reset_stats(self) -> None:
        """Reset cumulative in-memory counters to zero for a fresh test run."""
        self._sent_count = 0
        self._error_count = 0
        self._last_sent_count = 0
        self._ema_rate = 0.0
        self._recent_messages.clear()
        logger.info("Producer %s stats reset", self._producer_id)

    async def set_frequency(self, hz: float) -> None:
        """
        Update the message generation frequency at runtime.

        The change takes effect on the next loop iteration (i.e. no more
        than one old-frequency sleep away).

        Parameters
        ----------
        hz:
            New frequency in messages per second (1–1000).
        """
        old = self._frequency_hz
        self._frequency_hz = hz
        logger.info(
            "Producer %s frequency changed: %.1f → %.1f Hz",
            self._producer_id,
            old,
            hz,
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> ProducerStatus:
        """
        Return a snapshot of the current producer state.

        This method is synchronous because it only reads in-memory values;
        the ``buffered_count`` field is best-effort (may lag slightly).
        """
        return ProducerStatus(
            producer_id=self._producer_id,
            running=self._running,
            frequency_hz=self._frequency_hz,
            sequence_counter=self._sequence_counter,
            # count_pending() is async; we use 0 as a safe fallback here.
            # The WebSocket handler calls _async_get_status() instead.
            buffered_count=0,
            sent_count=self._sent_count,
            error_count=self._error_count,
            kafka_connected=self._kafka_producer.is_connected,
        )

    async def async_get_status(self) -> ProducerStatus:
        """
        Async variant of get_status() that includes the accurate buffer count.
        """
        buffered = await self._buffer.count_pending()
        return ProducerStatus(
            producer_id=self._producer_id,
            running=self._running,
            frequency_hz=self._frequency_hz,
            sequence_counter=self._sequence_counter,
            buffered_count=buffered,
            sent_count=self._sent_count,
            error_count=self._error_count,
            kafka_connected=self._kafka_producer.is_connected,
        )

    def get_recent_messages(self) -> List[Dict[str, Any]]:
        """Return the last up to 100 messages from the in-memory ring buffer."""
        return list(self._recent_messages)

    # ------------------------------------------------------------------
    # Rate tracking (called by WebSocket handler every second)
    # ------------------------------------------------------------------

    def update_rate_metric(self) -> None:
        """
        Compute an exponential moving average of the send rate and update
        the Prometheus gauge.

        Should be called approximately once per second.
        """
        delta = self._sent_count - self._last_sent_count
        self._last_sent_count = self._sent_count

        # EMA with α=0.3 — gives a reasonably smooth estimate
        alpha = 0.3
        self._ema_rate = alpha * delta + (1 - alpha) * self._ema_rate

        messages_sent_rate.labels(producer_id=self._producer_id).set(self._ema_rate)

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _produce_loop(self) -> None:
        """
        Core message generation loop.

        Generates one message per (1 / frequency_hz) seconds.  Each message
        is handed to the Kafka producer; successes and failures are tracked
        for the status endpoint.
        """
        logger.info(
            "Produce loop started for %s @ %.1f Hz",
            self._producer_id,
            self._frequency_hz,
        )
        while self._running:
            try:
                message = await self._generate_message()
                success = await self._kafka_producer.send_message(message.model_dump())

                if success:
                    self._sent_count += 1
                    # Add to in-memory ring buffer for /api/messages/recent
                    self._recent_messages.append(message.model_dump())
                else:
                    # Buffered — still counts as sent_count once delivered,
                    # so we increment optimistically here.  The error_count
                    # only increments on non-retriable errors.
                    self._sent_count += 1
                    self._recent_messages.append(message.model_dump())

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._error_count += 1
                logger.exception(
                    "Unexpected error in produce loop (seq=%d): %s",
                    self._sequence_counter,
                    exc,
                )

            # Sleep for the interval corresponding to the current frequency.
            # Read _frequency_hz each iteration so frequency changes take effect
            # without restarting the loop.
            interval = 1.0 / max(self._frequency_hz, 0.001)
            await asyncio.sleep(interval)

        logger.info("Produce loop stopped for %s", self._producer_id)

    async def _generate_message(self) -> Message:
        """
        Create a new HAMq message with an incremented sequence counter.

        The payload ``data`` field contains a small random block encoded as
        base64 (8 bytes of randomness) so that each message has a distinct
        checksum, which aids end-to-end testing.

        Returns
        -------
        Message
            A fully populated :class:`~app.models.Message` instance.
        """
        self._sequence_counter += 1

        # Generate a small random payload to give each message a unique checksum
        raw_data = base64.b64encode(os.urandom(8)).decode("ascii")
        checksum = self._compute_checksum(raw_data)

        return Message(
            id=str(uuid.uuid4()),
            sequence=self._sequence_counter,
            producer_id=self._producer_id,
            # ISO-8601 with millisecond precision as required by spec
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            frequency_hz=self._frequency_hz,
            payload=MessagePayload(data=raw_data, checksum=checksum),
        )

    @staticmethod
    def _compute_checksum(data: str) -> str:
        """
        Compute the SHA-256 hex digest of a string.

        Parameters
        ----------
        data:
            The data field value from the message payload.

        Returns
        -------
        str
            64-character lowercase hex string.
        """
        return hashlib.sha256(data.encode("utf-8")).hexdigest()
