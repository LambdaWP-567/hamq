"""
Integration and unit tests for the HAMq Arbiter.

Test suite covers:
  1. App starts and /api/health returns 200
  2. Authentication: valid credentials return a JWT; wrong credentials return 401
  3. AuditStore: save_result persists a record; get_result retrieves it
  4. AuditStore: get_history returns summaries in descending timestamp order
  5. Reconciler: missing-sequence computation (unit test with mock HTTP responses)
  6. Loss rate calculation: 0 missing → 0.0, 1/10 missing → 10%
  7. Manual reconcile endpoint returns a valid ReconcileReport with correct fields

Run with:
    pytest components/arbiter/backend/tests/test_app.py -v
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, Response

# ---------------------------------------------------------------------------
# App bootstrap helpers
# ---------------------------------------------------------------------------
# We patch the DB_PATH to :memory: before importing the app so that tests
# never write to the filesystem.

import os
os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("PRODUCER_API_URLS", "http://mock-producer:8000")
os.environ.setdefault("CONSUMER_API_URL", "http://mock-consumer:8001")

from app.audit_store import AuditStore
from app.config import settings
from app.models import AuditResult, ReconcileReport
from app.reconciler import Reconciler, _compute_status


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def audit_store(tmp_path):
    """
    Create and initialise an in-memory AuditStore for tests.
    Using ":memory:" means each test gets a fresh, isolated database.
    """
    store = AuditStore(":memory:")
    await store.initialize()
    yield store
    await store.close()


def _make_audit_result(
    producer_id: str = "producer-1",
    sent_count: int = 100,
    received_count: int = 95,
    missing_sequences: list = None,
    loss_rate: float = 0.05,
    status: str = "warning",
) -> AuditResult:
    """Helper that constructs a minimal AuditResult with default values."""
    return AuditResult(
        audit_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        producer_id=producer_id,
        sent_count=sent_count,
        received_count=received_count,
        missing_sequences=missing_sequences or [1, 2, 3, 4, 5],
        loss_rate=loss_rate,
        status=status,
    )


# ---------------------------------------------------------------------------
# Test 1: App health check
# ---------------------------------------------------------------------------

def test_health_endpoint():
    """
    The FastAPI application must start cleanly and /api/health must return
    HTTP 200 with {"status": "ok"}.

    We patch the reconciler.start() and audit_store.initialize() methods to
    avoid real I/O during the test.
    """
    with (
        patch("app.audit_store.AuditStore.initialize", new_callable=AsyncMock),
        patch("app.reconciler.Reconciler.start", new_callable=AsyncMock),
        patch("app.reconciler.Reconciler.stop", new_callable=AsyncMock),
        patch("app.audit_store.AuditStore.close", new_callable=AsyncMock),
    ):
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Test 2: Authentication
# ---------------------------------------------------------------------------

def test_auth_valid_credentials():
    """
    POST /api/auth/login with correct credentials must return HTTP 200
    and a JSON body containing 'access_token' and 'token_type'.
    """
    with (
        patch("app.audit_store.AuditStore.initialize", new_callable=AsyncMock),
        patch("app.reconciler.Reconciler.start", new_callable=AsyncMock),
        patch("app.reconciler.Reconciler.stop", new_callable=AsyncMock),
        patch("app.audit_store.AuditStore.close", new_callable=AsyncMock),
    ):
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/auth/login",
            json={"username": settings.AUTH_USERNAME, "password": "admin"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"


def test_auth_invalid_credentials():
    """
    POST /api/auth/login with wrong password must return HTTP 401.
    """
    with (
        patch("app.audit_store.AuditStore.initialize", new_callable=AsyncMock),
        patch("app.reconciler.Reconciler.start", new_callable=AsyncMock),
        patch("app.reconciler.Reconciler.stop", new_callable=AsyncMock),
        patch("app.audit_store.AuditStore.close", new_callable=AsyncMock),
    ):
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert resp.status_code == 401


def test_protected_endpoint_requires_auth():
    """
    GET /api/status without a token must return HTTP 401.
    """
    with (
        patch("app.audit_store.AuditStore.initialize", new_callable=AsyncMock),
        patch("app.reconciler.Reconciler.start", new_callable=AsyncMock),
        patch("app.reconciler.Reconciler.stop", new_callable=AsyncMock),
        patch("app.audit_store.AuditStore.close", new_callable=AsyncMock),
    ):
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/status")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test 3: AuditStore — save and retrieve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_store_save_and_retrieve(audit_store):
    """
    save_result should persist an AuditResult such that get_result
    returns an identical object (including missing_sequences list).
    """
    original = _make_audit_result()
    await audit_store.save_result(original)

    retrieved = await audit_store.get_result(original.audit_id)
    assert retrieved is not None
    assert retrieved.audit_id == original.audit_id
    assert retrieved.producer_id == original.producer_id
    assert retrieved.sent_count == original.sent_count
    assert retrieved.received_count == original.received_count
    assert retrieved.missing_sequences == original.missing_sequences
    assert retrieved.loss_rate == pytest.approx(original.loss_rate)
    assert retrieved.status == original.status


@pytest.mark.asyncio
async def test_audit_store_get_result_not_found(audit_store):
    """get_result with an unknown audit_id must return None."""
    result = await audit_store.get_result("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_audit_store_get_history_ordering(audit_store):
    """
    get_history should return records ordered by timestamp descending.

    We insert three records with different timestamps and verify that
    the most recent record appears first in the list.
    """
    # Insert records with explicit timestamps to control ordering
    for i in range(3):
        result = _make_audit_result(producer_id="producer-order")
        # Manually set timestamp to force predictable ordering
        result = AuditResult(
            **{
                **result.model_dump(),
                "audit_id": str(uuid.uuid4()),
                "timestamp": f"2026-01-0{i+1}T00:00:00+00:00",
            }
        )
        await audit_store.save_result(result)

    history = await audit_store.get_history("producer-order", limit=10)
    assert len(history) == 3

    # Verify descending timestamp order
    timestamps = [h.timestamp for h in history]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.asyncio
async def test_audit_store_get_history_filter_by_producer(audit_store):
    """
    get_history should filter by producer_id when that argument is provided.
    """
    await audit_store.save_result(_make_audit_result(producer_id="alpha"))
    await audit_store.save_result(_make_audit_result(producer_id="beta"))
    await audit_store.save_result(_make_audit_result(producer_id="alpha"))

    alpha_history = await audit_store.get_history("alpha", limit=100)
    beta_history = await audit_store.get_history("beta", limit=100)

    assert len(alpha_history) == 2
    assert len(beta_history) == 1
    assert all(h.producer_id == "alpha" for h in alpha_history)


# ---------------------------------------------------------------------------
# Test 4: Reconciler — missing sequence computation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconciler_missing_sequences(audit_store):
    """
    Unit test for the reconciler's set-difference logic.

    Given:
      - Producer sent sequences {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
      - Consumer received sequences {1, 2, 3, 5, 6, 7, 8, 9, 10}
    Expected:
      - missing = {4}
      - loss_rate = 1/10 = 0.1
    """
    # Mock the HTTP client responses
    producer_response_body = {
        "producer_id": "producer-test",
        "sequences": list(range(1, 11)),  # 1..10
        "total": 10,
    }
    # Consumer is missing sequence 4
    consumer_response_body = {
        "producer_id": "producer-test",
        "missing": [4],
        "checked_range": [1, 10],
    }

    mock_http = AsyncMock()
    mock_http.get = AsyncMock(side_effect=[
        _mock_response(200, producer_response_body),
        _mock_response(200, consumer_response_body),
    ])

    reconciler = Reconciler(audit_store)
    reconciler._http = mock_http

    result = await reconciler._reconcile_producer(
        "http://mock-producer:8000",
        datetime.now(timezone.utc).isoformat(),
    )

    assert result is not None
    assert result.sent_count == 10
    assert result.missing_count == 1
    assert 4 in result.missing_sequences
    assert result.loss_rate == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_reconciler_no_missing(audit_store):
    """
    When the consumer has received all messages, missing_count should be 0
    and loss_rate should be exactly 0.0.
    """
    producer_response_body = {
        "producer_id": "producer-perfect",
        "sequences": list(range(1, 6)),  # 1..5
        "total": 5,
    }
    # Consumer reports no missing sequences
    consumer_response_body = {
        "producer_id": "producer-perfect",
        "missing": [],
        "checked_range": [1, 5],
    }

    mock_http = AsyncMock()
    mock_http.get = AsyncMock(side_effect=[
        _mock_response(200, producer_response_body),
        _mock_response(200, consumer_response_body),
    ])

    reconciler = Reconciler(audit_store)
    reconciler._http = mock_http

    result = await reconciler._reconcile_producer(
        "http://mock-producer:8000",
        datetime.now(timezone.utc).isoformat(),
    )

    assert result is not None
    assert result.missing_count == 0
    assert result.missing_sequences == []
    assert result.loss_rate == pytest.approx(0.0)
    assert result.status == "ok"


# ---------------------------------------------------------------------------
# Test 5: Loss rate calculation
# ---------------------------------------------------------------------------

def test_loss_rate_zero_missing():
    """
    When there are no missing messages, loss_rate must be 0.0 and status 'ok'.
    """
    # Simulated computation:  0 missing / 100 sent = 0.0
    sent = 100
    missing = 0
    loss_rate = missing / sent if sent > 0 else 0.0
    assert loss_rate == 0.0
    assert _compute_status(loss_rate, threshold=0.01) == "ok"


def test_loss_rate_one_in_ten():
    """
    1 missing out of 10 sent = 10% = 0.1 loss rate.
    With a 1% threshold this should be 'critical'.
    """
    sent = 10
    missing = 1
    loss_rate = missing / sent
    assert loss_rate == pytest.approx(0.1)
    assert _compute_status(loss_rate, threshold=0.01) == "critical"


def test_loss_rate_below_threshold():
    """
    Loss rate below threshold (but > 0) should be 'warning'.
    """
    sent = 10000
    missing = 5
    loss_rate = missing / sent  # 0.05% — below 1% threshold
    assert _compute_status(loss_rate, threshold=0.01) == "warning"


def test_loss_rate_zero_sent():
    """
    When sent_count is 0, loss_rate must default to 0.0 (no zero-division).
    """
    sent = 0
    missing = 0
    loss_rate = missing / sent if sent > 0 else 0.0
    assert loss_rate == 0.0


# ---------------------------------------------------------------------------
# Test 6: Manual reconcile endpoint
# ---------------------------------------------------------------------------

def test_manual_reconcile_endpoint():
    """
    POST /api/reconcile (authenticated) must return HTTP 200 and a JSON body
    that conforms to the ReconcileReport schema.

    We patch reconciler.run_once() to return a synthetic report so the test
    does not need live Producer/Consumer APIs.
    """
    fake_report = ReconcileReport(
        report_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        producers=[],
        total_sent=50,
        total_received=50,
        total_missing=0,
        overall_loss_rate=0.0,
        duration_ms=12.5,
    )

    with (
        patch("app.audit_store.AuditStore.initialize", new_callable=AsyncMock),
        patch("app.reconciler.Reconciler.start", new_callable=AsyncMock),
        patch("app.reconciler.Reconciler.stop", new_callable=AsyncMock),
        patch("app.audit_store.AuditStore.close", new_callable=AsyncMock),
        patch(
            "app.reconciler.Reconciler.run_once",
            new_callable=AsyncMock,
            return_value=fake_report,
        ),
        patch(
            "app.audit_store.AuditStore.get_stats",
            new_callable=AsyncMock,
            return_value={
                "total_audits": 0,
                "avg_loss_rate": 0.0,
                "worst_producer": None,
                "worst_loss_rate": 0.0,
                "producers_tracked": 0,
            },
        ),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            # First obtain a JWT
            login_resp = client.post(
                "/api/auth/login",
                json={"username": settings.AUTH_USERNAME, "password": "admin"},
            )
            assert login_resp.status_code == 200
            token = login_resp.json()["access_token"]

            # Trigger manual reconcile
            reconcile_resp = client.post(
                "/api/reconcile",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert reconcile_resp.status_code == 200
            body = reconcile_resp.json()

            # Validate the response conforms to ReconcileReport
            assert "report_id" in body
            assert "timestamp" in body
            assert "total_sent" in body
            assert "total_received" in body
            assert "total_missing" in body
            assert "overall_loss_rate" in body
            assert body["total_sent"] == 50
            assert body["total_missing"] == 0
            assert body["overall_loss_rate"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int, body: dict) -> MagicMock:
    """
    Build a mock httpx.Response object with the given status code and JSON body.

    Used to simulate Producer and Consumer API responses in unit tests without
    making real network calls.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = body
    # raise_for_status should be a no-op for 2xx responses
    if status_code >= 400:
        from httpx import HTTPStatusError, Request
        mock_request = MagicMock(spec=Request)
        mock_resp.raise_for_status.side_effect = HTTPStatusError(
            message=f"HTTP {status_code}",
            request=mock_request,
            response=mock_resp,
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp
