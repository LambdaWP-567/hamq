"""
WebSocket handler for real-time producer status streaming.

The WebSocket endpoint broadcasts a :class:`~app.models.ProducerStatus`
JSON snapshot to all connected clients once per second.  Clients can use
this to update dashboards without polling the REST API.

Connection lifecycle
--------------------
1. Client connects to ``/ws``.
2. Server adds the connection to the active set.
3. A per-connection sender coroutine streams status updates every second.
4. On disconnect (or any send error) the connection is removed from the set.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Set

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Set of currently connected WebSocket clients
_connected_clients: Set[WebSocket] = set()


class ConnectionManager:
    """
    Manages the set of active WebSocket connections and provides a
    broadcast helper.
    """

    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection and register it."""
        await websocket.accept()
        self._clients.add(websocket)
        logger.info(
            "WebSocket client connected; total=%d", len(self._clients)
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the active set."""
        self._clients.discard(websocket)
        logger.info(
            "WebSocket client disconnected; total=%d", len(self._clients)
        )

    async def broadcast(self, data: str) -> None:
        """
        Send a text message to all connected clients.

        Silently removes any client whose send fails (stale connections).

        Parameters
        ----------
        data:
            JSON string to broadcast.
        """
        stale: list[WebSocket] = []
        for client in list(self._clients):
            try:
                await client.send_text(data)
            except Exception:
                # Connection is dead; mark for removal
                stale.append(client)

        for client in stale:
            self._clients.discard(client)


# Module-level singleton shared by the route and the broadcast loop
manager = ConnectionManager()


async def websocket_status_handler(
    websocket: WebSocket,
    producer_service: Any,
) -> None:
    """
    WebSocket endpoint handler — streams ProducerStatus every second.

    Parameters
    ----------
    websocket:
        The FastAPI WebSocket instance for this connection.
    producer_service:
        The shared :class:`~app.producer_service.ProducerService` instance
        injected from application state.
    """
    await manager.connect(websocket)
    try:
        while True:
            # Fetch a fresh status snapshot (includes async buffer count)
            status = await producer_service.async_get_status()

            # Also update the rate metric here so it's always driven at 1 Hz
            producer_service.update_rate_metric()

            # Serialise to JSON and broadcast
            payload = json.dumps(status.model_dump())
            try:
                await websocket.send_text(payload)
            except Exception:
                # Client disconnected
                break

            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("WebSocket handler error: %s", exc)
    finally:
        manager.disconnect(websocket)
