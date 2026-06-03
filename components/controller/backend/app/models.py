"""
Pydantic data models for the HAMq Controller.

These models are shared between the API layer, the Kubernetes client wrapper,
the chaos engine, and the SQLite event store.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Kubernetes resource info models
# ---------------------------------------------------------------------------

class PodInfo(BaseModel):
    """
    Snapshot of a single Kubernetes pod's state.

    Used to represent Kafka broker pods and can be extended for other
    workloads that the controller may need to inspect.
    """

    name: str = Field(..., description="Pod name (e.g. hamq-kafka-kafka-0)")
    namespace: str = Field(..., description="Kubernetes namespace")
    status: str = Field(..., description="Pod phase: Running, Pending, Failed, etc.")
    node: str = Field(
        default="",
        description="Name of the node this pod is scheduled on"
    )
    ready: bool = Field(
        default=False,
        description="True when all containers in the pod are ready"
    )
    restart_count: int = Field(
        default=0,
        description="Total container restart count across all containers in the pod"
    )


class NodeInfo(BaseModel):
    """
    Snapshot of a Kubernetes node's scheduling state and conditions.
    """

    name: str = Field(..., description="Node name")
    status: str = Field(
        default="Unknown",
        description="Derived status string, e.g. 'Ready' or 'NotReady'"
    )
    schedulable: bool = Field(
        default=True,
        description="False when the node is cordoned (spec.unschedulable=true)"
    )
    roles: List[str] = Field(
        default_factory=list,
        description="List of node roles extracted from node.kubernetes.io/role labels"
    )
    conditions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Raw condition objects from the node status"
    )


class NetworkPolicyInfo(BaseModel):
    """
    Summary of a Kubernetes NetworkPolicy resource.

    The controller creates 'isolation' policies that block all ingress/egress
    for the targeted pods; this model captures enough detail to display and
    manage those policies.
    """

    name: str = Field(..., description="NetworkPolicy resource name")
    namespace: str = Field(..., description="Kubernetes namespace")
    pod_selector: Dict[str, Any] = Field(
        default_factory=dict,
        description="The .spec.podSelector field (matchLabels / matchExpressions)"
    )
    ingress_rules: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of ingress rule objects from the NetworkPolicy spec"
    )
    egress_rules: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of egress rule objects from the NetworkPolicy spec"
    )


# ---------------------------------------------------------------------------
# Event / audit models
# ---------------------------------------------------------------------------

class ClusterEvent(BaseModel):
    """
    Audit record for every operation performed by the controller.

    All events are persisted to SQLite so operators can review what happened
    during chaos experiments.
    """

    event_id: str = Field(..., description="UUID4 event identifier")
    timestamp: str = Field(
        ...,
        description="ISO-8601 UTC timestamp of when the event was initiated"
    )
    event_type: Literal[
        "pod_restart",
        "pod_delete",
        "node_cordon",
        "node_drain",
        "node_uncordon",
        "network_partition_create",
        "network_partition_delete",
        "chaos_random",
    ] = Field(..., description="Category of cluster operation")
    target: str = Field(
        ...,
        description="Name of the resource affected (pod name, node name, policy name)"
    )
    namespace: str = Field(
        default="",
        description="Kubernetes namespace of the affected resource"
    )
    status: Literal["pending", "success", "failed"] = Field(
        default="pending",
        description="Outcome of the operation"
    )
    details: str = Field(
        default="",
        description="Human-readable description or error message"
    )


# ---------------------------------------------------------------------------
# Chaos engine models
# ---------------------------------------------------------------------------

class ChaosConfig(BaseModel):
    """
    Configuration for a single chaos run.

    Clients POST this to /api/chaos/run to trigger a specific failure scenario.
    The dry_run flag lets operators preview what *would* happen without actually
    modifying cluster state.
    """

    enabled: bool = Field(
        default=True,
        description="Must be True for the chaos engine to execute the action"
    )
    action: Literal[
        "random_pod_delete",
        "node_drain",
        "network_partition",
    ] = Field(
        default="random_pod_delete",
        description="Which failure scenario to inject"
    )
    target_namespace: str = Field(
        default="kafka",
        description="Kubernetes namespace to target for chaos operations"
    )
    dry_run: bool = Field(
        default=False,
        description="If True, log what would happen but do NOT modify the cluster"
    )


# ---------------------------------------------------------------------------
# Status aggregate model
# ---------------------------------------------------------------------------

class ControllerStatus(BaseModel):
    """
    Full status snapshot returned by GET /api/status and streamed over WebSocket.

    Combines Kubernetes state with recent audit events so the dashboard can
    render a complete picture in a single request.
    """

    controller_id: str = Field(..., description="Identifier of this controller instance")
    k8s_connected: bool = Field(
        ...,
        description="True when the Kubernetes API is reachable"
    )
    kafka_pods: List[PodInfo] = Field(
        default_factory=list,
        description="Current state of all Kafka broker pods"
    )
    nodes: List[NodeInfo] = Field(
        default_factory=list,
        description="Current state of all cluster nodes"
    )
    active_partitions: List[NetworkPolicyInfo] = Field(
        default_factory=list,
        description="NetworkPolicies created by the controller that are still active"
    )
    recent_events: List[ClusterEvent] = Field(
        default_factory=list,
        description="Last 20 audit events from the event store"
    )
    chaos_enabled: bool = Field(
        default=True,
        description="Whether the chaos engine is globally enabled"
    )


# ---------------------------------------------------------------------------
# Generic action request
# ---------------------------------------------------------------------------

class ActionRequest(BaseModel):
    """
    Generic action request used for ad-hoc cluster operations.

    Most operations have dedicated endpoints with path parameters; this model
    is used for actions that need additional options (e.g. grace period).
    """

    action: str = Field(..., description="Action identifier string")
    target: str = Field(..., description="Resource name to act on")
    namespace: str = Field(
        default="",
        description="Namespace of the target resource (empty = use configured default)"
    )
    options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Action-specific options (e.g. {'grace_period': 0})"
    )


# ---------------------------------------------------------------------------
# Auth models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    """Credentials submitted to POST /api/auth/login."""

    username: str = Field(..., description="API username")
    password: str = Field(
        ...,
        description="API password (plain text, transmitted over TLS)"
    )


class TokenResponse(BaseModel):
    """JWT token response returned after a successful login."""

    access_token: str = Field(..., description="Signed JWT bearer token")
    token_type: str = Field(default="bearer", description="Always 'bearer'")


# ---------------------------------------------------------------------------
# Network partition creation request
# ---------------------------------------------------------------------------

class NetworkPartitionRequest(BaseModel):
    """
    Body for POST /api/network-policies.

    Creates a Kubernetes NetworkPolicy that blocks all traffic to/from pods
    matching the given selector — simulating a network partition.
    """

    name: str = Field(
        ...,
        description="Name for the NetworkPolicy resource (must be unique in namespace)"
    )
    target_namespace: str = Field(
        ...,
        description="Namespace where the NetworkPolicy will be created"
    )
    pod_selector: Dict[str, str] = Field(
        default_factory=dict,
        description="matchLabels selector for pods to isolate (empty = all pods)"
    )
