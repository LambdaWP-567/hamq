from __future__ import annotations

import logging
import ssl as _ssl_mod

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.admin.records_to_delete import RecordsToDelete

from app.config import settings

logger = logging.getLogger(__name__)


def _kafka_kwargs() -> dict:
    ssl_ctx = None
    if settings.KAFKA_TLS_ENABLED:
        ssl_ctx = _ssl_mod.create_default_context()
        if settings.KAFKA_CA_CERT_PATH:
            ssl_ctx.load_verify_locations(settings.KAFKA_CA_CERT_PATH)
        if settings.KAFKA_CLIENT_CERT_PATH and settings.KAFKA_CLIENT_KEY_PATH:
            ssl_ctx.load_cert_chain(settings.KAFKA_CLIENT_CERT_PATH, settings.KAFKA_CLIENT_KEY_PATH)
    return dict(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        ssl_context=ssl_ctx,
        security_protocol="SSL" if settings.KAFKA_TLS_ENABLED else "PLAINTEXT",
    )


async def purge_topic() -> None:
    """Delete all records in the test topic up to the current end offsets.

    The consumer group's committed offset will fall below the new log-start after
    deletion, causing aiokafka to auto-reset to earliest on the next consumer start —
    so no separate group deletion is needed.
    """
    kw = _kafka_kwargs()
    admin = AIOKafkaAdminClient(**kw)
    await admin.start()
    try:
        # Step 1: get partition IDs from the broker (no consumer metadata needed)
        topics_meta = await admin.describe_topics([settings.KAFKA_TOPIC])
        if not topics_meta or topics_meta[0].get("error_code", 0) != 0:
            logger.warning("purge: topic %s not found", settings.KAFKA_TOPIC)
            return
        parts = [p["partition"] for p in topics_meta[0]["partitions"]]
        tps = [TopicPartition(settings.KAFKA_TOPIC, p) for p in sorted(parts)]

        # Step 2: get end offsets via a temporary no-group consumer
        tmp = AIOKafkaConsumer(**kw)
        await tmp.start()
        try:
            tmp.assign(tps)
            end_offsets = await tmp.end_offsets(tps)
        finally:
            await tmp.stop()

        logger.info("purge: end offsets %s", {f"p{tp.partition}": off for tp, off in end_offsets.items()})

        # Step 3: delete records
        to_delete = {tp: RecordsToDelete(before_offset=off) for tp, off in end_offsets.items() if off > 0}
        if to_delete:
            await admin.delete_records(to_delete)
            logger.info("purge: deleted records in %d partition(s)", len(to_delete))
        else:
            logger.info("purge: topic already empty")
    finally:
        await admin.close()
