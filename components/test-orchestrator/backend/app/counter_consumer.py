from __future__ import annotations

import asyncio
import json
import logging
import time

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.judge import Judge

logger = logging.getLogger(__name__)


class CounterConsumer:
    def __init__(self, judge: Judge) -> None:
        self._judge = judge
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task | None = None
        self._running = False

        self.recv_counter: int | None = None
        self.total_received: int = 0
        self.recv_rate: float = 0.0

        self._rate_window_count: int = 0
        self._rate_window_start: float = time.monotonic()

    async def _build_consumer(self) -> AIOKafkaConsumer:
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

        return AIOKafkaConsumer(
            settings.KAFKA_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="hamq-test-orchestrator",
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
            ssl_context=ssl_context,
            security_protocol="SSL" if settings.KAFKA_TLS_ENABLED else "PLAINTEXT",
        )

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._consumer = await self._build_consumer()
        await self._consumer.start()
        self._task = asyncio.create_task(self._loop())
        logger.info("CounterConsumer started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None
        logger.info("CounterConsumer stopped")

    async def _loop(self) -> None:
        async for msg in self._consumer:
            if not self._running:
                break
            try:
                data = json.loads(msg.value.decode("utf-8"))
                counter = int(data["counter"])
                self._judge.record(counter)
                self.recv_counter = counter
                self.total_received += 1
                self._rate_window_count += 1

                now = time.monotonic()
                elapsed = now - self._rate_window_start
                if elapsed >= 1.0:
                    self.recv_rate = self._rate_window_count / elapsed
                    self._rate_window_count = 0
                    self._rate_window_start = now

            except Exception as exc:
                logger.warning("Consume error: %s", exc)
