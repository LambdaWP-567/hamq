"""
HAMq Consumer — SQLite Message Store
======================================
Persists received Kafka messages to a local SQLite database.
All I/O is asynchronous via aiosqlite so the event loop is never blocked.

Design decisions:
  - INSERT OR IGNORE deduplicates re-delivered messages (at-least-once safety).
  - Composite index on (producer_id, sequence) supports fast Arbiter range queries.
  - A background cleanup task removes rows older than DB_RETENTION_HOURS.
  - WAL journal mode is enabled at startup for better concurrent read throughput.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

from .config import settings

logger = logging.getLogger(__name__)

# SQLite schema — kept in a constant so tests can verify it.
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    id               TEXT    PRIMARY KEY,
    sequence         INTEGER NOT NULL,
    producer_id      TEXT    NOT NULL,
    received_at      TEXT    NOT NULL,
    original_timestamp TEXT  NOT NULL,
    frequency_hz     REAL    NOT NULL,
    payload_data     TEXT    NOT NULL,
    checksum_valid   INTEGER NOT NULL DEFAULT 1
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_producer_seq
    ON messages (producer_id, sequence);
"""

_CREATE_RECEIVED_AT_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_received_at
    ON messages (received_at);
"""


class MessageStore:
    """
    Async SQLite store for received Kafka messages.

    Lifecycle::

        store = MessageStore()
        await store.initialize()   # call once at startup
        ...
        await store.save(msg_dict)
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path: str = db_path or settings.DB_PATH
        # We keep a single long-lived connection; aiosqlite wraps it in a
        # thread so blocking SQLite calls do not stall the event loop.
        self._db: Optional[aiosqlite.Connection] = None

    # ---------------------------------------------------------------------- #
    #  Lifecycle
    # ---------------------------------------------------------------------- #

    async def initialize(self) -> None:
        """
        Open (or create) the SQLite database and apply the schema.
        Call once during application startup.
        """
        logger.info("Opening SQLite database at %s", self._db_path)
        self._db = await aiosqlite.connect(self._db_path)

        # Row factory makes rows accessible by column name.
        self._db.row_factory = aiosqlite.Row

        # WAL mode improves concurrent read performance and is safer on
        # abrupt process termination.
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")

        # Apply schema.
        await self._db.execute(_CREATE_TABLE_SQL)
        await self._db.execute(_CREATE_INDEX_SQL)
        await self._db.execute(_CREATE_RECEIVED_AT_INDEX_SQL)
        await self._db.commit()
        logger.info("SQLite schema ready")

    async def close(self) -> None:
        """Close the database connection gracefully during shutdown."""
        if self._db is not None:
            await self._db.close()
            self._db = None
            logger.info("SQLite connection closed")

    # ---------------------------------------------------------------------- #
    #  Write
    # ---------------------------------------------------------------------- #

    async def save(self, message: Dict[str, Any]) -> bool:
        """
        Persist one Kafka message.

        The message dict is expected to follow the HAMq wire format::

            {
                "id": "<uuid4>",
                "sequence": 42,
                "producer_id": "producer-0",
                "timestamp": "2026-01-01T00:00:00.000Z",
                "frequency_hz": 10.0,
                "payload": {"data": "...", "checksum": "<sha256>"}
            }

        Returns True if the message was inserted, False if it was already
        present (idempotent duplicate handling via INSERT OR IGNORE).
        """
        assert self._db is not None, "MessageStore.initialize() has not been called"

        msg_id: str = message["id"]
        sequence: int = message["sequence"]
        producer_id: str = message["producer_id"]
        original_timestamp: str = message.get("timestamp", "")
        frequency_hz: float = message.get("frequency_hz", 0.0)

        payload: Dict[str, str] = message.get("payload", {})
        payload_data: str = payload.get("data", "")
        declared_checksum: str = payload.get("checksum", "")

        # ------------------------------------------------------------------ #
        #  Checksum validation
        #  The producer computes SHA-256 of the raw payload bytes (before any
        #  base64 encoding).  We recompute the digest and compare.
        # ------------------------------------------------------------------ #
        checksum_valid: bool = _verify_checksum(payload_data, declared_checksum)

        received_at: str = datetime.now(timezone.utc).isoformat()

        try:
            cursor = await self._db.execute(
                """
                INSERT OR IGNORE INTO messages
                    (id, sequence, producer_id, received_at, original_timestamp,
                     frequency_hz, payload_data, checksum_valid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    sequence,
                    producer_id,
                    received_at,
                    original_timestamp,
                    frequency_hz,
                    payload_data,
                    int(checksum_valid),
                ),
            )
            await self._db.commit()
            inserted = cursor.rowcount > 0
            if inserted:
                logger.debug(
                    "Saved message id=%s seq=%d producer=%s checksum_valid=%s",
                    msg_id, sequence, producer_id, checksum_valid,
                )
            else:
                logger.debug("Duplicate message ignored: id=%s", msg_id)
            return inserted
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to save message id=%s: %s", msg_id, exc)
            raise

    # ---------------------------------------------------------------------- #
    #  Read
    # ---------------------------------------------------------------------- #

    async def get_by_sequence_range(
        self,
        producer_id: str,
        seq_from: int,
        seq_to: int,
        page: int = 1,
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Return messages for *producer_id* with sequence in [seq_from, seq_to].
        Results are ordered by sequence ascending and paginated.
        """
        assert self._db is not None

        offset = (page - 1) * page_size
        async with self._db.execute(
            """
            SELECT id, sequence, producer_id, received_at, original_timestamp,
                   frequency_hz, payload_data, checksum_valid
            FROM messages
            WHERE producer_id = ?
              AND sequence BETWEEN ? AND ?
            ORDER BY sequence ASC
            LIMIT ? OFFSET ?
            """,
            (producer_id, seq_from, seq_to, page_size, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_total_in_range(
        self, producer_id: str, seq_from: int, seq_to: int
    ) -> int:
        """Return the count of messages matching the given producer + sequence range."""
        assert self._db is not None

        async with self._db.execute(
            """
            SELECT COUNT(*) FROM messages
            WHERE producer_id = ? AND sequence BETWEEN ? AND ?
            """,
            (producer_id, seq_from, seq_to),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_missing_sequences(
        self, producer_id: str, seq_from: int, seq_to: int
    ) -> List[int]:
        """
        Identify gaps in the sequence range [seq_from, seq_to] for *producer_id*.

        The returned list contains every integer in the range that has no
        corresponding row in the messages table.  This is the primary mechanism
        the Arbiter uses to compute message-loss statistics.

        Note: for very large ranges consider calling with a bounded window to
        avoid building an enormous Python list.
        """
        assert self._db is not None

        # Fetch the sequences we *do* have — then subtract from the full range.
        async with self._db.execute(
            """
            SELECT sequence FROM messages
            WHERE producer_id = ?
              AND sequence BETWEEN ? AND ?
            ORDER BY sequence ASC
            """,
            (producer_id, seq_from, seq_to),
        ) as cursor:
            rows = await cursor.fetchall()

        received: set[int] = {row[0] for row in rows}
        missing: List[int] = [
            s for s in range(seq_from, seq_to + 1) if s not in received
        ]
        return missing

    async def get_stats(self) -> Dict[str, Any]:
        """
        Return aggregate statistics used to populate ConsumerStatus.

        Returns a dict with:
          - ``total_count``             — total rows in the table
          - ``count_by_producer``       — {producer_id: count}
          - ``last_sequence_by_producer`` — {producer_id: max(sequence)}
          - ``checksum_error_count``    — rows where checksum_valid = 0
        """
        assert self._db is not None

        async with self._db.execute(
            """
            SELECT producer_id,
                   COUNT(*)       AS cnt,
                   MAX(sequence)  AS last_seq
            FROM messages
            GROUP BY producer_id
            """
        ) as cursor:
            producer_rows = await cursor.fetchall()

        async with self._db.execute(
            "SELECT COUNT(*) FROM messages WHERE checksum_valid = 0"
        ) as cursor:
            err_row = await cursor.fetchone()

        total = sum(r["cnt"] for r in producer_rows)
        count_by_producer = {r["producer_id"]: r["cnt"] for r in producer_rows}
        last_sequence = {r["producer_id"]: r["last_seq"] for r in producer_rows}
        checksum_errors = err_row[0] if err_row else 0

        return {
            "total_count": total,
            "count_by_producer": count_by_producer,
            "last_sequence_by_producer": last_sequence,
            "checksum_error_count": checksum_errors,
        }

    async def get_recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recently received messages (by received_at DESC)."""
        assert self._db is not None

        async with self._db.execute(
            """
            SELECT id, sequence, producer_id, received_at, original_timestamp,
                   frequency_hz, payload_data, checksum_valid
            FROM messages
            ORDER BY received_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_all_messages(
        self,
        producer_id: Optional[str] = None,
        seq_from: Optional[int] = None,
        seq_to: Optional[int] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Flexible query used by GET /api/messages.
        All filters are optional; results are ordered by received_at DESC.
        """
        assert self._db is not None

        conditions = []
        params: list = []

        if producer_id is not None:
            conditions.append("producer_id = ?")
            params.append(producer_id)
        if seq_from is not None:
            conditions.append("sequence >= ?")
            params.append(seq_from)
        if seq_to is not None:
            conditions.append("sequence <= ?")
            params.append(seq_to)

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        offset = (page - 1) * page_size
        params.extend([page_size, offset])

        async with self._db.execute(
            f"""
            SELECT id, sequence, producer_id, received_at, original_timestamp,
                   frequency_hz, payload_data, checksum_valid
            FROM messages
            {where_clause}
            ORDER BY received_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_total_count(
        self,
        producer_id: Optional[str] = None,
        seq_from: Optional[int] = None,
        seq_to: Optional[int] = None,
    ) -> int:
        """Count rows matching optional filter (used for pagination metadata)."""
        assert self._db is not None

        conditions = []
        params: list = []

        if producer_id is not None:
            conditions.append("producer_id = ?")
            params.append(producer_id)
        if seq_from is not None:
            conditions.append("sequence >= ?")
            params.append(seq_from)
        if seq_to is not None:
            conditions.append("sequence <= ?")
            params.append(seq_to)

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        async with self._db.execute(
            f"SELECT COUNT(*) FROM messages {where_clause}", params
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    # ---------------------------------------------------------------------- #
    #  Maintenance
    # ---------------------------------------------------------------------- #

    async def cleanup_old(self) -> int:
        """
        Delete messages older than DB_RETENTION_HOURS.
        Returns the number of rows deleted.
        Call periodically (e.g., every hour) from a background task.
        """
        assert self._db is not None

        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=settings.DB_RETENTION_HOURS)
        ).isoformat()

        cursor = await self._db.execute(
            "DELETE FROM messages WHERE received_at < ?", (cutoff,)
        )
        await self._db.commit()
        deleted = cursor.rowcount
        if deleted:
            logger.info("Pruned %d old messages (cutoff=%s)", deleted, cutoff)
        return deleted


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _verify_checksum(payload_data: str, declared_checksum: str) -> bool:
    """
    Verify the SHA-256 checksum of the payload.

    The producer computes::

        checksum = sha256(payload_data.encode()).hexdigest()

    We replicate the same computation and compare against *declared_checksum*.
    Returns True when the checksums match or when *declared_checksum* is absent.
    """
    if not declared_checksum:
        # No checksum supplied — treat as valid (older producer versions).
        return True
    try:
        computed = hashlib.sha256(payload_data.encode()).hexdigest()
        return computed == declared_checksum
    except Exception:  # pragma: no cover
        return False
