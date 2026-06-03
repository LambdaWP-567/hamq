"""
Pytest test suite for the HAMq Controller API.

Tests cover:
1. Health endpoint returns 200
2. /metrics returns Prometheus text format
3. GET /api/nodes returns list (mocked K8s client)
4. GET /api/pods returns list (mocked K8s client)
5. POST /api/chaos/run validates input
6. GET /api/chaos/status works
7. Authentication required on protected endpoints

All Kubernetes interactions are mocked so no cluster is needed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import AsyncGenerator, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Ensure we can import app from the backend directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Patch Kubernetes config loading BEFORE importing app modules so the import
# itself does not attempt to contact a real cluster.
with patch("kubernetes.config.load_incluster_config", return_value=None), \
     patch("kubernetes.config.load_kube_config", return_value=None), \
     patch("kubernetes.client.CoreV1Api", return_value=MagicMock()), \
     patch("kubernetes.client.NetworkingV1Api", return_value=MagicMock()), \
     patch("kubernetes.client.AppsV1Api", return_value=MagicMock()):
    from app.main import app
    from app.models import (
        ClusterEvent,
        ChaosConfig,
        NodeInfo,
        PodInfo,
        NetworkPolicyInfo,
        TokenResponse,
    )
    from app.auth import create_access_token
    from app.config import settings
    from app.k8s_client import K8sClient
    from app.chaos_engine import ChaosEngine
    from app.event_store import EventStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(event_type: str = "pod_restart", target: str = "test-pod") -> ClusterEvent:
    return ClusterEvent(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        event_type=event_type,
        target=target,
        namespace="kafka",
        status="success",
        details="Test event",
    )


def _make_token(username: str = "admin") -> str:
    """Generate a valid JWT for testing."""
    return create_access_token(data={"sub": username})


def _auth_headers(username: str = "admin") -> dict:
    return {"Authorization": f"Bearer {_make_token(username)}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_k8s_client() -> MagicMock:
    """
    Return a MagicMock that mimics a connected K8sClient.
    All async methods are patched to return sensible defaults.
    """
    mock = MagicMock(spec=K8sClient)
    mock.is_connected = True

    mock.list_pods = AsyncMock(
        return_value=[
            PodInfo(
                name="hamq-kafka-kafka-0",
                namespace="kafka",
                status="Running",
                node="node-1",
                ready=True,
                restart_count=0,
            ),
            PodInfo(
                name="hamq-kafka-kafka-1",
                namespace="kafka",
                status="Running",
                node="node-2",
                ready=True,
                restart_count=1,
            ),
        ]
    )

    mock.list_nodes = AsyncMock(
        return_value=[
            NodeInfo(
                name="node-1",
                status="Ready",
                schedulable=True,
                roles=["worker"],
                conditions=[{"type": "Ready", "status": "True", "message": ""}],
            ),
            NodeInfo(
                name="node-2",
                status="Ready",
                schedulable=True,
                roles=["worker"],
                conditions=[{"type": "Ready", "status": "True", "message": ""}],
            ),
        ]
    )

    mock.list_network_policies = AsyncMock(return_value=[])

    mock.restart_pod = AsyncMock(return_value=_make_event("pod_restart", "hamq-kafka-kafka-0"))
    mock.delete_pod = AsyncMock(return_value=_make_event("pod_delete", "hamq-kafka-kafka-0"))
    mock.cordon_node = AsyncMock(return_value=_make_event("node_cordon", "node-1"))
    mock.uncordon_node = AsyncMock(return_value=_make_event("node_uncordon", "node-1"))
    mock.drain_node = AsyncMock(return_value=_make_event("node_drain", "node-1"))
    mock.create_network_partition = AsyncMock(
        return_value=_make_event("network_partition_create", "chaos-partition-test")
    )
    mock.delete_network_partition = AsyncMock(
        return_value=_make_event("network_partition_delete", "chaos-partition-test")
    )

    return mock


@pytest.fixture
def mock_event_store() -> MagicMock:
    mock = MagicMock(spec=EventStore)
    mock.initialize = AsyncMock()
    mock.close = AsyncMock()
    mock.save_event = AsyncMock()
    mock.get_events = AsyncMock(return_value=[_make_event()])
    return mock


@pytest.fixture
def mock_chaos_engine(mock_k8s_client: MagicMock) -> MagicMock:
    mock = MagicMock(spec=ChaosEngine)
    mock.last_event = _make_event("chaos_random", "hamq-kafka-kafka-0")
    mock.run_chaos = AsyncMock(return_value=_make_event("chaos_random", "hamq-kafka-kafka-0"))
    return mock


@pytest.fixture
def client(
    mock_k8s_client: MagicMock,
    mock_event_store: MagicMock,
    mock_chaos_engine: MagicMock,
) -> TestClient:
    """
    Return a synchronous TestClient with all singletons replaced by mocks.

    The lifespan is bypassed by injecting state directly onto app.state before
    the client starts.
    """
    app.state.k8s_client = mock_k8s_client
    app.state.event_store = mock_event_store
    app.state.chaos_engine = mock_chaos_engine
    app.state.settings = settings

    # Use raise_server_exceptions=True so test failures surface clearly
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# 1. Health endpoint
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self, client: TestClient) -> None:
        response = client.get("/api/health")
        data = response.json()
        assert data.get("status") == "ok"

    def test_health_does_not_require_auth(self, client: TestClient) -> None:
        """Health endpoint must be reachable without a JWT token."""
        response = client.get("/api/health")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 2. Metrics endpoint
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_metrics_returns_200(self, client: TestClient) -> None:
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_content_type_is_prometheus(self, client: TestClient) -> None:
        response = client.get("/metrics")
        content_type = response.headers.get("content-type", "")
        # Prometheus text exposition format uses text/plain
        assert "text/plain" in content_type

    def test_metrics_body_is_not_empty(self, client: TestClient) -> None:
        response = client.get("/metrics")
        assert len(response.text) > 0

    def test_metrics_contains_python_info(self, client: TestClient) -> None:
        """Prometheus client always exports python_info by default."""
        response = client.get("/metrics")
        assert "python_info" in response.text or "process_" in response.text


# ---------------------------------------------------------------------------
# 3. GET /api/nodes
# ---------------------------------------------------------------------------

class TestListNodes:
    def test_list_nodes_returns_200_with_auth(
        self,
        client: TestClient,
        mock_k8s_client: MagicMock,
    ) -> None:
        response = client.get("/api/nodes", headers=_auth_headers())
        assert response.status_code == 200

    def test_list_nodes_returns_list(
        self,
        client: TestClient,
        mock_k8s_client: MagicMock,
    ) -> None:
        response = client.get("/api/nodes", headers=_auth_headers())
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_list_nodes_response_contains_expected_fields(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/api/nodes", headers=_auth_headers())
        node = response.json()[0]
        assert "name" in node
        assert "status" in node
        assert "schedulable" in node
        assert "roles" in node

    def test_list_nodes_node_values_correct(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/api/nodes", headers=_auth_headers())
        nodes = response.json()
        names = {n["name"] for n in nodes}
        assert "node-1" in names
        assert "node-2" in names

    def test_list_nodes_requires_auth(self, client: TestClient) -> None:
        response = client.get("/api/nodes")
        assert response.status_code == 401

    def test_list_nodes_rejects_invalid_token(self, client: TestClient) -> None:
        response = client.get(
            "/api/nodes",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 4. GET /api/pods
# ---------------------------------------------------------------------------

class TestListPods:
    def test_list_pods_returns_200_with_auth(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/api/pods", headers=_auth_headers())
        assert response.status_code == 200

    def test_list_pods_returns_list(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/api/pods", headers=_auth_headers())
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_list_pods_response_contains_expected_fields(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/api/pods", headers=_auth_headers())
        pod = response.json()[0]
        assert "name" in pod
        assert "namespace" in pod
        assert "status" in pod
        assert "node" in pod
        assert "ready" in pod
        assert "restart_count" in pod

    def test_list_pods_pod_values_correct(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/api/pods", headers=_auth_headers())
        pods = response.json()
        names = {p["name"] for p in pods}
        assert "hamq-kafka-kafka-0" in names
        assert "hamq-kafka-kafka-1" in names

    def test_list_pods_requires_auth(self, client: TestClient) -> None:
        response = client.get("/api/pods")
        assert response.status_code == 401

    def test_list_pods_rejects_expired_token(self, client: TestClient) -> None:
        # A syntactically valid but wrong-key token
        from datetime import timedelta

        bad_token = create_access_token(
            data={"sub": "admin"}, expires_delta=timedelta(seconds=-1)
        )
        response = client.get(
            "/api/pods",
            headers={"Authorization": f"Bearer {bad_token}"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 5. POST /api/chaos/run  — input validation
# ---------------------------------------------------------------------------

class TestChaosRun:
    def test_chaos_run_valid_payload_returns_200(
        self,
        client: TestClient,
        mock_chaos_engine: MagicMock,
    ) -> None:
        payload = {
            "enabled": True,
            "action": "random_pod_delete",
            "target_namespace": "kafka",
            "dry_run": True,
        }
        response = client.post("/api/chaos/run", json=payload, headers=_auth_headers())
        assert response.status_code == 200

    def test_chaos_run_returns_cluster_event(
        self,
        client: TestClient,
        mock_chaos_engine: MagicMock,
    ) -> None:
        payload = {
            "enabled": True,
            "action": "random_pod_delete",
            "target_namespace": "kafka",
            "dry_run": True,
        }
        response = client.post("/api/chaos/run", json=payload, headers=_auth_headers())
        data = response.json()
        assert "event_id" in data
        assert "timestamp" in data
        assert "event_type" in data
        assert "status" in data

    def test_chaos_run_invalid_action_returns_422(
        self,
        client: TestClient,
    ) -> None:
        """An action value not in the Literal enum must be rejected with 422."""
        payload = {
            "enabled": True,
            "action": "destroy_everything",  # not a valid literal
            "target_namespace": "kafka",
            "dry_run": False,
        }
        response = client.post("/api/chaos/run", json=payload, headers=_auth_headers())
        assert response.status_code == 422

    def test_chaos_run_missing_body_returns_422(
        self,
        client: TestClient,
    ) -> None:
        response = client.post("/api/chaos/run", headers=_auth_headers())
        assert response.status_code == 422

    def test_chaos_run_node_drain_action_accepted(
        self,
        client: TestClient,
        mock_chaos_engine: MagicMock,
    ) -> None:
        payload = {
            "enabled": True,
            "action": "node_drain",
            "target_namespace": "kafka",
            "dry_run": True,
        }
        response = client.post("/api/chaos/run", json=payload, headers=_auth_headers())
        assert response.status_code == 200

    def test_chaos_run_network_partition_action_accepted(
        self,
        client: TestClient,
        mock_chaos_engine: MagicMock,
    ) -> None:
        payload = {
            "enabled": True,
            "action": "network_partition",
            "target_namespace": "kafka",
            "dry_run": True,
        }
        response = client.post("/api/chaos/run", json=payload, headers=_auth_headers())
        assert response.status_code == 200

    def test_chaos_run_requires_auth(self, client: TestClient) -> None:
        payload = {
            "enabled": True,
            "action": "random_pod_delete",
            "target_namespace": "kafka",
            "dry_run": True,
        }
        response = client.post("/api/chaos/run", json=payload)
        assert response.status_code == 401

    def test_chaos_run_calls_engine(
        self,
        client: TestClient,
        mock_chaos_engine: MagicMock,
    ) -> None:
        """Verify the route actually delegates to the ChaosEngine."""
        payload = {
            "enabled": True,
            "action": "random_pod_delete",
            "target_namespace": "kafka",
            "dry_run": True,
        }
        client.post("/api/chaos/run", json=payload, headers=_auth_headers())
        mock_chaos_engine.run_chaos.assert_called_once()


# ---------------------------------------------------------------------------
# 6. GET /api/chaos/status
# ---------------------------------------------------------------------------

class TestChaosStatus:
    def test_chaos_status_returns_200(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/api/chaos/status", headers=_auth_headers())
        assert response.status_code == 200

    def test_chaos_status_returns_cluster_event(
        self,
        client: TestClient,
        mock_chaos_engine: MagicMock,
    ) -> None:
        response = client.get("/api/chaos/status", headers=_auth_headers())
        data = response.json()
        # last_event is not None for mock, so we get a cluster event
        assert "event_id" in data
        assert "event_type" in data

    def test_chaos_status_returns_null_when_no_event(
        self,
        client: TestClient,
        mock_chaos_engine: MagicMock,
    ) -> None:
        """When last_event is None the endpoint should return null (200)."""
        mock_chaos_engine.last_event = None
        response = client.get("/api/chaos/status", headers=_auth_headers())
        assert response.status_code == 200
        assert response.json() is None

    def test_chaos_status_requires_auth(self, client: TestClient) -> None:
        response = client.get("/api/chaos/status")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 7. Authentication on all protected endpoints
# ---------------------------------------------------------------------------

class TestAuthProtection:
    """Verify that every protected endpoint rejects unauthenticated requests."""

    PROTECTED_ENDPOINTS = [
        ("GET", "/api/status"),
        ("GET", "/api/pods"),
        ("GET", "/api/nodes"),
        ("GET", "/api/network-policies"),
        ("GET", "/api/chaos/status"),
        ("GET", "/api/events"),
    ]

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_endpoint_rejects_no_token(
        self,
        client: TestClient,
        method: str,
        path: str,
    ) -> None:
        response = client.request(method, path)
        assert response.status_code == 401, (
            f"{method} {path} should return 401 without a token, got {response.status_code}"
        )

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_endpoint_rejects_garbage_token(
        self,
        client: TestClient,
        method: str,
        path: str,
    ) -> None:
        response = client.request(
            method,
            path,
            headers={"Authorization": "Bearer garbage"},
        )
        assert response.status_code == 401, (
            f"{method} {path} should return 401 with a garbage token, got {response.status_code}"
        )

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_endpoint_accepts_valid_token(
        self,
        client: TestClient,
        method: str,
        path: str,
    ) -> None:
        response = client.request(method, path, headers=_auth_headers())
        assert response.status_code in (200, 201), (
            f"{method} {path} should succeed with a valid token, got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# 8. Login endpoint
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_returns_token_for_valid_credentials(
        self,
        client: TestClient,
    ) -> None:
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        # The default password hash in settings is bcrypt("admin")
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_returns_401_for_wrong_password(
        self,
        client: TestClient,
    ) -> None:
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrongpassword"},
        )
        assert response.status_code == 401

    def test_login_returns_401_for_unknown_user(
        self,
        client: TestClient,
    ) -> None:
        response = client.post(
            "/api/auth/login",
            json={"username": "hacker", "password": "admin"},
        )
        assert response.status_code == 401

    def test_login_missing_fields_returns_422(
        self,
        client: TestClient,
    ) -> None:
        response = client.post("/api/auth/login", json={"username": "admin"})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# 9. Pod restart / delete endpoints
# ---------------------------------------------------------------------------

class TestPodActions:
    def test_restart_pod_returns_event(
        self,
        client: TestClient,
        mock_k8s_client: MagicMock,
    ) -> None:
        response = client.post(
            "/api/pods/hamq-kafka-kafka-0/restart",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "pod_restart"

    def test_delete_pod_returns_event(
        self,
        client: TestClient,
        mock_k8s_client: MagicMock,
    ) -> None:
        response = client.post(
            "/api/pods/hamq-kafka-kafka-0/delete",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "pod_delete"

    def test_restart_pod_requires_auth(self, client: TestClient) -> None:
        response = client.post("/api/pods/hamq-kafka-kafka-0/restart")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 10. Node action endpoints
# ---------------------------------------------------------------------------

class TestNodeActions:
    def test_cordon_node_returns_event(
        self,
        client: TestClient,
        mock_k8s_client: MagicMock,
    ) -> None:
        response = client.post(
            "/api/nodes/node-1/cordon",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "node_cordon"

    def test_uncordon_node_returns_event(
        self,
        client: TestClient,
        mock_k8s_client: MagicMock,
    ) -> None:
        response = client.post(
            "/api/nodes/node-1/uncordon",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "node_uncordon"

    def test_drain_node_returns_event(
        self,
        client: TestClient,
        mock_k8s_client: MagicMock,
    ) -> None:
        response = client.post(
            "/api/nodes/node-1/drain",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "node_drain"

    def test_node_actions_require_auth(self, client: TestClient) -> None:
        for path in ["/api/nodes/node-1/cordon", "/api/nodes/node-1/uncordon", "/api/nodes/node-1/drain"]:
            response = client.post(path)
            assert response.status_code == 401, f"{path} should require auth"


# ---------------------------------------------------------------------------
# 11. Network policy endpoints
# ---------------------------------------------------------------------------

class TestNetworkPolicies:
    def test_list_network_policies_returns_list(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/api/network-policies", headers=_auth_headers())
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_network_partition_returns_201(
        self,
        client: TestClient,
        mock_k8s_client: MagicMock,
    ) -> None:
        payload = {
            "name": "test-partition",
            "target_namespace": "kafka",
            "pod_selector": {"statefulset.kubernetes.io/pod-name": "hamq-kafka-kafka-0"},
        }
        response = client.post(
            "/api/network-policies",
            json=payload,
            headers=_auth_headers(),
        )
        assert response.status_code == 201

    def test_delete_network_partition_returns_event(
        self,
        client: TestClient,
        mock_k8s_client: MagicMock,
    ) -> None:
        response = client.delete(
            "/api/network-policies/test-partition",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "network_partition_delete"

    def test_create_partition_requires_auth(self, client: TestClient) -> None:
        payload = {
            "name": "bad-partition",
            "target_namespace": "kafka",
            "pod_selector": {},
        }
        response = client.post("/api/network-policies", json=payload)
        assert response.status_code == 401

    def test_create_partition_missing_name_returns_422(
        self,
        client: TestClient,
    ) -> None:
        payload = {
            "target_namespace": "kafka",
            "pod_selector": {},
            # missing "name"
        }
        response = client.post(
            "/api/network-policies",
            json=payload,
            headers=_auth_headers(),
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# 12. Events endpoint
# ---------------------------------------------------------------------------

class TestEvents:
    def test_get_events_returns_list(
        self,
        client: TestClient,
        mock_event_store: MagicMock,
    ) -> None:
        response = client.get("/api/events", headers=_auth_headers())
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_events_limit_parameter_accepted(
        self,
        client: TestClient,
    ) -> None:
        response = client.get("/api/events?limit=10", headers=_auth_headers())
        assert response.status_code == 200

    def test_get_events_invalid_limit_returns_422(
        self,
        client: TestClient,
    ) -> None:
        # limit must be >= 1
        response = client.get("/api/events?limit=0", headers=_auth_headers())
        assert response.status_code == 422

    def test_get_events_event_type_filter_accepted(
        self,
        client: TestClient,
    ) -> None:
        response = client.get(
            "/api/events?event_type=pod_restart",
            headers=_auth_headers(),
        )
        assert response.status_code == 200

    def test_get_events_requires_auth(self, client: TestClient) -> None:
        response = client.get("/api/events")
        assert response.status_code == 401
