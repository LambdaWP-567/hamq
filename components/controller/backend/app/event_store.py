"""
SQLite-backed audit log for the HAMq Controller.

Every operation performed by the controller is persisted here so operators
can review what happened during chaos experiments and investigate failures.

The database is intentionally simple: a single ``events`` table with a
JSON blob for flexible schema evolution.

Usage pattern:
    store = EventStore(db_path="/data/controller_events.db")
    await store.initialize()
    await store.save_event(some_cluster_event)
    events = await store.get_events(limit=50)
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

import aiosqlite

from app.models import ClusterEvent

logger = logging.getLogger(__name__)

# DDL for the events table.  Using TEXT for all columns keeps the schema
# simple while still allowing rich queries via SQLite's JSON functions.
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS events (
    event_id   TEXT PRIMARY KEY,
    timestamp  TEXT NOT NULL,
    event_type TEXT NOT NULL,
    target     TEXT NOT NULL,
    namespace  TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'pending',
    details    TEXT NOT NULL DEFAULT ''
);
"""

# Index on timestamp accelerates the most common query (recent events)
_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp DESC);
"""


class EventStore:
    """
    Asynchronous SQLite audit store for cluster events.

    Thread-safety is ensured by aiosqlite's internal serialisation of all
    database operations to a single background thread.
    """

    def __init__(self, db_path: str) -> None:
        """
        Parameters
        ----------
        db_path:
            Filesystem path for the SQLite database.  The parent directory
            must exist (typically a Kubernetes PersistentVolume mounted at /data).
        """
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """
        Open the database connection and create the schema if needed.

        Must be called once during application startup before any other method.
        """
        logger.info("EventStore: opening database at %s", self._db_path)
        self._db = await aiosqlite.connect(self._db_path)

        # Enable WAL mode for better concurrent read performance
        await self._db.execute("PRAGMA journal_mode=WAL;")

        # Create table and index
        await self._db.execute(_CREATE_TABLE_SQL)
        await self._db.execute(_CREATE_INDEX_SQL)
        await self._db.commit()
        logger.info("EventStore: schema ready")

    async def close(self) -> None:
        """Close the database connection gracefully."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("EventStore: database connection closed")

    async def save_event(self, event: ClusterEvent) -> None:
        """
        Persist a cluster event to the audit log.

        Parameters
        ----------
        event:
            The event to store.  The event_id must be unique across all events.
        """
        if not self._db:
            logger.error("EventStore.save_event called before initialize()")
            return

        sql = """
        INSERT OR REPLACE INTO events
            (event_id, timestamp, event_type, target, namespace, status, details)
        VALUES
            (?, ?, ?, ?, ?, ?, ?)
        """
        await self._db.execute(
            sql,
            (
                event.event_id,
                event.timestamp,
                event.event_type,
                event.target,
                event.namespace,
                event.status,
                event.details,
            ),
        )
        await self._db.commit()
        logger.debug("EventStore: saved event %s (%s)", event.event_id, event.event_type)

    async def get_events(
        self,
        limit: int = 100,
        event_type: Optional[str] = None,
    ) -> List[ClusterEvent]:
        """
        Retrieve recent events from the audit log.

        Parameters
        ----------
        limit:
            Maximum number of events to return (most recent first).
        event_type:
            Optional filter — return only events of this type.

        Returns
        -------
        list[ClusterEvent]
            Events ordered newest-first.
        """
        if not self._db:
            logger.error("EventStore.get_events called before initialize()")
            return []

        if event_type:
            sql = """
            SELECT event_id, timestamp, event_type, target, namespace, status, details
            FROM events
            WHERE event_type = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """
            params = (event_type, limit)
        else:
            sql = """
            SELECT event_id, timestamp, event_type, target, namespace, status, details
            FROM events
            ORDER BY timestamp DESC
            LIMIT ?
            """
            params = (limit,)

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        await cursor.close()

        events: List[ClusterEvent] = []
        for row in rows:
            events.append(
                ClusterEvent(
                    event_id=row[0],
                    timestamp=row[1],
                    event_type=row[2],
                    target=row[3],
                    namespace=row[4],
                    status=row[5],
                    details=row[6],
                )
            )

        return events

    async def get_stats(self) -> Dict[str, Dict[str, int]]:
        """
        Aggregate event counts grouped by (event_type, status).

        Returns
        -------
        dict
            Nested dict: ``{event_type: {status: count}}``.
            Example::

                {
                    "pod_restart": {"success": 5, "failed": 1},
                    "node_drain":  {"success": 2},
                }
        """
        if not self._db:
            return {}

        sql = """
        SELECT event_type, status, COUNT(*) as cnt
        FROM events
        GROUP BY event_type, status
        """
        cursor = await self._db.execute(sql)
        rows = await cursor.fetchall()
        await cursor.close()

        stats: Dict[str, Dict[str, int]] = {}
        for event_type, status, count in rows:
            if event_type not in stats:
                stats[event_type] = {}
            stats[event_type][status] = count

        return stats
