"""
Kubernetes API wrapper for the HAMq Controller.

This module provides an async-friendly abstraction over the synchronous
Kubernetes Python client.  All blocking API calls are executed in a
thread-pool executor to avoid stalling the FastAPI event loop.

Design principles:
- Idempotent where possible (e.g. cordon an already-cordoned node is a no-op)
- Returns ClusterEvent objects so callers can persist results to the audit log
- is_connected property lets the status endpoint report Kubernetes health
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from app.config import settings
from app.models import ClusterEvent, NodeInfo, PodInfo, NetworkPolicyInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper: generate a UTC ISO-8601 timestamp string
# ---------------------------------------------------------------------------

def _now() -> str:
    """Return the current UTC time as an ISO-8601 string (millisecond precision)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _new_event_id() -> str:
    """Generate a UUID4 event identifier."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# K8sClient
# ---------------------------------------------------------------------------

class K8sClient:
    """
    Wraps the Kubernetes Python client with in-cluster or kubeconfig auth.

    All I/O operations are idempotent where possible.  Blocking synchronous
    Kubernetes API calls are executed via asyncio.get_event_loop().run_in_executor
    so they do not block the uvicorn/asyncio event loop.
    """

    def __init__(self, settings_: Any = None) -> None:
        """
        Initialise the Kubernetes client.

        Parameters
        ----------
        settings_:
            Application settings.  If None the module-level ``settings``
            singleton is used.  Injected for unit-testing.
        """
        cfg = settings_ or settings
        self._settings = cfg
        self._connected = False

        try:
            if cfg.K8S_IN_CLUSTER:
                # Load the service account token mounted inside the pod
                k8s_config.load_incluster_config()
                logger.info("Kubernetes: loaded in-cluster config")
            else:
                # Fall back to a kubeconfig file (local development)
                kubeconfig = cfg.K8S_KUBECONFIG_PATH or None
                k8s_config.load_kube_config(config_file=kubeconfig)
                logger.info("Kubernetes: loaded kubeconfig from %s", kubeconfig or "~/.kube/config")

            # Instantiate the client handles we need
            self._core_v1 = client.CoreV1Api()
            self._networking_v1 = client.NetworkingV1Api()
            self._apps_v1 = client.AppsV1Api()
            self._connected = True
        except Exception as exc:
            logger.error("Kubernetes initialisation failed: %s", exc)
            self._core_v1 = None
            self._networking_v1 = None
            self._apps_v1 = None

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True when the Kubernetes client was successfully initialised."""
        return self._connected

    async def _run_sync(self, func, *args, **kwargs):
        """
        Execute a synchronous callable in the default thread-pool executor.

        This prevents the blocking Kubernetes HTTP calls from stalling the
        asyncio event loop.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    # ------------------------------------------------------------------
    # Pod operations
    # ------------------------------------------------------------------

    async def list_pods(
        self,
        namespace: str,
        label_selector: str = "",
    ) -> List[PodInfo]:
        """
        List pods in *namespace* optionally filtered by *label_selector*.

        Parameters
        ----------
        namespace:
            Kubernetes namespace to query.
        label_selector:
            Kubernetes label selector string (e.g. ``strimzi.io/name=hamq-kafka-kafka``).

        Returns
        -------
        list[PodInfo]
            Sorted list of pod snapshots (by pod name).
        """
        if not self._connected or self._core_v1 is None:
            return []

        try:
            kwargs: Dict[str, Any] = {"namespace": namespace}
            if label_selector:
                kwargs["label_selector"] = label_selector

            pod_list = await self._run_sync(
                self._core_v1.list_namespaced_pod, **kwargs
            )
        except ApiException as exc:
            logger.error("list_pods failed: %s", exc)
            return []

        result: List[PodInfo] = []
        for pod in pod_list.items:
            # Derive a human-readable ready state from container statuses
            ready = False
            restart_count = 0
            if pod.status and pod.status.container_statuses:
                ready = all(cs.ready for cs in pod.status.container_statuses)
                restart_count = sum(
                    cs.restart_count for cs in pod.status.container_statuses
                )

            result.append(
                PodInfo(
                    name=pod.metadata.name,
                    namespace=pod.metadata.namespace,
                    status=pod.status.phase if pod.status and pod.status.phase else "Unknown",
                    node=pod.spec.node_name or "",
                    ready=ready,
                    restart_count=restart_count,
                )
            )

        return sorted(result, key=lambda p: p.name)

    async def delete_pod(
        self,
        name: str,
        namespace: str,
        grace_period: int = 0,
    ) -> ClusterEvent:
        """
        Delete a pod by name.

        Kubernetes will immediately evict the pod.  If it belongs to a
        StatefulSet or Deployment the controller will recreate it.

        Parameters
        ----------
        name:
            Pod name.
        namespace:
            Namespace of the pod.
        grace_period:
            Grace period in seconds (0 = force-delete immediately).

        Returns
        -------
        ClusterEvent
            Audit record with the outcome of the delete operation.
        """
        event = ClusterEvent(
            event_id=_new_event_id(),
            timestamp=_now(),
            event_type="pod_delete",
            target=name,
            namespace=namespace,
            status="pending",
            details=f"Deleting pod {namespace}/{name} (grace_period={grace_period}s)",
        )

        if not self._connected or self._core_v1 is None:
            event.status = "failed"
            event.details = "Kubernetes client not connected"
            return event

        try:
            body = client.V1DeleteOptions(grace_period_seconds=grace_period)
            await self._run_sync(
                self._core_v1.delete_namespaced_pod,
                name=name,
                namespace=namespace,
                body=body,
            )
            event.status = "success"
            event.details = f"Pod {namespace}/{name} deleted (grace={grace_period}s)"
            logger.info("Deleted pod %s/%s", namespace, name)
        except ApiException as exc:
            event.status = "failed"
            event.details = f"ApiException {exc.status}: {exc.reason}"
            logger.error("delete_pod %s/%s failed: %s", namespace, name, exc)

        return event

    async def restart_pod(self, name: str, namespace: str) -> ClusterEvent:
        """
        Restart a pod by deleting it with a short grace period.

        For StatefulSet-managed pods (like Strimzi Kafka brokers) the
        StatefulSet controller will automatically create a replacement pod.

        Parameters
        ----------
        name:
            Pod name.
        namespace:
            Namespace of the pod.

        Returns
        -------
        ClusterEvent
            Audit record with outcome.
        """
        event = ClusterEvent(
            event_id=_new_event_id(),
            timestamp=_now(),
            event_type="pod_restart",
            target=name,
            namespace=namespace,
            status="pending",
            details=f"Restarting pod {namespace}/{name} (graceful delete)",
        )

        if not self._connected or self._core_v1 is None:
            event.status = "failed"
            event.details = "Kubernetes client not connected"
            return event

        try:
            # Use a 10-second grace period for graceful restart (allows
            # in-flight Kafka requests to complete)
            body = client.V1DeleteOptions(grace_period_seconds=10)
            await self._run_sync(
                self._core_v1.delete_namespaced_pod,
                name=name,
                namespace=namespace,
                body=body,
            )
            event.status = "success"
            event.details = (
                f"Pod {namespace}/{name} deleted (grace=10s); "
                "StatefulSet will recreate it"
            )
            logger.info("Restarted pod %s/%s", namespace, name)
        except ApiException as exc:
            event.status = "failed"
            event.details = f"ApiException {exc.status}: {exc.reason}"
            logger.error("restart_pod %s/%s failed: %s", namespace, name, exc)

        return event

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    async def list_nodes(self) -> List[NodeInfo]:
        """
        Return a snapshot of all nodes in the cluster.

        Returns
        -------
        list[NodeInfo]
            Sorted list of node snapshots (by node name).
        """
        if not self._connected or self._core_v1 is None:
            return []

        try:
            node_list = await self._run_sync(self._core_v1.list_node)
        except ApiException as exc:
            logger.error("list_nodes failed: %s", exc)
            return []

        result: List[NodeInfo] = []
        for node in node_list.items:
            # Extract role labels (node-role.kubernetes.io/<role>)
            labels = node.metadata.labels or {}
            roles = [
                k.split("/")[-1]
                for k in labels
                if k.startswith("node-role.kubernetes.io/")
            ]
            if not roles:
                roles = ["worker"]

            # Derive a simple status string from the Ready condition
            node_status = "Unknown"
            conditions = []
            if node.status and node.status.conditions:
                for cond in node.status.conditions:
                    conditions.append(
                        {
                            "type": cond.type,
                            "status": cond.status,
                            "message": cond.message or "",
                        }
                    )
                    if cond.type == "Ready":
                        node_status = "Ready" if cond.status == "True" else "NotReady"

            schedulable = not bool(node.spec and node.spec.unschedulable)

            result.append(
                NodeInfo(
                    name=node.metadata.name,
                    status=node_status,
                    schedulable=schedulable,
                    roles=roles,
                    conditions=conditions,
                )
            )

        return sorted(result, key=lambda n: n.name)

    async def cordon_node(self, node_name: str) -> ClusterEvent:
        """
        Cordon a node — mark it unschedulable so no new pods land on it.

        This is idempotent: cordoning an already-cordoned node returns success.

        Parameters
        ----------
        node_name:
            Name of the node to cordon.

        Returns
        -------
        ClusterEvent
            Audit record with outcome.
        """
        event = ClusterEvent(
            event_id=_new_event_id(),
            timestamp=_now(),
            event_type="node_cordon",
            target=node_name,
            namespace="",
            status="pending",
            details=f"Cordoning node {node_name}",
        )

        if not self._connected or self._core_v1 is None:
            event.status = "failed"
            event.details = "Kubernetes client not connected"
            return event

        try:
            body = {"spec": {"unschedulable": True}}
            await self._run_sync(
                self._core_v1.patch_node,
                name=node_name,
                body=body,
            )
            event.status = "success"
            event.details = f"Node {node_name} cordoned (unschedulable=true)"
            logger.info("Cordoned node %s", node_name)
        except ApiException as exc:
            event.status = "failed"
            event.details = f"ApiException {exc.status}: {exc.reason}"
            logger.error("cordon_node %s failed: %s", node_name, exc)

        return event

    async def uncordon_node(self, node_name: str) -> ClusterEvent:
        """
        Uncordon a node — restore schedulability after maintenance.

        This is idempotent: uncordoning an already-schedulable node succeeds.

        Parameters
        ----------
        node_name:
            Name of the node to uncordon.

        Returns
        -------
        ClusterEvent
            Audit record with outcome.
        """
        event = ClusterEvent(
            event_id=_new_event_id(),
            timestamp=_now(),
            event_type="node_uncordon",
            target=node_name,
            namespace="",
            status="pending",
            details=f"Uncordoning node {node_name}",
        )

        if not self._connected or self._core_v1 is None:
            event.status = "failed"
            event.details = "Kubernetes client not connected"
            return event

        try:
            body = {"spec": {"unschedulable": False}}
            await self._run_sync(
                self._core_v1.patch_node,
                name=node_name,
                body=body,
            )
            event.status = "success"
            event.details = f"Node {node_name} uncordoned (unschedulable=false)"
            logger.info("Uncordoned node %s", node_name)
        except ApiException as exc:
            event.status = "failed"
            event.details = f"ApiException {exc.status}: {exc.reason}"
            logger.error("uncordon_node %s failed: %s", node_name, exc)

        return event

    async def drain_node(
        self,
        node_name: str,
        ignore_daemonsets: bool = True,
        force: bool = False,
    ) -> ClusterEvent:
        """
        Drain a node by evicting all evictable pods.

        The drain operation:
        1. Cordons the node (marks unschedulable) so no new pods land.
        2. Evicts all non-DaemonSet pods (with ignore_daemonsets=True).

        Parameters
        ----------
        node_name:
            Name of the node to drain.
        ignore_daemonsets:
            Skip DaemonSet-managed pods (they cannot be evicted).
        force:
            Evict pods even if they are not managed by a ReplicationController,
            Job, DaemonSet or StatefulSet.

        Returns
        -------
        ClusterEvent
            Audit record with outcome.
        """
        event = ClusterEvent(
            event_id=_new_event_id(),
            timestamp=_now(),
            event_type="node_drain",
            target=node_name,
            namespace="",
            status="pending",
            details=f"Draining node {node_name} (ignore_daemonsets={ignore_daemonsets}, force={force})",
        )

        if not self._connected or self._core_v1 is None:
            event.status = "failed"
            event.details = "Kubernetes client not connected"
            return event

        try:
            # Step 1: cordon the node first
            cordon_body = {"spec": {"unschedulable": True}}
            await self._run_sync(
                self._core_v1.patch_node,
                name=node_name,
                body=cordon_body,
            )
            logger.info("drain_node: cordoned %s", node_name)

            # Step 2: list all pods on this node
            pod_list = await self._run_sync(
                self._core_v1.list_pod_for_all_namespaces,
                field_selector=f"spec.nodeName={node_name}",
            )

            evicted = 0
            skipped = 0
            for pod in pod_list.items:
                pod_name = pod.metadata.name
                pod_ns = pod.metadata.namespace
                owner_refs = pod.metadata.owner_references or []

                # Determine if we should skip this pod
                is_daemonset = any(r.kind == "DaemonSet" for r in owner_refs)
                is_static = not owner_refs  # static pods have no owner

                if ignore_daemonsets and is_daemonset:
                    logger.debug("drain_node: skipping DaemonSet pod %s/%s", pod_ns, pod_name)
                    skipped += 1
                    continue

                if is_static and not force:
                    logger.debug("drain_node: skipping static pod %s/%s (no owner)", pod_ns, pod_name)
                    skipped += 1
                    continue

                # Evict the pod using the Eviction sub-resource
                try:
                    eviction = client.V1Eviction(
                        metadata=client.V1ObjectMeta(
                            name=pod_name,
                            namespace=pod_ns,
                        )
                    )
                    await self._run_sync(
                        self._core_v1.create_namespaced_pod_eviction,
                        name=pod_name,
                        namespace=pod_ns,
                        body=eviction,
                    )
                    evicted += 1
                    logger.info("drain_node: evicted pod %s/%s", pod_ns, pod_name)
                except ApiException as evict_exc:
                    # Pod may already be gone; log but continue draining
                    logger.warning(
                        "drain_node: could not evict %s/%s: %s",
                        pod_ns,
                        pod_name,
                        evict_exc,
                    )

            event.status = "success"
            event.details = (
                f"Node {node_name} drained: {evicted} pods evicted, "
                f"{skipped} skipped (DaemonSet/static)"
            )
            logger.info("Drained node %s (%d evicted)", node_name, evicted)

        except ApiException as exc:
            event.status = "failed"
            event.details = f"ApiException {exc.status}: {exc.reason}"
            logger.error("drain_node %s failed: %s", node_name, exc)

        return event

    # ------------------------------------------------------------------
    # NetworkPolicy operations
    # ------------------------------------------------------------------

    async def list_network_policies(self, namespace: str) -> List[NetworkPolicyInfo]:
        """
        List NetworkPolicy resources in *namespace*.

        Returns
        -------
        list[NetworkPolicyInfo]
            List of network policy summaries.
        """
        if not self._connected or self._networking_v1 is None:
            return []

        try:
            np_list = await self._run_sync(
                self._networking_v1.list_namespaced_network_policy,
                namespace=namespace,
            )
        except ApiException as exc:
            logger.error("list_network_policies failed: %s", exc)
            return []

        result: List[NetworkPolicyInfo] = []
        for np in np_list.items:
            spec = np.spec or {}

            # Convert the pod selector to a plain dict
            pod_sel: Dict[str, Any] = {}
            if hasattr(spec, "pod_selector") and spec.pod_selector:
                sel = spec.pod_selector
                if sel.match_labels:
                    pod_sel["matchLabels"] = dict(sel.match_labels)
                if sel.match_expressions:
                    pod_sel["matchExpressions"] = [
                        {
                            "key": expr.key,
                            "operator": expr.operator,
                            "values": list(expr.values or []),
                        }
                        for expr in sel.match_expressions
                    ]

            result.append(
                NetworkPolicyInfo(
                    name=np.metadata.name,
                    namespace=np.metadata.namespace,
                    pod_selector=pod_sel,
                    ingress_rules=[],  # simplified: full rules not needed for dashboard
                    egress_rules=[],
                )
            )

        return result

    async def create_network_partition(
        self,
        target_namespace: str,
        target_pod_selector: Dict[str, str],
        name: str,
    ) -> ClusterEvent:
        """
        Create a NetworkPolicy that blocks all ingress and egress traffic for
        the pods matched by *target_pod_selector*.

        This simulates a network partition for those pods.  To restore
        connectivity delete the policy via delete_network_partition().

        Parameters
        ----------
        target_namespace:
            Namespace where the NetworkPolicy will be created.
        target_pod_selector:
            ``matchLabels`` dict identifying the pods to isolate.
        name:
            Name for the new NetworkPolicy resource.

        Returns
        -------
        ClusterEvent
            Audit record with outcome.
        """
        event = ClusterEvent(
            event_id=_new_event_id(),
            timestamp=_now(),
            event_type="network_partition_create",
            target=name,
            namespace=target_namespace,
            status="pending",
            details=(
                f"Creating network partition policy '{name}' in {target_namespace} "
                f"targeting selector {target_pod_selector}"
            ),
        )

        if not self._connected or self._networking_v1 is None:
            event.status = "failed"
            event.details = "Kubernetes client not connected"
            return event

        try:
            # Build a NetworkPolicy with empty ingress + egress lists.
            # An empty policyTypes list with ingress/egress specified blocks all traffic.
            policy_body = client.V1NetworkPolicy(
                metadata=client.V1ObjectMeta(
                    name=name,
                    namespace=target_namespace,
                    labels={
                        # Mark this policy as controller-managed for easy cleanup
                        "app.kubernetes.io/managed-by": "hamq-controller",
                        "hamq.io/partition": "true",
                    },
                ),
                spec=client.V1NetworkPolicySpec(
                    # Pod selector — empty dict matches ALL pods in the namespace
                    pod_selector=client.V1LabelSelector(
                        match_labels=target_pod_selector or {}
                    ),
                    # Explicitly declare that this policy applies to both directions
                    policy_types=["Ingress", "Egress"],
                    # No ingress rules = deny all ingress
                    ingress=[],
                    # No egress rules = deny all egress
                    egress=[],
                ),
            )

            await self._run_sync(
                self._networking_v1.create_namespaced_network_policy,
                namespace=target_namespace,
                body=policy_body,
            )
            event.status = "success"
            event.details = (
                f"Network partition policy '{name}' created in {target_namespace}: "
                "all ingress/egress blocked for matching pods"
            )
            logger.info("Created network partition policy %s/%s", target_namespace, name)

        except ApiException as exc:
            event.status = "failed"
            event.details = f"ApiException {exc.status}: {exc.reason}"
            logger.error(
                "create_network_partition %s/%s failed: %s",
                target_namespace,
                name,
                exc,
            )

        return event

    async def delete_network_partition(
        self,
        name: str,
        namespace: str,
    ) -> ClusterEvent:
        """
        Delete a previously-created NetworkPolicy to restore connectivity.

        Parameters
        ----------
        name:
            Name of the NetworkPolicy resource.
        namespace:
            Namespace of the NetworkPolicy.

        Returns
        -------
        ClusterEvent
            Audit record with outcome.
        """
        event = ClusterEvent(
            event_id=_new_event_id(),
            timestamp=_now(),
            event_type="network_partition_delete",
            target=name,
            namespace=namespace,
            status="pending",
            details=f"Deleting network partition policy {namespace}/{name}",
        )

        if not self._connected or self._networking_v1 is None:
            event.status = "failed"
            event.details = "Kubernetes client not connected"
            return event

        try:
            await self._run_sync(
                self._networking_v1.delete_namespaced_network_policy,
                name=name,
                namespace=namespace,
            )
            event.status = "success"
            event.details = f"Network partition policy {namespace}/{name} deleted"
            logger.info("Deleted network partition policy %s/%s", namespace, name)

        except ApiException as exc:
            if exc.status == 404:
                # Already gone — treat as success (idempotent)
                event.status = "success"
                event.details = f"Policy {namespace}/{name} not found (already deleted)"
            else:
                event.status = "failed"
                event.details = f"ApiException {exc.status}: {exc.reason}"
                logger.error(
                    "delete_network_partition %s/%s failed: %s",
                    namespace,
                    name,
                    exc,
                )

        return event
