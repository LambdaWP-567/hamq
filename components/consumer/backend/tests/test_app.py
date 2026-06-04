"""
HAMq Consumer — Backend Tests
================================
Covers:
  1. App starts and GET /api/health returns 200
  2. POST /api/auth/login returns a JWT
  3. Protected routes reject unauthenticated requests
  4. MessageStore save + retrieve cycle
  5. Missing sequence detection
  6. Checksum validation logic

Run with::

    cd components/consumer/backend
    pytest tests/ -v
"""

from __future__ import annotations

import hashlib
import pytest
import pytest_asyncio

# ---- Optional import guard so unit tests run without aiokafka installed ---- #
# aiokafka is not available in the test environment during early CI stages.
# We mock the KafkaConsumerService to keep tests self-contained.


# --------------------------------------------------------------------------- #
#  Fixtures
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def store(tmp_path):
    """Provide a temporary MessageStore backed by a fresh SQLite database."""
    from app.storage import MessageStore

    db_path = str(tmp_path / "test.db")
    s = MessageStore(db_path=db_path)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def sample_message():
    """A well-formed HAMq message dict (checksum matches payload)."""
    payload_data = "hello-hamq"
    checksum = hashlib.sha256(payload_data.encode()).hexdigest()
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "sequence": 42,
        "producer_id": "producer-0",
        "timestamp": "2026-01-01T00:00:00.000Z",
        "frequency_hz": 10.0,
        "payload": {
            "data": payload_data,
            "checksum": checksum,
        },
    }


@pytest.fixture
def bad_checksum_message():
    """A message whose payload.checksum does NOT match payload.data."""
    return {
        "id": "22222222-2222-2222-2222-222222222222",
        "sequence": 99,
        "producer_id": "producer-0",
        "timestamp": "2026-01-01T00:00:01.000Z",
        "frequency_hz": 10.0,
        "payload": {
            "data": "some-data",
            "checksum": "0000000000000000000000000000000000000000000000000000000000000000",
        },
    }


# --------------------------------------------------------------------------- #
#  HTTP client fixture
# --------------------------------------------------------------------------- #

@pytest_asyncio.fixture
async def client():
    """
    Return an async httpx TestClient for the FastAPI app.

    The ConsumerService is initialised directly here (not via lifespan) so that
    tests run without a real Kafka broker.  ASGITransport does not trigger the
    ASGI lifespan, so we bootstrap the service manually and inject it via
    set_service() before yielding the client.
    """
    import os
    import tempfile

    tmp = tempfile.mktemp(suffix=".db")
    # Force DB_PATH for this test run (may already be set by CI env)
    os.environ["DB_PATH"] = tmp

    # Import after setting env so Settings picks up the temp path
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.consumer_service import ConsumerService
    import app.api.routes as _routes

    # Initialise a real service (opens SQLite, starts stats loop).
    # Kafka consumer is NOT started — no broker needed for unit tests.
    svc = ConsumerService()
    await svc.initialize()
    _routes.set_service(svc)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    # Teardown: stop the service and remove the temp database.
    await svc.shutdown()
    _routes.set_service(None)  # type: ignore[arg-type]
    if os.path.exists(tmp):
        os.remove(tmp)


@pytest_asyncio.fixture
async def auth_token(client):
    """Return a valid JWT obtained via the login endpoint."""
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    # The default password hash in Settings matches "admin" — override for test.
    # If the hash doesn't match we use a fresh one.
    if resp.status_code != 200:
        from app.auth import hash_password, create_access_token
        return create_access_token("admin")
    return resp.json()["access_token"]


# --------------------------------------------------------------------------- #
#  Test 1 — Health endpoint
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_health_returns_200(client):
    """GET /api/health should return 200 without authentication."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "consumer_id" in body


# --------------------------------------------------------------------------- #
#  Test 2 — Login returns JWT
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_login_returns_jwt(client):
    """
    POST /api/auth/login with correct credentials should return a TokenResponse.
    We use create_access_token directly to avoid coupling to a specific hash.
    """
    # Patch the settings so the password hash matches "testpass".
    from app.auth import hash_password
    from app import config

    original_hash = config.settings.AUTH_PASSWORD_HASH
    original_user = config.settings.AUTH_USERNAME
    config.settings.AUTH_PASSWORD_HASH = hash_password("testpass")
    config.settings.AUTH_USERNAME = "testuser"

    try:
        resp = await client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "testpass"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
    finally:
        config.settings.AUTH_PASSWORD_HASH = original_hash
        config.settings.AUTH_USERNAME = original_user


@pytest.mark.asyncio
async def test_login_rejects_bad_credentials(client):
    """Wrong password should return 401."""
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
#  Test 3 — Protected routes require auth
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_protected_status_requires_auth(client):
    """GET /api/status without a token must return 403 or 401."""
    resp = await client.get("/api/status")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_protected_messages_requires_auth(client):
    """GET /api/messages without a token must return 403 or 401."""
    resp = await client.get("/api/messages")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_status_with_token(client):
    """GET /api/status with a valid token must return 200."""
    from app.auth import create_access_token

    token = create_access_token("admin")
    resp = await client.get(
        "/api/status", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "consumer_id" in body
    assert "running" in body


# --------------------------------------------------------------------------- #
#  Test 4 — MessageStore save + retrieve
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_store_save_and_retrieve(store, sample_message):
    """Saving a message and then querying by producer+sequence should return it."""
    inserted = await store.save(sample_message)
    assert inserted is True

    rows = await store.get_by_sequence_range(
        producer_id="producer-0",
        seq_from=1,
        seq_to=100,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == sample_message["id"]
    assert row["sequence"] == 42
    assert row["producer_id"] == "producer-0"
    assert row["checksum_valid"] == 1  # stored as integer


@pytest.mark.asyncio
async def test_store_deduplication(store, sample_message):
    """INSERT OR IGNORE must silently skip duplicate messages."""
    first = await store.save(sample_message)
    second = await store.save(sample_message)
    assert first is True
    assert second is False

    rows = await store.get_by_sequence_range("producer-0", 1, 100)
    assert len(rows) == 1  # still only one row


@pytest.mark.asyncio
async def test_store_get_recent(store, sample_message):
    """get_recent should return the most recently saved message."""
    await store.save(sample_message)
    recent = await store.get_recent(limit=10)
    assert len(recent) == 1
    assert recent[0]["id"] == sample_message["id"]


@pytest.mark.asyncio
async def test_store_stats(store, sample_message):
    """get_stats should reflect the saved message."""
    await store.save(sample_message)
    stats = await store.get_stats()
    assert stats["total_count"] == 1
    assert "producer-0" in stats["last_sequence_by_producer"]
    assert stats["last_sequence_by_producer"]["producer-0"] == 42


# --------------------------------------------------------------------------- #
#  Test 5 — Missing sequence detection
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_missing_sequences_none_when_all_present(store):
    """If all sequences in a range are present, the missing list is empty."""
    for seq in range(1, 6):
        msg = {
            "id": f"aaaaaaaa-0000-0000-0000-{seq:012d}",
            "sequence": seq,
            "producer_id": "producer-0",
            "timestamp": "2026-01-01T00:00:00Z",
            "frequency_hz": 1.0,
            "payload": {"data": "x", "checksum": hashlib.sha256(b"x").hexdigest()},
        }
        await store.save(msg)

    missing = await store.get_missing_sequences("producer-0", seq_from=1, seq_to=5)
    assert missing == []


@pytest.mark.asyncio
async def test_missing_sequences_detects_gap(store):
    """Sequences 2 and 4 are missing from 1–5."""
    for seq in [1, 3, 5]:
        msg = {
            "id": f"bbbbbbbb-0000-0000-0000-{seq:012d}",
            "sequence": seq,
            "producer_id": "producer-0",
            "timestamp": "2026-01-01T00:00:00Z",
            "frequency_hz": 1.0,
            "payload": {"data": "x", "checksum": hashlib.sha256(b"x").hexdigest()},
        }
        await store.save(msg)

    missing = await store.get_missing_sequences("producer-0", seq_from=1, seq_to=5)
    assert set(missing) == {2, 4}


@pytest.mark.asyncio
async def test_missing_sequences_isolated_to_producer(store):
    """Missing-sequence query for producer-A must not include gaps of producer-B."""
    # producer-A: sequences 1, 3 (missing 2)
    for seq in [1, 3]:
        msg = {
            "id": f"cccccccc-0000-0000-AAAA-{seq:012d}",
            "sequence": seq,
            "producer_id": "producer-A",
            "timestamp": "2026-01-01T00:00:00Z",
            "frequency_hz": 1.0,
            "payload": {"data": "x", "checksum": hashlib.sha256(b"x").hexdigest()},
        }
        await store.save(msg)

    # producer-B: sequences 1, 2, 3 (no gap)
    for seq in [1, 2, 3]:
        msg = {
            "id": f"cccccccc-0000-0000-BBBB-{seq:012d}",
            "sequence": seq,
            "producer_id": "producer-B",
            "timestamp": "2026-01-01T00:00:00Z",
            "frequency_hz": 1.0,
            "payload": {"data": "x", "checksum": hashlib.sha256(b"x").hexdigest()},
        }
        await store.save(msg)

    missing_a = await store.get_missing_sequences("producer-A", 1, 3)
    missing_b = await store.get_missing_sequences("producer-B", 1, 3)

    assert missing_a == [2]
    assert missing_b == []


# --------------------------------------------------------------------------- #
#  Test 6 — Checksum validation
# --------------------------------------------------------------------------- #

def test_checksum_valid():
    """_verify_checksum should return True when payload matches declared hash."""
    from app.storage import _verify_checksum

    data = "hello-hamq"
    good_hash = hashlib.sha256(data.encode()).hexdigest()
    assert _verify_checksum(data, good_hash) is True


def test_checksum_invalid():
    """_verify_checksum should return False on mismatch."""
    from app.storage import _verify_checksum

    assert _verify_checksum("hello", "0" * 64) is False


def test_checksum_empty_declared():
    """Missing checksum should be treated as valid (legacy messages)."""
    from app.storage import _verify_checksum

    assert _verify_checksum("any-data", "") is True


@pytest.mark.asyncio
async def test_store_marks_bad_checksum(store, bad_checksum_message):
    """Messages with invalid checksums must be stored with checksum_valid=0."""
    await store.save(bad_checksum_message)
    rows = await store.get_by_sequence_range("producer-0", 90, 110)
    assert len(rows) == 1
    assert rows[0]["checksum_valid"] == 0


@pytest.mark.asyncio
async def test_store_marks_good_checksum(store, sample_message):
    """Messages with valid checksums must be stored with checksum_valid=1."""
    await store.save(sample_message)
    rows = await store.get_by_sequence_range("producer-0", 40, 50)
    assert len(rows) == 1
    assert rows[0]["checksum_valid"] == 1
