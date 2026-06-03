"""
HAMq Consumer — Consumer Service
====================================
Orchestrates the KafkaConsumerService and MessageStore lifecycle.
Acts as the single source of truth for ConsumerStatus and is the only
component that the API layer needs to import.
"""

from __future__ import annotations

import asyncio
import logging

from .config import settings
from .kafka_consumer import KafkaConsumerService
from .metrics import messages_in_db_gauge
from .models import ConsumerStatus
from .storage import MessageStore

logger = logging.getLogger(__name__)


class ConsumerService:
    """
    High-level orchestrator for the consumer component.

    Responsibilities:
    - Owns the MessageStore (SQLite) and KafkaConsumerService instances.
    - Provides start() / stop() control plane methods called by the REST API.
    - Runs a background stats-refresh task that updates Prometheus gauges.
    - Provides get_status() for the /api/status endpoint and WebSocket stream.
    """

    def __init__(self) -> None:
        self._store = MessageStore()
        self._kafka = KafkaConsumerService(self._store)
        self._stats_task: asyncio.Task | None = None

        # Cached stats dict refreshed every 5 s by the background task.
        self._cached_stats: dict = {
            "total_count": 0,
            "last_sequence_by_producer": {},
            "checksum_error_count": 0,
        }

    # ---------------------------------------------------------------------- #
    #  Properties for direct access by API / WebSocket layers
    # ---------------------------------------------------------------------- #

    @property
    def store(self) -> MessageStore:
        return self._store

    # ---------------------------------------------------------------------- #
    #  Lifecycle
    # ---------------------------------------------------------------------- #

    async def initialize(self) -> None:
        """
        Open the SQLite database and start background maintenance.
        Called once from the FastAPI lifespan hook.
        """
        await self._store.initialize()
        # Start the periodic stats-refresh task.
        self._stats_task = asyncio.create_task(
            self._stats_loop(), name="consumer-stats-loop"
        )
        logger.info("ConsumerService initialised")

    async def shutdown(self) -> None:
        """Stop all background tasks and close connections gracefully."""
        await self._kafka.stop()
        if self._stats_task is not None and not self._stats_task.done():
            self._stats_task.cancel()
            try:
                await self._stats_task
            except asyncio.CancelledError:
                pass
        await self._store.close()
        logger.info("ConsumerService shut down")

    # ---------------------------------------------------------------------- #
    #  Control plane
    # ---------------------------------------------------------------------- #

    async def start(self) -> None:
        """Begin consuming messages from Kafka."""
        if self._kafka.running:
            logger.info("Consumer already running — start() is a no-op")
            return
        await self._kafka.start()
        logger.info("Consumer started")

    async def stop(self) -> None:
        """Stop consuming messages (does not close SQLite)."""
        await self._kafka.stop()
        logger.info("Consumer stopped")

    # ---------------------------------------------------------------------- #
    #  Status
    # ---------------------------------------------------------------------- #

    def get_status(self) -> ConsumerStatus:
        """
        Return a snapshot of the current consumer state.
        Uses the cached stats dict (refreshed every 5 s) to avoid hitting
        SQLite on every WebSocket tick.
        """
        return ConsumerStatus(
            consumer_id=settings.CONSUMER_ID,
            running=self._kafka.running,
            kafka_connected=self._kafka.connected,
            received_count=self._cached_stats.get("total_count", 0),
            last_sequence_by_producer=self._cached_stats.get(
                "last_sequence_by_producer", {}
            ),
            lag_estimate=self._kafka.lag_estimate,
            checksum_errors=self._kafka.checksum_errors,
        )

    # ---------------------------------------------------------------------- #
    #  Background tasks
    # ---------------------------------------------------------------------- #

    async def _stats_loop(self) -> None:
        """
        Refresh cached stats and Prometheus gauges every 5 seconds.
        Also triggers the old-message cleanup once per hour.
        """
        cleanup_counter = 0
        while True:
            try:
                stats = await self._store.get_stats()
                self._cached_stats = stats

                # Update the in-DB message count gauge.
                messages_in_db_gauge.labels(
                    consumer_id=settings.CONSUMER_ID
                ).set(stats.get("total_count", 0))

                # Run cleanup roughly once per hour (720 × 5 s ≈ 3600 s).
                cleanup_counter += 1
                if cleanup_counter >= 720:
                    cleanup_counter = 0
                    deleted = await self._store.cleanup_old()
                    if deleted:
                        logger.info("Background cleanup removed %d old messages", deleted)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Stats loop error (non-fatal): %s", exc)

            await asyncio.sleep(5)
