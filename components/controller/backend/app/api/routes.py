"""
API route definitions for the HAMq Controller.

All routes (except /health and /metrics) require a valid JWT Bearer token.

Route summary:
    POST   /api/auth/login               → JWT token
    GET    /api/health                   → health check
    GET    /metrics                      → Prometheus metrics
    GET    /api/status                   → full cluster status

    GET    /api/pods                     → list Kafka pods
    POST   /api/pods/{name}/restart      → graceful pod restart
    POST   /api/pods/{name}/delete       → force-delete pod (grace=0)

    GET    /api/nodes                    → list all nodes
    POST   /api/nodes/{name}/cordon      → cordon node
    POST   /api/nodes/{name}/uncordon    → uncordon node
    POST   /api/nodes/{name}/drain       → drain node

    GET    /api/network-policies         → list active partitions
    POST   /api/network-policies         → create partition
    DELETE /api/network-policies/{name}  → remove partition

    POST   /api/chaos/run                → trigger chaos action
    GET    /api/chaos/status             → last chaos event

    GET    /api/events                   → paginated event history

    WS     /ws                           → real-time status stream
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status

from app.auth import get_current_user, login_for_access_token
from app.chaos_engine import ChaosEngine
from app.event_store import EventStore
from app.k8s_client import K8sClient
from app.metrics import (
    active_network_partitions_gauge,
    controller_operations_total,
    kafka_pods_ready_gauge,
    nodes_schedulable_gauge,
)
from app.models import (
    ChaosConfig,
    ClusterEvent,
    ControllerStatus,
    LoginRequest,
    NetworkPartitionRequest,
    NodeInfo,
    PodInfo,
    TokenResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency injection helpers
# ---------------------------------------------------------------------------
# The FastAPI app.state is used as a simple DI container.
# These helpers extract the shared singletons from the request state.

def _get_k8s(request) -> K8sClient:
    return request.app.state.k8s_client


def _get_store(request) -> EventStore:
    return request.app.state.event_store


def _get_chaos(request) -> ChaosEngine:
    return request.app.state.chaos_engine


def _get_settings(request):
    return request.app.state.settings


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@router.post(
    "/api/auth/login",
    response_model=TokenResponse,
    summary="Authenticate and receive a JWT token",
    tags=["auth"],
)
async def login(request: LoginRequest) -> TokenResponse:
    """
    Accepts username + password and returns a signed JWT.
    The token must be sent as a ``Bearer`` token in the ``Authorization`` header.
    """
    return await login_for_access_token(request)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get(
    "/api/health",
    summary="Health check",
    tags=["health"],
)
async def health() -> Dict[str, str]:
    """Simple liveness probe — returns 200 when the process is running."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@router.get(
    "/api/status",
    response_model=ControllerStatus,
    summary="Full cluster status snapshot",
    tags=["status"],
)
async def get_status(
    request: Request,
    _user: str = Depends(get_current_user),
) -> ControllerStatus:
    """
    Returns a comprehensive snapshot of:
    - Kubernetes connectivity
    - Kafka pod states
    - Node states
    - Active network partitions
    - Last 20 audit events
    """
    k8s: K8sClient = _get_k8s(request)
    store: EventStore = _get_store(request)
    cfg = _get_settings(request)

    kafka_pods, nodes, partitions, recent_events = await asyncio.gather(
        k8s.list_pods(cfg.KAFKA_NAMESPACE, cfg.KAFKA_POD_LABEL_SELECTOR),
        k8s.list_nodes(),
        k8s.list_network_policies(cfg.KAFKA_NAMESPACE),
        store.get_events(limit=20),
    )

    # Update Prometheus gauges while we have fresh data
    kafka_pods_ready_gauge.set(sum(1 for p in kafka_pods if p.ready))
    nodes_schedulable_gauge.set(sum(1 for n in nodes if n.schedulable))
    active_network_partitions_gauge.set(len(partitions))

    return ControllerStatus(
        controller_id=cfg.CONTROLLER_ID,
        k8s_connected=k8s.is_connected,
        kafka_pods=kafka_pods,
        nodes=nodes,
        active_partitions=partitions,
        recent_events=recent_events,
        chaos_enabled=cfg.CHAOS_ENABLED,
    )


# ---------------------------------------------------------------------------
# Pod management
# ---------------------------------------------------------------------------

@router.get(
    "/api/pods",
    response_model=List[PodInfo],
    summary="List Kafka broker pods",
    tags=["pods"],
)
async def list_pods(
    request: Request,
    _user: str = Depends(get_current_user),
) -> List[PodInfo]:
    """Returns all Kafka broker pods matching the configured label selector."""
    k8s: K8sClient = _get_k8s(request)
    cfg = _get_settings(request)
    return await k8s.list_pods(cfg.KAFKA_NAMESPACE, cfg.KAFKA_POD_LABEL_SELECTOR)


@router.post(
    "/api/pods/{name}/restart",
    response_model=ClusterEvent,
    summary="Gracefully restart a Kafka pod",
    tags=["pods"],
)
async def restart_pod(
    request: Request,
    name: str,
    _user: str = Depends(get_current_user),
) -> ClusterEvent:
    """
    Delete the pod with a 10-second grace period.

    Strimzi's StatefulSet controller will recreate the pod automatically.
    The operation is recorded in the audit log.
    """
    k8s: K8sClient = _get_k8s(request)
    store: EventStore = _get_store(request)
    cfg = _get_settings(request)

    event = await k8s.restart_pod(name=name, namespace=cfg.KAFKA_NAMESPACE)
    await store.save_event(event)
    controller_operations_total.labels(operation="pod_restart", status=event.status).inc()
    return event


@router.post(
    "/api/pods/{name}/delete",
    response_model=ClusterEvent,
    summary="Force-delete a Kafka pod (grace_period=0)",
    tags=["pods"],
)
async def delete_pod(
    request: Request,
    name: str,
    _user: str = Depends(get_current_user),
) -> ClusterEvent:
    """
    Force-delete a pod with grace_period=0 to simulate an abrupt crash.

    Use this to test the Kafka broker's recovery path when a leader is
    killed without a clean shutdown.
    """
    k8s: K8sClient = _get_k8s(request)
    store: EventStore = _get_store(request)
    cfg = _get_settings(request)

    event = await k8s.delete_pod(name=name, namespace=cfg.KAFKA_NAMESPACE, grace_period=0)
    await store.save_event(event)
    controller_operations_total.labels(operation="pod_delete", status=event.status).inc()
    return event


# ---------------------------------------------------------------------------
# Node management
# ---------------------------------------------------------------------------

@router.get(
    "/api/nodes",
    response_model=List[NodeInfo],
    summary="List cluster nodes",
    tags=["nodes"],
)
async def list_nodes(
    request: Request,
    _user: str = Depends(get_current_user),
) -> List[NodeInfo]:
    """Returns all Kubernetes nodes with scheduling state and conditions."""
    k8s: K8sClient = _get_k8s(request)
    return await k8s.list_nodes()


@router.post(
    "/api/nodes/{name}/cordon",
    response_model=ClusterEvent,
    summary="Cordon a node (mark unschedulable)",
    tags=["nodes"],
)
async def cordon_node(
    request: Request,
    name: str,
    _user: str = Depends(get_current_user),
) -> ClusterEvent:
    """
    Mark the node as unschedulable.

    Running pods are unaffected; only new pod scheduling is blocked.
    Use this to simulate a node that is about to undergo maintenance.
    """
    k8s: K8sClient = _get_k8s(request)
    store: EventStore = _get_store(request)

    event = await k8s.cordon_node(name)
    await store.save_event(event)
    controller_operations_total.labels(operation="node_cordon", status=event.status).inc()
    return event


@router.post(
    "/api/nodes/{name}/uncordon",
    response_model=ClusterEvent,
    summary="Uncordon a node (restore schedulability)",
    tags=["nodes"],
)
async def uncordon_node(
    request: Request,
    name: str,
    _user: str = Depends(get_current_user),
) -> ClusterEvent:
    """Restore a previously-cordoned node to the scheduling pool."""
    k8s: K8sClient = _get_k8s(request)
    store: EventStore = _get_store(request)

    event = await k8s.uncordon_node(name)
    await store.save_event(event)
    controller_operations_total.labels(operation="node_uncordon", status=event.status).inc()
    return event


@router.post(
    "/api/nodes/{name}/drain",
    response_model=ClusterEvent,
    summary="Drain a node (evict pods + cordon)",
    tags=["nodes"],
)
async def drain_node(
    request: Request,
    name: str,
    ignore_daemonsets: bool = Query(default=True, description="Skip DaemonSet pods"),
    force: bool = Query(default=False, description="Evict unmanaged (static) pods"),
    _user: str = Depends(get_current_user),
) -> ClusterEvent:
    """
    Cordon the node and evict all evictable pods.

    This simulates a node failure scenario where workloads must be rescheduled
    onto other nodes.  DaemonSet pods are skipped by default.
    """
    k8s: K8sClient = _get_k8s(request)
    store: EventStore = _get_store(request)

    event = await k8s.drain_node(
        node_name=name,
        ignore_daemonsets=ignore_daemonsets,
        force=force,
    )
    await store.save_event(event)
    controller_operations_total.labels(operation="node_drain", status=event.status).inc()
    return event


# ---------------------------------------------------------------------------
# Network partitions
# ---------------------------------------------------------------------------

@router.get(
    "/api/network-policies",
    response_model=List,
    summary="List active network partition policies",
    tags=["network"],
)
async def list_network_policies(
    request: Request,
    namespace: Optional[str] = Query(default=None, description="Namespace to query"),
    _user: str = Depends(get_current_user),
) -> List:
    """
    Returns all NetworkPolicy resources in the configured namespace.

    Use this to see which simulated partitions are currently active.
    """
    k8s: K8sClient = _get_k8s(request)
    cfg = _get_settings(request)
    target_ns = namespace or cfg.KAFKA_NAMESPACE
    return await k8s.list_network_policies(target_ns)


@router.post(
    "/api/network-policies",
    response_model=ClusterEvent,
    summary="Create a network partition",
    tags=["network"],
    status_code=status.HTTP_201_CREATED,
)
async def create_network_partition(
    request: Request,
    body: NetworkPartitionRequest,
    _user: str = Depends(get_current_user),
) -> ClusterEvent:
    """
    Create a NetworkPolicy that blocks all traffic to/from the targeted pods.

    This simulates a network partition without killing the pods — they remain
    running but are unreachable.  Clients will experience timeouts rather than
    connection errors, which is a more realistic failure scenario.
    """
    k8s: K8sClient = _get_k8s(request)
    store: EventStore = _get_store(request)

    event = await k8s.create_network_partition(
        target_namespace=body.target_namespace,
        target_pod_selector=body.pod_selector,
        name=body.name,
    )
    await store.save_event(event)
    controller_operations_total.labels(
        operation="network_partition_create", status=event.status
    ).inc()
    active_network_partitions_gauge.inc()
    return event


@router.delete(
    "/api/network-policies/{name}",
    response_model=ClusterEvent,
    summary="Remove a network partition policy",
    tags=["network"],
)
async def delete_network_partition(
    request: Request,
    name: str,
    namespace: Optional[str] = Query(default=None, description="Namespace of the policy"),
    _user: str = Depends(get_current_user),
) -> ClusterEvent:
    """
    Delete a NetworkPolicy to restore network connectivity.

    Pods affected by the partition will begin receiving traffic again once the
    policy is removed.
    """
    k8s: K8sClient = _get_k8s(request)
    store: EventStore = _get_store(request)
    cfg = _get_settings(request)
    target_ns = namespace or cfg.KAFKA_NAMESPACE

    event = await k8s.delete_network_partition(name=name, namespace=target_ns)
    await store.save_event(event)
    controller_operations_total.labels(
        operation="network_partition_delete", status=event.status
    ).inc()
    if event.status == "success":
        active_network_partitions_gauge.dec()
    return event


# ---------------------------------------------------------------------------
# Chaos engine
# ---------------------------------------------------------------------------

@router.post(
    "/api/chaos/run",
    response_model=ClusterEvent,
    summary="Trigger a chaos action",
    tags=["chaos"],
)
async def run_chaos(
    request: Request,
    config: ChaosConfig,
    _user: str = Depends(get_current_user),
) -> ClusterEvent:
    """
    Execute the specified chaos action.

    The ``dry_run`` flag in *config* lets you preview what would happen without
    actually modifying the cluster.  Rate limiting applies regardless of dry_run.
    """
    chaos: ChaosEngine = _get_chaos(request)
    store: EventStore = _get_store(request)

    event = await chaos.run_chaos(config)
    await store.save_event(event)
    controller_operations_total.labels(operation="chaos_random", status=event.status).inc()
    return event


@router.get(
    "/api/chaos/status",
    response_model=Optional[ClusterEvent],
    summary="Get the last chaos event",
    tags=["chaos"],
)
async def chaos_status(
    request: Request,
    _user: str = Depends(get_current_user),
) -> Optional[ClusterEvent]:
    """Returns the most recent ClusterEvent produced by the chaos engine, or null."""
    chaos: ChaosEngine = _get_chaos(request)
    return chaos.last_event


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

@router.get(
    "/api/events",
    response_model=List[ClusterEvent],
    summary="Paginated event history",
    tags=["events"],
)
async def get_events(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum events to return"),
    event_type: Optional[str] = Query(default=None, description="Filter by event type"),
    _user: str = Depends(get_current_user),
) -> List[ClusterEvent]:
    """
    Returns the audit log (most recent first).

    Use *event_type* to filter by a specific operation category
    (e.g. ``pod_restart``, ``chaos_random``).
    """
    store: EventStore = _get_store(request)
    return await store.get_events(limit=limit, event_type=event_type)


# ---------------------------------------------------------------------------
# WebSocket — real-time status stream
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None, description="JWT token"),
) -> None:
    """
    WebSocket connection that streams cluster status every 5 seconds.

    Authentication: pass the JWT as a query parameter ``?token=<jwt>``.

    Clients receive JSON-serialised ControllerStatus messages.
    The connection is closed by the server if the token is invalid or missing.
    """
    # Validate the token before accepting the connection
    if not token:
        await websocket.close(code=1008, reason="Missing token")
        return

    from jose import JWTError, jwt as jose_jwt
    from app.config import settings as app_settings

    try:
        payload = jose_jwt.decode(
            token,
            app_settings.AUTH_SECRET_KEY,
            algorithms=["HS256"],
        )
        if payload.get("sub") is None:
            raise JWTError("no sub claim")
    except JWTError:
        await websocket.close(code=1008, reason="Invalid token")
        return

    await websocket.accept()
    logger.info("WebSocket: client connected")

    k8s: K8sClient = websocket.app.state.k8s_client
    store: EventStore = websocket.app.state.event_store
    cfg = websocket.app.state.settings

    try:
        while True:
            # Gather fresh cluster state
            kafka_pods, nodes, partitions, recent_events = await asyncio.gather(
                k8s.list_pods(cfg.KAFKA_NAMESPACE, cfg.KAFKA_POD_LABEL_SELECTOR),
                k8s.list_nodes(),
                k8s.list_network_policies(cfg.KAFKA_NAMESPACE),
                store.get_events(limit=20),
            )

            status_msg = ControllerStatus(
                controller_id=cfg.CONTROLLER_ID,
                k8s_connected=k8s.is_connected,
                kafka_pods=kafka_pods,
                nodes=nodes,
                active_partitions=partitions,
                recent_events=recent_events,
                chaos_enabled=cfg.CHAOS_ENABLED,
            )

            await websocket.send_text(status_msg.model_dump_json())
            await asyncio.sleep(5)

    except WebSocketDisconnect:
        logger.info("WebSocket: client disconnected")
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
        await websocket.close()
