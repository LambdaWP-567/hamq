"""
SQLite-backed audit store for the HAMq Arbiter.

Audit records are persisted to a local SQLite database so that:
  - Historical loss data survives Arbiter pod restarts
  - The /api/audits endpoint can serve paginated history
  - The /api/stats endpoint can compute aggregate metrics

Schema
------
audits
  audit_id          TEXT PRIMARY KEY
  timestamp         TEXT    (ISO-8601 UTC)
  producer_id       TEXT
  sent_count        INTEGER
  received_count    INTEGER
  missing_sequences TEXT    (JSON-encoded list[int])
  loss_rate         REAL
  status            TEXT    ('ok' | 'warning' | 'critical')

The missing_sequences column stores a JSON array so we avoid a separate
many-to-many join table while keeping the data queryable via json_each() when
needed in the future.

Concurrent access from multiple async tasks is handled by aiosqlite which
wraps the synchronous sqlite3 module in a thread-pool executor.  A single
connection is shared for the lifetime of the process; WAL mode is enabled to
allow concurrent reads during writes.
"""

import json
import logging
from typing import Optional

import aiosqlite

from app.models import AuditResult, AuditSummary

logger = logging.getLogger(__name__)


class AuditStore:
    """
    Async SQLite store for Arbiter audit results.

    Usage
    -----
    store = AuditStore("/data/arbiter_audits.db")
    await store.initialize()   # called once at startup
    await store.save_result(result)
    history = await store.get_history(producer_id="producer-1", limit=50)
    """

    def __init__(self, db_path: str) -> None:
        """
        Parameters
        ----------
        db_path:
            Filesystem path for the SQLite file.  Set to ":memory:" in tests.
        """
        self._db_path = db_path
        # Single shared connection — created by initialize()
        self._db: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """
        Open the database connection and create the audits table if it does not
        exist yet.  Also enables WAL mode for better write/read concurrency.

        Must be called once before any other method.
        """
        logger.info("Opening audit database at %s", self._db_path)
        self._db = await aiosqlite.connect(self._db_path)

        # Return rows as dict-like sqlite3.Row objects for easy column access
        self._db.row_factory = aiosqlite.Row

        # WAL mode: readers don't block writers and vice-versa.
        # This is critical because the reconcile loop writes while the API
        # serves read requests concurrently.
        await self._db.execute("PRAGMA journal_mode=WAL")

        # Create the audits table if it doesn't exist
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS audits (
                audit_id          TEXT PRIMARY KEY,
                timestamp         TEXT NOT NULL,
                producer_id       TEXT NOT NULL,
                sent_count        INTEGER NOT NULL DEFAULT 0,
                received_count    INTEGER NOT NULL DEFAULT 0,
                missing_sequences TEXT NOT NULL DEFAULT '[]',
                loss_rate         REAL NOT NULL DEFAULT 0.0,
                status            TEXT NOT NULL DEFAULT 'ok'
            )
            """
        )

        # Index for efficient filtering by producer_id and time ordering
        await self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audits_producer_ts
            ON audits (producer_id, timestamp DESC)
            """
        )

        await self._db.commit()
        logger.info("Audit database initialised successfully")

    async def close(self) -> None:
        """Close the database connection gracefully."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("Audit database connection closed")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def save_result(self, result: AuditResult) -> None:
        """
        Persist a single AuditResult to the database.

        The missing_sequences list is JSON-encoded before storage.
        Duplicate audit_ids are silently ignored (INSERT OR IGNORE) so the
        method is idempotent if called twice with the same result.

        Parameters
        ----------
        result:
            The fully-populated AuditResult to persist.
        """
        if self._db is None:
            raise RuntimeError("AuditStore not initialised — call initialize() first")

        missing_json = json.dumps(result.missing_sequences)

        await self._db.execute(
            """
            INSERT OR IGNORE INTO audits
                (audit_id, timestamp, producer_id, sent_count, received_count,
                 missing_sequences, loss_rate, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.audit_id,
                result.timestamp,
                result.producer_id,
                result.sent_count,
                result.received_count,
                missing_json,
                result.loss_rate,
                result.status,
            ),
        )
        await self._db.commit()
        logger.debug("Saved audit %s for producer %s", result.audit_id, result.producer_id)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_history(
        self,
        producer_id: Optional[str],
        limit: int = 100,
    ) -> list[AuditSummary]:
        """
        Return a list of AuditSummary records, ordered by timestamp descending
        (most recent first).

        Parameters
        ----------
        producer_id:
            If not None, restrict results to this producer.
            If None, return audits across all producers.
        limit:
            Maximum number of records to return.

        Returns
        -------
        list[AuditSummary]
            Lightweight summaries without the missing_sequences payload.
        """
        if self._db is None:
            raise RuntimeError("AuditStore not initialised")

        if producer_id is not None:
            cursor = await self._db.execute(
                """
                SELECT audit_id, timestamp, producer_id, sent_count,
                       received_count, loss_rate, status
                FROM   audits
                WHERE  producer_id = ?
                ORDER  BY timestamp DESC
                LIMIT  ?
                """,
                (producer_id, limit),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT audit_id, timestamp, producer_id, sent_count,
                       received_count, loss_rate, status
                FROM   audits
                ORDER  BY timestamp DESC
                LIMIT  ?
                """,
                (limit,),
            )

        rows = await cursor.fetchall()
        return [
            AuditSummary(
                audit_id=row["audit_id"],
                timestamp=row["timestamp"],
                producer_id=row["producer_id"],
                sent_count=row["sent_count"],
                received_count=row["received_count"],
                loss_rate=row["loss_rate"],
                status=row["status"],
            )
            for row in rows
        ]

    async def get_result(self, audit_id: str) -> Optional[AuditResult]:
        """
        Fetch a full AuditResult (including missing_sequences) by audit_id.

        Parameters
        ----------
        audit_id:
            The UUID of the audit to fetch.

        Returns
        -------
        AuditResult or None if not found.
        """
        if self._db is None:
            raise RuntimeError("AuditStore not initialised")

        cursor = await self._db.execute(
            """
            SELECT audit_id, timestamp, producer_id, sent_count, received_count,
                   missing_sequences, loss_rate, status
            FROM   audits
            WHERE  audit_id = ?
            """,
            (audit_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        return AuditResult(
            audit_id=row["audit_id"],
            timestamp=row["timestamp"],
            producer_id=row["producer_id"],
            sent_count=row["sent_count"],
            received_count=row["received_count"],
            missing_sequences=json.loads(row["missing_sequences"]),
            loss_rate=row["loss_rate"],
            status=row["status"],
        )

    async def get_stats(self) -> dict:
        """
        Compute aggregate statistics across all stored audits.

        Returns
        -------
        dict with keys:
            total_audits       – total number of rows
            avg_loss_rate      – mean loss rate across all audits
            worst_producer     – producer_id with highest mean loss rate
            worst_loss_rate    – that producer's mean loss rate
            producers_tracked  – number of distinct producer IDs
        """
        if self._db is None:
            raise RuntimeError("AuditStore not initialised")

        # Total count and global average
        cursor = await self._db.execute(
            "SELECT COUNT(*) AS cnt, AVG(loss_rate) AS avg_lr FROM audits"
        )
        row = await cursor.fetchone()
        total_audits: int = row["cnt"] or 0
        avg_loss_rate: float = row["avg_lr"] or 0.0

        # Worst producer by average loss rate
        cursor = await self._db.execute(
            """
            SELECT   producer_id, AVG(loss_rate) AS mean_lr
            FROM     audits
            GROUP BY producer_id
            ORDER BY mean_lr DESC
            LIMIT    1
            """
        )
        worst_row = await cursor.fetchone()
        worst_producer = None
        worst_loss_rate = 0.0
        if worst_row:
            worst_producer = worst_row["producer_id"]
            worst_loss_rate = worst_row["mean_lr"] or 0.0

        # Distinct producers
        cursor = await self._db.execute(
            "SELECT COUNT(DISTINCT producer_id) AS cnt FROM audits"
        )
        row = await cursor.fetchone()
        producers_tracked: int = row["cnt"] or 0

        return {
            "total_audits": total_audits,
            "avg_loss_rate": avg_loss_rate,
            "worst_producer": worst_producer,
            "worst_loss_rate": worst_loss_rate,
            "producers_tracked": producers_tracked,
        }

    async def get_recent_missing(
        self,
        producer_id: str,
        limit: int = 50,
    ) -> list[int]:
        """
        Return the union of missing sequence numbers from the most recent
        ``limit`` audit records for the given producer.

        Useful for the dashboard to show "which sequences are persistently
        missing?" without re-running reconciliation.

        Parameters
        ----------
        producer_id:
            Producer to query.
        limit:
            How many recent audit records to look back through.

        Returns
        -------
        Sorted, deduplicated list of missing sequence numbers.
        """
        if self._db is None:
            raise RuntimeError("AuditStore not initialised")

        cursor = await self._db.execute(
            """
            SELECT missing_sequences
            FROM   audits
            WHERE  producer_id = ?
            ORDER  BY timestamp DESC
            LIMIT  ?
            """,
            (producer_id, limit),
        )
        rows = await cursor.fetchall()

        # Merge all missing_sequences lists into a single deduplicated set
        merged: set[int] = set()
        for row in rows:
            seqs: list[int] = json.loads(row["missing_sequences"])
            merged.update(seqs)

        return sorted(merged)
