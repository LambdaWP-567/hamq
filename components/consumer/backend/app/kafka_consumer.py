"""
HAMq Consumer — Kafka Consumer
=================================
Wraps aiokafka AIOKafkaConsumer with:
  - TLS / mTLS support via cert files mounted from Kubernetes Secrets
  - Manual offset commit *after* successful SQLite persistence (at-least-once)
  - Automatic reconnection on network failures
  - Per-message checksum validation
  - Prometheus metric emission

Design:
  The consume loop runs as a background asyncio Task.  On any exception it
  backs off and retries rather than crashing the whole process, so a transient
  Kafka outage does not bring down the consumer pod.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from datetime import datetime, timezone
from typing import Optional

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError

from .config import settings
from .metrics import (
    consumer_lag_gauge,
    kafka_connection_status,
    kafka_poll_errors_total,
    messages_checksum_invalid_total,
    messages_duplicate_total,
    messages_received_total,
    processing_latency_seconds,
)
from .storage import MessageStore, _verify_checksum

logger = logging.getLogger(__name__)

# How long to wait between reconnection attempts (seconds).
_RECONNECT_BACKOFF_MIN = 2
_RECONNECT_BACKOFF_MAX = 30


class KafkaConsumerService:
    """
    Manages the aiokafka consumer lifecycle and the message-processing loop.

    Typical usage::

        svc = KafkaConsumerService(store)
        await svc.start()
        ...
        await svc.stop()
    """

    def __init__(self, store: MessageStore) -> None:
        self._store = store
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._task: Optional[asyncio.Task] = None

        # Mutable state surfaced to ConsumerService.get_status()
        self.connected: bool = False
        self.running: bool = False
        self.received_count: int = 0
        self.checksum_errors: int = 0
        self.lag_estimate: int = 0

    # ---------------------------------------------------------------------- #
    #  Lifecycle
    # ---------------------------------------------------------------------- #

    async def start(self) -> None:
        """Start the background consume loop."""
        if self.running:
            logger.warning("KafkaConsumerService.start() called but already running")
            return
        self.running = True
        self._task = asyncio.create_task(
            self._run_loop(), name="kafka-consume-loop"
        )
        logger.info("Kafka consume loop task created")

    async def stop(self) -> None:
        """Gracefully stop consuming and close the Kafka connection."""
        self.running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._close_consumer()
        logger.info("Kafka consumer stopped")

    # ---------------------------------------------------------------------- #
    #  Internal loop
    # ---------------------------------------------------------------------- #

    async def _run_loop(self) -> None:
        """
        Outer retry loop.
        Keeps reconnecting on failures until self.running is False.
        """
        backoff = _RECONNECT_BACKOFF_MIN
        while self.running:
            try:
                await self._connect()
                backoff = _RECONNECT_BACKOFF_MIN  # reset after successful connect
                await self._consume()
            except asyncio.CancelledError:
                logger.info("Consume loop cancelled")
                break
            except Exception as exc:
                logger.error(
                    "Kafka consumer error (backing off %ds): %s", backoff, exc
                )
                kafka_connection_status.labels(
                    consumer_id=settings.CONSUMER_ID
                ).set(0)
                self.connected = False
                if self.running:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _RECONNECT_BACKOFF_MAX)
        kafka_connection_status.labels(consumer_id=settings.CONSUMER_ID).set(0)

    async def _connect(self) -> None:
        """Create and start an AIOKafkaConsumer instance."""
        await self._close_consumer()  # clean up any previous instance

        ssl_context = _build_ssl_context() if settings.KAFKA_TLS_ENABLED else None

        consumer_kwargs: dict = {
            "group_id": settings.KAFKA_CONSUMER_GROUP_ID,
            "auto_offset_reset": settings.KAFKA_AUTO_OFFSET_RESET,
            "enable_auto_commit": settings.KAFKA_ENABLE_AUTO_COMMIT,
            "max_poll_records": settings.KAFKA_MAX_POLL_RECORDS,
            # Deserialise the raw bytes to a Python dict.
            "value_deserializer": lambda raw: json.loads(raw.decode("utf-8")),
        }

        if ssl_context is not None:
            consumer_kwargs["ssl_context"] = ssl_context
            consumer_kwargs["security_protocol"] = "SSL"
        else:
            consumer_kwargs["security_protocol"] = "PLAINTEXT"

        self._consumer = AIOKafkaConsumer(
            settings.KAFKA_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            **consumer_kwargs,
        )

        logger.info(
            "Connecting to Kafka at %s (topic=%s, group=%s, tls=%s)",
            settings.KAFKA_BOOTSTRAP_SERVERS,
            settings.KAFKA_TOPIC,
            settings.KAFKA_CONSUMER_GROUP_ID,
            settings.KAFKA_TLS_ENABLED,
        )
        await self._consumer.start()
        self.connected = True
        kafka_connection_status.labels(consumer_id=settings.CONSUMER_ID).set(1)
        logger.info("Kafka consumer connected")

    async def _consume(self) -> None:
        """
        Inner consume loop — poll for message batches and persist each one.

        Offset commit is performed *after* storage.save() succeeds to ensure
        at-least-once delivery: if the process crashes between receiving a
        message and persisting it, the message will be re-delivered on restart.
        """
        assert self._consumer is not None

        while self.running:
            try:
                # getmany() returns a dict: {TopicPartition: [ConsumerRecord]}
                # It blocks for up to 1000 ms before returning an empty dict,
                # allowing us to react quickly when running=False.
                records_by_partition = await self._consumer.getmany(
                    timeout_ms=1000, max_records=settings.KAFKA_MAX_POLL_RECORDS
                )
            except KafkaError as exc:
                kafka_poll_errors_total.labels(
                    consumer_id=settings.CONSUMER_ID
                ).inc()
                logger.warning("Kafka poll error: %s", exc)
                raise  # bubble up to _run_loop for reconnect

            for tp, records in records_by_partition.items():
                for record in records:
                    await self._handle_record(record)
                    # Commit offset for this partition after each successful save.
                    # Batch-committing the whole partition at once is more
                    # efficient but per-message commits are simpler and safe.
                    await self._consumer.commit({tp: record.offset + 1})

            # Update lag estimate periodically.
            await self._update_lag()

    async def _handle_record(self, record) -> None:
        """
        Process one ConsumerRecord: validate checksum, persist to SQLite,
        and emit Prometheus metrics.
        """
        message: dict = record.value
        producer_id: str = message.get("producer_id", "unknown")
        sequence: int = message.get("sequence", -1)

        # ------------------------------------------------------------------ #
        #  Latency measurement
        #  Compute the wall-clock latency from producer timestamp to now.
        # ------------------------------------------------------------------ #
        latency_seconds: Optional[float] = _compute_latency(
            message.get("timestamp", "")
        )

        # ------------------------------------------------------------------ #
        #  Checksum validation
        # ------------------------------------------------------------------ #
        payload = message.get("payload", {})
        payload_data = payload.get("data", "")
        declared_checksum = payload.get("checksum", "")
        checksum_ok = _verify_checksum(payload_data, declared_checksum)

        if not checksum_ok:
            self.checksum_errors += 1
            messages_checksum_invalid_total.labels(
                consumer_id=settings.CONSUMER_ID,
                producer_id=producer_id,
            ).inc()
            logger.warning(
                "Checksum mismatch for message id=%s seq=%d producer=%s",
                message.get("id"),
                sequence,
                producer_id,
            )

        # ------------------------------------------------------------------ #
        #  Persist to SQLite
        # ------------------------------------------------------------------ #
        inserted = await self._store.save(message)

        if inserted:
            self.received_count += 1
            messages_received_total.labels(
                consumer_id=settings.CONSUMER_ID,
                producer_id=producer_id,
                topic=settings.KAFKA_TOPIC,
            ).inc()

            if latency_seconds is not None:
                processing_latency_seconds.labels(
                    consumer_id=settings.CONSUMER_ID,
                    producer_id=producer_id,
                ).observe(latency_seconds)

            logger.debug(
                "Persisted seq=%d producer=%s checksum_ok=%s latency=%.3fs",
                sequence,
                producer_id,
                checksum_ok,
                latency_seconds or 0.0,
            )
        else:
            # INSERT OR IGNORE skipped — duplicate message
            messages_duplicate_total.labels(
                consumer_id=settings.CONSUMER_ID,
                producer_id=producer_id,
            ).inc()

    async def _update_lag(self) -> None:
        """
        Estimate the consumer lag by comparing current position to the end
        offset for each assigned partition.
        """
        if self._consumer is None:
            return
        try:
            end_offsets = await self._consumer.end_offsets(
                self._consumer.assignment()
            )
            current_positions = {}
            for tp in self._consumer.assignment():
                pos = await self._consumer.position(tp)
                current_positions[tp] = pos

            total_lag = sum(
                max(0, end_offsets[tp] - current_positions.get(tp, 0))
                for tp in end_offsets
            )
            self.lag_estimate = total_lag
            consumer_lag_gauge.labels(
                consumer_id=settings.CONSUMER_ID,
                topic=settings.KAFKA_TOPIC,
            ).set(total_lag)
        except Exception as exc:
            logger.debug("Could not compute lag: %s", exc)

    async def _close_consumer(self) -> None:
        """Stop and discard the current consumer instance if it exists."""
        if self._consumer is not None:
            try:
                await self._consumer.stop()
            except Exception as exc:
                logger.debug("Error stopping consumer: %s", exc)
            self._consumer = None
        self.connected = False


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _build_ssl_context() -> ssl.SSLContext:
    """
    Build an SSL context using the certificate files specified in settings.

    Strimzi mounts the Kafka CA cert and the KafkaUser client cert+key
    into the pod filesystem.  We load them here for mTLS authentication.
    """
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.load_verify_locations(cafile=settings.KAFKA_CA_CERT_PATH)
    ctx.load_cert_chain(
        certfile=settings.KAFKA_CLIENT_CERT_PATH,
        keyfile=settings.KAFKA_CLIENT_KEY_PATH,
    )
    return ctx


def _compute_latency(timestamp_str: str) -> Optional[float]:
    """
    Parse the ISO-8601 producer timestamp and return end-to-end latency in
    seconds.  Returns None if the timestamp cannot be parsed.
    """
    if not timestamp_str:
        return None
    try:
        # Handle both "Z" suffix and "+00:00" style UTC timestamps.
        ts_str = timestamp_str.replace("Z", "+00:00")
        produced_at = datetime.fromisoformat(ts_str)
        now = datetime.now(timezone.utc)
        return (now - produced_at).total_seconds()
    except (ValueError, TypeError):
        return None
