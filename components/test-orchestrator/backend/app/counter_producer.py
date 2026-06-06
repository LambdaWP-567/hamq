from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer

from app.config import settings

logger = logging.getLogger(__name__)


class CounterProducer:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None
        self._task: asyncio.Task | None = None
        self._running = False

        self.sent_counter: int = 0
        self.total_sent: int = 0
        self.send_rate: float = 0.0

        self._rate_window_count: int = 0
        self._rate_window_start: float = time.monotonic()

    async def _build_producer(self) -> AIOKafkaProducer:
        ssl_context = None
        if settings.KAFKA_TLS_ENABLED:
            import ssl
            ssl_context = ssl.create_default_context()
            if settings.KAFKA_CA_CERT_PATH:
                ssl_context.load_verify_locations(settings.KAFKA_CA_CERT_PATH)
            if settings.KAFKA_CLIENT_CERT_PATH and settings.KAFKA_CLIENT_KEY_PATH:
                ssl_context.load_cert_chain(
                    settings.KAFKA_CLIENT_CERT_PATH,
                    settings.KAFKA_CLIENT_KEY_PATH,
                )

        return AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            ssl_context=ssl_context,
            security_protocol="SSL" if settings.KAFKA_TLS_ENABLED else "PLAINTEXT",
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks="all",
            enable_idempotence=True,
        )

    async def start(self, freq_hz: float, counter_max: int) -> None:
        if self._running:
            return
        self._running = True
        self._producer = await self._build_producer()
        await self._producer.start()
        self._task = asyncio.create_task(self._loop(freq_hz, counter_max))
        logger.info("CounterProducer started (freq=%.1f Hz, max=%d)", freq_hz, counter_max)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._producer:
            await self._producer.stop()
            self._producer = None
        logger.info("CounterProducer stopped")

    async def _loop(self, freq_hz: float, counter_max: int) -> None:
        counter = self.sent_counter if self.sent_counter > 0 else 1
        interval = 1.0 / max(freq_hz, 0.1)

        while self._running:
            msg = {
                "counter": counter,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            try:
                await self._producer.send_and_wait(settings.KAFKA_TOPIC, msg)
                self.sent_counter = counter
                self.total_sent += 1
                self._rate_window_count += 1
                counter = counter % counter_max + 1

                now = time.monotonic()
                elapsed = now - self._rate_window_start
                if elapsed >= 1.0:
                    self.send_rate = self._rate_window_count / elapsed
                    self._rate_window_count = 0
                    self._rate_window_start = now
            except Exception as exc:
                logger.warning("Send error: %s", exc)

            await asyncio.sleep(interval)
