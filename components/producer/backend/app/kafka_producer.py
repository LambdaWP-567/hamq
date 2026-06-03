"""
Resilient Kafka producer wrapper for the HAMq Producer.

Design goals
------------
1. **No message loss**: every message is buffered to SQLite *before* being
   sent to Kafka.  If the send fails the message stays in the buffer and is
   retried by the background flush loop.
2. **Transparent reconnection**: the aiokafka producer is recreated from
   scratch after a connection failure.  Because the bootstrap address is a
   DNS name (Kubernetes Service), it automatically resolves to the current
   broker IP even after a rolling restart or IP change.
3. **Ordered delivery within a session**: the flush loop processes buffered
   messages FIFO so sequence numbers arrive in order.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from typing import Any, Dict, Optional

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError, KafkaError, KafkaTimeoutError

from app.buffer import MessageBuffer
from app.config import settings
from app.metrics import (
    kafka_connection_status,
    messages_buffered_gauge,
    messages_sent_total,
    send_latency_seconds,
)

logger = logging.getLogger(__name__)


def _build_ssl_context() -> Optional[ssl.SSLContext]:
    """
    Build an SSL context for mutual-TLS Kafka authentication.

    Returns None when TLS is disabled (e.g. local dev without certs).
    """
    if not settings.KAFKA_TLS_ENABLED:
        return None

    ctx = ssl.create_default_context(
        purpose=ssl.Purpose.SERVER_AUTH,
        cafile=settings.KAFKA_CA_CERT_PATH,
    )
    # Load client certificate + private key for mTLS
    ctx.load_cert_chain(
        certfile=settings.KAFKA_CLIENT_CERT_PATH,
        keyfile=settings.KAFKA_CLIENT_KEY_PATH,
    )
    return ctx


class ResilientKafkaProducer:
    """
    Wraps ``aiokafka.AIOKafkaProducer`` with automatic reconnection and
    SQLite-backed message persistence.

    Usage::

        producer = ResilientKafkaProducer(buffer)
        await producer.start()
        ok = await producer.send_message(msg_dict)
        await producer.stop()
    """

    def __init__(self, buffer: MessageBuffer) -> None:
        """
        Parameters
        ----------
        buffer:
            Initialised :class:`~app.buffer.MessageBuffer` instance shared
            with the rest of the application.
        """
        self._buffer = buffer
        self._producer: Optional[AIOKafkaProducer] = None
        self._connected: bool = False

        # Background tasks managed by start()/stop()
        self._reconnect_task: Optional[asyncio.Task] = None
        self._flush_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None

        # Coordination: flush loop waits on this event when not connected
        self._connected_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start the Kafka producer and background maintenance tasks.

        This method returns immediately; the reconnect loop handles the
        initial connection attempt in the background so that the API is
        available even before Kafka is reachable.
        """
        logger.info(
            "Starting ResilientKafkaProducer (bootstrap=%s, topic=%s)",
            settings.KAFKA_BOOTSTRAP_SERVERS,
            settings.KAFKA_TOPIC,
        )
        self._reconnect_task = asyncio.create_task(
            self._reconnect_loop(), name="kafka-reconnect"
        )
        self._flush_task = asyncio.create_task(
            self._flush_loop(), name="kafka-flush"
        )
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(), name="buffer-cleanup"
        )

    async def stop(self) -> None:
        """
        Stop background tasks and close the Kafka producer connection.
        """
        logger.info("Stopping ResilientKafkaProducer")

        # Cancel background tasks
        for task in (self._reconnect_task, self._flush_task, self._cleanup_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close the aiokafka producer
        await self._close_producer()

    # ------------------------------------------------------------------
    # Public send interface
    # ------------------------------------------------------------------

    async def send_message(self, message: Dict[str, Any]) -> bool:
        """
        Send a message to Kafka, buffering it locally if the send fails.

        The message is **always** written to the SQLite buffer first.  If
        the Kafka send succeeds the buffer entry is immediately marked as
        sent.  If it fails the entry remains and will be retried by the
        flush loop.

        Parameters
        ----------
        message:
            Message dict with at minimum an ``id`` field (UUID4 string).

        Returns
        -------
        bool
            True if the message was delivered to Kafka synchronously,
            False if it was buffered for later retry.
        """
        # Step 1: persist to buffer BEFORE attempting Kafka send
        await self._buffer.add(message)

        # Step 2: attempt immediate delivery if connected
        if self._connected and self._producer is not None:
            return await self._send_single(message)

        # Not connected — leave in buffer, flush loop will retry
        logger.debug(
            "Kafka not connected; message %s queued in buffer", message["id"]
        )
        return False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True when the aiokafka producer is connected and healthy."""
        return self._connected

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _create_producer(self) -> AIOKafkaProducer:
        """
        Instantiate and start a new ``AIOKafkaProducer``.

        A fresh producer is created each reconnection attempt so that
        the DNS lookup for the bootstrap address is re-evaluated.
        """
        ssl_context = _build_ssl_context()

        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            # Durability: wait for all ISR replicas to acknowledge
            acks=settings.KAFKA_ACKS,
            # Batch tuning
            max_batch_size=settings.KAFKA_MAX_BATCH_SIZE,
            linger_ms=settings.KAFKA_LINGER_MS,
            # Timeout / retry
            request_timeout_ms=settings.KAFKA_REQUEST_TIMEOUT_MS,
            retry_backoff_ms=settings.KAFKA_RETRY_BACKOFF_MS,
            # TLS
            ssl_context=ssl_context,
            security_protocol="SSL" if ssl_context else "PLAINTEXT",
            # JSON serialisation
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await producer.start()
        return producer

    async def _close_producer(self) -> None:
        """Close the current aiokafka producer instance if open."""
        if self._producer is not None:
            try:
                await self._producer.stop()
            except Exception as exc:
                logger.warning("Error closing Kafka producer: %s", exc)
            finally:
                self._producer = None
                self._connected = False
                self._connected_event.clear()
                kafka_connection_status.labels(
                    producer_id=settings.PRODUCER_ID
                ).set(0)

    async def _send_single(self, message: Dict[str, Any]) -> bool:
        """
        Attempt a single Kafka send and handle failures.

        Parameters
        ----------
        message:
            Pre-buffered message dict.

        Returns
        -------
        bool
            True on success.
        """
        import time as _time

        try:
            t0 = _time.monotonic()
            await self._producer.send_and_wait(  # type: ignore[union-attr]
                settings.KAFKA_TOPIC,
                value=message,
                key=message.get("producer_id"),
            )
            elapsed = _time.monotonic() - t0

            # Record Prometheus metrics
            send_latency_seconds.observe(elapsed)
            messages_sent_total.labels(
                producer_id=settings.PRODUCER_ID,
                topic=settings.KAFKA_TOPIC,
            ).inc()

            # Mark as delivered in the local buffer
            await self._buffer.mark_sent(message["id"])
            return True

        except (KafkaConnectionError, KafkaTimeoutError) as exc:
            logger.warning(
                "Kafka send failed for message %s: %s — will retry from buffer",
                message["id"],
                exc,
            )
            # Trigger reconnection
            self._connected = False
            self._connected_event.clear()
            kafka_connection_status.labels(producer_id=settings.PRODUCER_ID).set(0)
            asyncio.create_task(self._reconnect_once())
            return False

        except KafkaError as exc:
            logger.error(
                "Non-retriable Kafka error for message %s: %s",
                message["id"],
                exc,
            )
            # Still leave in buffer — operator can inspect and decide
            return False

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    async def _reconnect_loop(self) -> None:
        """
        Background task: keep the Kafka connection alive.

        Attempts to connect on startup, then re-checks every
        ``BUFFER_RETRY_INTERVAL_S`` seconds whenever the connection is lost.
        """
        while True:
            if not self._connected:
                await self._reconnect_once()
            await asyncio.sleep(settings.BUFFER_RETRY_INTERVAL_S)

    async def _reconnect_once(self) -> None:
        """
        Make a single connection attempt.

        On success, sets ``_connected=True`` and signals the flush loop.
        On failure, logs the error and returns (the loop will retry).
        """
        # Close any stale producer first
        await self._close_producer()

        try:
            logger.info(
                "Connecting to Kafka at %s …", settings.KAFKA_BOOTSTRAP_SERVERS
            )
            self._producer = await self._create_producer()
            self._connected = True
            self._connected_event.set()
            kafka_connection_status.labels(producer_id=settings.PRODUCER_ID).set(1)
            logger.info("Kafka connection established")

        except Exception as exc:
            logger.warning(
                "Kafka connection attempt failed: %s — will retry in %ss",
                exc,
                settings.BUFFER_RETRY_INTERVAL_S,
            )
            self._connected = False
            self._connected_event.clear()
            kafka_connection_status.labels(producer_id=settings.PRODUCER_ID).set(0)

    async def _flush_loop(self) -> None:
        """
        Background task: flush buffered messages to Kafka.

        Runs every ``BUFFER_FLUSH_INTERVAL_S`` seconds.  Waits until the
        Kafka connection is established before attempting to flush.
        """
        while True:
            try:
                await asyncio.sleep(settings.BUFFER_FLUSH_INTERVAL_S)

                if not self._connected:
                    # Update buffered gauge even when disconnected
                    count = await self._buffer.count_pending()
                    messages_buffered_gauge.labels(
                        producer_id=settings.PRODUCER_ID
                    ).set(count)
                    continue

                await self._flush_buffer()

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Unhandled error in flush loop: %s", exc)

    async def _flush_buffer(self) -> None:
        """
        Send all pending buffered messages to Kafka in FIFO order.

        Fetches messages in batches of 100 to avoid loading the entire
        buffer into memory at once.
        """
        while True:
            pending = await self._buffer.get_pending(limit=100)
            if not pending:
                break

            sent_count = 0
            for msg in pending:
                if not self._connected:
                    # Lost connection mid-flush — stop and let reconnect loop handle it
                    logger.info(
                        "Connection lost during buffer flush; will resume later"
                    )
                    return

                success = await self._send_single(msg)
                if success:
                    sent_count += 1

            # Update prometheus gauge
            buffered = await self._buffer.count_pending()
            messages_buffered_gauge.labels(
                producer_id=settings.PRODUCER_ID
            ).set(buffered)

            if sent_count == 0:
                # Every send in this batch failed — break to avoid busy-looping
                break

    async def _cleanup_loop(self) -> None:
        """
        Background task: remove old sent messages from the SQLite buffer.

        Runs every 5 minutes to keep the database file size bounded.
        """
        while True:
            try:
                await asyncio.sleep(300)  # every 5 minutes
                deleted = await self._buffer.cleanup_sent(max_age_seconds=3600)
                if deleted:
                    logger.info("Buffer housekeeping: removed %d sent messages", deleted)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Buffer cleanup loop error: %s", exc)
