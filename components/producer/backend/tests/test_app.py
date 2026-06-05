"""
Integration tests for the HAMq Producer.

Each test is self-contained and uses an in-memory SQLite database so no
external services (Kafka, filesystem) are required.

Test inventory
--------------
1. App starts and GET /api/health returns 200
2. POST /api/auth/login with valid credentials returns a JWT token
3. GET /api/status without token returns HTTP 401
4. GET /api/status with valid token returns HTTP 200
5. Message model validation — sequence must be a positive integer
6. MessageBuffer add / get_pending / mark_sent cycle
7. Checksum computation is deterministic
8. PUT /api/frequency via API updates the frequency
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_mock_producer_service(
    running: bool = False,
    frequency_hz: float = 1.0,
    sequence_counter: int = 0,
    buffered_count: int = 0,
    sent_count: int = 0,
    error_count: int = 0,
    kafka_connected: bool = False,
) -> MagicMock:
    """Build a mock ProducerService that satisfies the route layer."""
    from app.models import ProducerStatus

    service = MagicMock()
    service._producer_id = "producer-test"
    service._frequency_hz = frequency_hz

    status = ProducerStatus(
        producer_id="producer-test",
        running=running,
        frequency_hz=frequency_hz,
        sequence_counter=sequence_counter,
        buffered_count=buffered_count,
        sent_count=sent_count,
        error_count=error_count,
        kafka_connected=kafka_connected,
    )

    # async methods
    service.async_get_status = AsyncMock(return_value=status)
    service.start_producing = AsyncMock()
    service.stop_producing = AsyncMock()
    service.set_frequency = AsyncMock()
    service.get_recent_messages = MagicMock(return_value=[])
    service.update_rate_metric = MagicMock()
    return service


def _make_mock_kafka_producer(connected: bool = False) -> MagicMock:
    """Build a minimal mock ResilientKafkaProducer."""
    kp = MagicMock()
    kp.is_connected = connected
    kp.start = AsyncMock()
    kp.stop = AsyncMock()
    kp.send_message = AsyncMock(return_value=True)
    return kp


def _make_mock_buffer() -> MagicMock:
    """Build a minimal mock MessageBuffer."""
    buf = MagicMock()
    buf.initialize = AsyncMock()
    buf.close = AsyncMock()
    buf.count_pending = AsyncMock(return_value=0)
    return buf


@pytest_asyncio.fixture
async def test_app():
    """
    Create a FastAPI test application with all external dependencies mocked.

    The lifespan is bypassed by directly injecting mocks into app.state so
    that tests do not need a real Kafka cluster or filesystem.
    """
    # Import here to avoid triggering the real lifespan
    from app.main import create_app

    application = create_app()

    # Inject mock dependencies into app.state before any request is made
    application.state.producer_service = _make_mock_producer_service()
    application.state.kafka_producer = _make_mock_kafka_producer()
    application.state.buffer = _make_mock_buffer()

    return application


@pytest_asyncio.fixture
async def client(test_app) -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP client configured with the test application.

    Uses ASGITransport so no real TCP socket is opened.
    """
    # Skip lifespan for the test client — state is pre-populated by the fixture
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://testserver",
    ) as c:
        yield c


async def _get_token(client: AsyncClient) -> str:
    """
    Authenticate and return a JWT token for use in protected requests.

    Uses the default admin credentials from settings.
    """
    from app.config import settings

    resp = await client.post(
        "/api/auth/login",
        json={"username": settings.AUTH_USERNAME, "password": "admin"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Test 1: Health endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient) -> None:
    """GET /api/health must return HTTP 200 with status=ok (no auth required)."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "producer_id" in body


# ---------------------------------------------------------------------------
# Test 2: Login returns JWT token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_returns_jwt(client: AsyncClient) -> None:
    """POST /api/auth/login with valid credentials must return a JWT token."""
    from app.config import settings

    response = await client.post(
        "/api/auth/login",
        json={"username": settings.AUTH_USERNAME, "password": "admin"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    # Basic structural check: JWT has three dot-separated parts
    parts = body["access_token"].split(".")
    assert len(parts) == 3, "Expected a three-part JWT"


# ---------------------------------------------------------------------------
# Test 3: Protected endpoint rejects missing token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_requires_auth(client: AsyncClient) -> None:
    """GET /api/status without an Authorization header must return HTTP 401."""
    response = await client.get("/api/status")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 4: Protected endpoint accepts valid token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_with_valid_token(client: AsyncClient) -> None:
    """GET /api/status with a valid Bearer token must return HTTP 200."""
    token = await _get_token(client)
    response = await client.get(
        "/api/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    # Verify expected fields are present
    assert "producer_id" in body
    assert "running" in body
    assert "frequency_hz" in body
    assert "buffered_count" in body
    assert "sent_count" in body
    assert "kafka_connected" in body


# ---------------------------------------------------------------------------
# Test 5: Message model validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_model_sequence_validation() -> None:
    """
    Message model must reject sequence values that are not positive integers.

    The spec requires sequence >= 1; a value of 0 must raise a ValidationError.
    """
    from pydantic import ValidationError

    from app.models import Message, MessagePayload

    valid_payload = MessagePayload(data="dGVzdA==", checksum="abc123")

    # Valid message — should not raise
    msg = Message(
        id="00000000-0000-0000-0000-000000000001",
        sequence=1,
        producer_id="test",
        timestamp="2024-01-01T00:00:00.000Z",
        frequency_hz=1.0,
        payload=valid_payload,
    )
    assert msg.sequence == 1

    # sequence=0 must be rejected
    with pytest.raises(ValidationError) as exc_info:
        Message(
            id="00000000-0000-0000-0000-000000000002",
            sequence=0,  # invalid
            producer_id="test",
            timestamp="2024-01-01T00:00:00.000Z",
            frequency_hz=1.0,
            payload=valid_payload,
        )
    assert "sequence" in str(exc_info.value).lower()

    # Negative sequence must also be rejected
    with pytest.raises(ValidationError):
        Message(
            id="00000000-0000-0000-0000-000000000003",
            sequence=-1,  # invalid
            producer_id="test",
            timestamp="2024-01-01T00:00:00.000Z",
            frequency_hz=1.0,
            payload=valid_payload,
        )


# ---------------------------------------------------------------------------
# Test 6: MessageBuffer add / get_pending / mark_sent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_buffer_lifecycle() -> None:
    """
    Full add → get_pending → mark_sent cycle using an in-memory SQLite DB.

    Verifies that:
    - A message added with add() appears in get_pending().
    - After mark_sent(), it no longer appears in get_pending().
    - count_pending() reflects the correct count at each stage.
    """
    import uuid

    from app.buffer import MessageBuffer

    # Use ":memory:" for a throw-away in-process SQLite database
    buf = MessageBuffer(db_path=":memory:")
    await buf.initialize()

    try:
        test_message = {
            "id": str(uuid.uuid4()),
            "sequence": 1,
            "producer_id": "test-producer",
            "timestamp": "2024-01-01T00:00:00.000Z",
            "frequency_hz": 1.0,
            "payload": {"data": "aGVsbG8=", "checksum": "deadbeef"},
        }

        # Buffer should start empty
        assert await buf.count_pending() == 0

        # Add a message
        success = await buf.add(test_message)
        assert success is True
        assert await buf.count_pending() == 1

        # Retrieve pending messages
        pending = await buf.get_pending(limit=10)
        assert len(pending) == 1
        assert pending[0]["id"] == test_message["id"]
        assert pending[0]["sequence"] == 1

        # Mark as sent
        await buf.mark_sent(test_message["id"])
        assert await buf.count_pending() == 0

        # get_pending should now return empty list
        pending_after = await buf.get_pending(limit=10)
        assert len(pending_after) == 0

    finally:
        await buf.close()


# ---------------------------------------------------------------------------
# Test 7: Checksum is deterministic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checksum_is_deterministic() -> None:
    """
    ProducerService._compute_checksum() must return the same hex string for
    the same input on every call.
    """
    from app.producer_service import ProducerService

    data = "hello, world!"
    checksum_1 = ProducerService._compute_checksum(data)
    checksum_2 = ProducerService._compute_checksum(data)

    assert checksum_1 == checksum_2
    # SHA-256 hex digest is always 64 hex characters
    assert len(checksum_1) == 64
    assert all(c in "0123456789abcdef" for c in checksum_1)

    # Different input must produce a different checksum
    different = ProducerService._compute_checksum("different input")
    assert different != checksum_1


# ---------------------------------------------------------------------------
# Test 8: Frequency update via API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frequency_update(client: AsyncClient, test_app) -> None:
    """
    PUT /api/frequency must call set_frequency() and return ProducerStatus.
    """
    token = await _get_token(client)

    response = await client.put(
        "/api/frequency",
        json={"frequency_hz": 42.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    # Now returns ProducerStatus, not the minimal {"frequency_hz": ...}
    assert "running" in body
    assert "frequency_hz" in body
    assert "buffered_count" in body

    # Verify that set_frequency was called with the correct value
    test_app.state.producer_service.set_frequency.assert_called_once_with(42.0)


# ---------------------------------------------------------------------------
# Test 9: Invalid frequency is rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frequency_out_of_range_rejected(client: AsyncClient) -> None:
    """
    PUT /api/frequency with frequency_hz > 1000 must return HTTP 422.
    """
    token = await _get_token(client)

    response = await client.put(
        "/api/frequency",
        json={"frequency_hz": 9999.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test 10: Login with wrong password returns 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient) -> None:
    """POST /api/auth/login with wrong password must return HTTP 401."""
    from app.config import settings

    response = await client.post(
        "/api/auth/login",
        json={"username": settings.AUTH_USERNAME, "password": "wrong-password"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 11: POST /api/start returns ProducerStatus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_producer_status(client: AsyncClient, test_app) -> None:
    """POST /api/start must return a ProducerStatus JSON object, not {success: true}."""
    test_app.state.producer_service = _make_mock_producer_service(running=True)
    token = await _get_token(client)

    response = await client.post(
        "/api/start",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    # Must be a ProducerStatus, not {"success": true}
    assert "running" in body
    assert "frequency_hz" in body
    assert "sequence_counter" in body
    assert "buffered_count" in body
    assert "sent_count" in body
    assert "kafka_connected" in body
    assert "success" not in body


# ---------------------------------------------------------------------------
# Test 12: POST /api/stop returns ProducerStatus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_returns_producer_status(client: AsyncClient, test_app) -> None:
    """POST /api/stop must return a ProducerStatus JSON object, not {success: true}."""
    test_app.state.producer_service = _make_mock_producer_service(running=False)
    token = await _get_token(client)

    response = await client.post(
        "/api/stop",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "running" in body
    assert "frequency_hz" in body
    assert "success" not in body


# ---------------------------------------------------------------------------
# Test 13: PUT /api/frequency returns ProducerStatus with updated value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frequency_update_returns_producer_status(
    client: AsyncClient, test_app
) -> None:
    """PUT /api/frequency must return ProducerStatus (not {frequency_hz: ...})."""
    test_app.state.producer_service = _make_mock_producer_service(frequency_hz=42.0)
    token = await _get_token(client)

    response = await client.put(
        "/api/frequency",
        json={"frequency_hz": 42.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "running" in body
    assert "frequency_hz" in body
    assert "sequence_counter" in body
    # Must NOT be the old minimal response shape
    assert "kafka_connected" in body


# ---------------------------------------------------------------------------
# Test 14: POST /api/start is idempotent (already running)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_when_already_running_is_idempotent(
    client: AsyncClient, test_app
) -> None:
    """POST /api/start when producer is already running must still return 200."""
    test_app.state.producer_service = _make_mock_producer_service(running=True)
    token = await _get_token(client)

    response = await client.post(
        "/api/start",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "running" in body


# ---------------------------------------------------------------------------
# Test 15: PUT /api/frequency lower bound rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frequency_below_minimum_rejected(client: AsyncClient) -> None:
    """PUT /api/frequency with frequency_hz < 1 must return HTTP 422."""
    token = await _get_token(client)

    response = await client.put(
        "/api/frequency",
        json={"frequency_hz": 0.5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test 16: GET /api/messages/recent returns a list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recent_messages_returns_list(client: AsyncClient) -> None:
    """GET /api/messages/recent must return an array (empty or populated)."""
    token = await _get_token(client)

    response = await client.get(
        "/api/messages/recent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ---------------------------------------------------------------------------
# Test 17: GET /api/messages/recent requires auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recent_messages_requires_auth(client: AsyncClient) -> None:
    """GET /api/messages/recent without token must return HTTP 401."""
    response = await client.get("/api/messages/recent")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 18: POST /api/start requires auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_requires_auth(client: AsyncClient) -> None:
    """POST /api/start without a Bearer token must return HTTP 401."""
    response = await client.post("/api/start")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 19: POST /api/stop requires auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_requires_auth(client: AsyncClient) -> None:
    """POST /api/stop without a Bearer token must return HTTP 401."""
    response = await client.post("/api/stop")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 20: WebSocket rejected without token (sync test — uses Starlette client)
# ---------------------------------------------------------------------------


def test_websocket_requires_token(test_app) -> None:
    """WebSocket /ws without a token query param must not send data."""
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    # Do NOT use TestClient as a context manager — that starts the real lifespan
    # which tries to open a SQLite file. The test_app fixture already injects mocks.
    c = TestClient(test_app)
    rejected = False
    try:
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()
    except (WebSocketDisconnect, Exception):
        rejected = True
    assert rejected, "Expected connection to be rejected without token"


# ---------------------------------------------------------------------------
# Test 21: WebSocket sends structured payload with status + recent_messages
# ---------------------------------------------------------------------------


def test_websocket_sends_structured_payload(test_app) -> None:
    """WebSocket /ws must send {status: {...}, recent_messages: [...]} frames."""
    from starlette.testclient import TestClient
    from app.auth import create_access_token

    token = create_access_token({"sub": "admin"})

    # Do NOT use TestClient as a context manager to avoid triggering the real lifespan
    c = TestClient(test_app)
    with c.websocket_connect(f"/ws?token={token}") as ws:
        payload = ws.receive_json()
        assert "status" in payload, "WS payload missing 'status' key"
        assert "recent_messages" in payload, "WS payload missing 'recent_messages' key"
        assert isinstance(payload["recent_messages"], list)
        s = payload["status"]
        assert "running" in s
        assert "frequency_hz" in s
        assert "buffered_count" in s
