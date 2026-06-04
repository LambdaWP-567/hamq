"""
Chaos engineering engine for the HAMq Controller.

The ChaosEngine injects random failures into the Kubernetes cluster to
validate the HA properties of the message queue system.

Supported actions:
- random_pod_delete: picks a random running pod in the target namespace and deletes it
- node_drain:        picks a random non-control-plane node and drains it
- network_partition: isolates a random pod by applying a blocking NetworkPolicy

Safety mechanisms:
- CHAOS_MIN_INTERVAL_S: enforces a minimum time between consecutive chaos events
- dry_run mode: logs what would happen without modifying the cluster
- enabled flag: hard-disable switch

Usage:
    engine = ChaosEngine(k8s_client=k8s, settings=settings)
    event = await engine.run_chaos(ChaosConfig(action="random_pod_delete", target_namespace="kafka"))
"""

from __future__ import annotations

import logging
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import Settings, settings as default_settings
from app.k8s_client import K8sClient
from app.models import ChaosConfig, ClusterEvent

logger = logging.getLogger(__name__)


def _now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _new_event_id() -> str:
    return str(uuid.uuid4())


class ChaosEngine:
    """
    Injects random failures based on a ChaosConfig.

    An internal timestamp gate (CHAOS_MIN_INTERVAL_S) prevents the engine from
    running chaos events too close together, protecting the cluster from a
    cascade of self-inflicted failures.
    """

    def __init__(
        self,
        k8s_client: K8sClient,
        settings_: Optional[Settings] = None,
    ) -> None:
        """
        Parameters
        ----------
        k8s_client:
            Initialised K8sClient instance.
        settings_:
            Application settings.  If None, the module-level singleton is used.
        """
        self._k8s = k8s_client
        self._settings = settings_ or default_settings
        # Epoch-time of the last chaos event; 0 means no event has run yet
        self._last_chaos_time: float = 0.0
        self._last_event: Optional[ClusterEvent] = None

    @property
    def last_event(self) -> Optional[ClusterEvent]:
        """The most recent ClusterEvent produced by this engine."""
        return self._last_event

    def _check_interval(self) -> bool:
        """
        Return True if enough time has elapsed since the last chaos event.

        Prevents rapidly cascading failures that could permanently destabilise
        the cluster under test.
        """
        elapsed = time.monotonic() - self._last_chaos_time
        min_interval = self._settings.CHAOS_MIN_INTERVAL_S
        if elapsed < min_interval:
            logger.warning(
                "ChaosEngine: rate-limited — only %.1fs since last event (min=%ds)",
                elapsed,
                min_interval,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run_chaos(self, config: ChaosConfig) -> ClusterEvent:
        """
        Execute a chaos action described by *config*.

        Parameters
        ----------
        config:
            Specifies which action to run and whether it is a dry run.

        Returns
        -------
        ClusterEvent
            Audit record for the chaos operation.
        """
        # Hard-disable gate — checked both here and in the API layer
        if not config.enabled or not self._settings.CHAOS_ENABLED:
            event = ClusterEvent(
                event_id=_new_event_id(),
                timestamp=_now(),
                event_type="chaos_random",
                target="N/A",
                namespace=config.target_namespace,
                status="failed",
                details="Chaos is disabled (enabled=False or CHAOS_ENABLED=False)",
            )
            self._last_event = event
            return event

        # Rate-limit gate
        if not self._check_interval():
            event = ClusterEvent(
                event_id=_new_event_id(),
                timestamp=_now(),
                event_type="chaos_random",
                target="N/A",
                namespace=config.target_namespace,
                status="failed",
                details=(
                    f"Rate-limited: minimum interval of {self._settings.CHAOS_MIN_INTERVAL_S}s "
                    "has not elapsed since the last chaos event"
                ),
            )
            self._last_event = event
            return event

        # Dispatch to the appropriate action handler
        action = config.action
        if action == "random_pod_delete":
            event = await self.random_pod_delete(
                namespace=config.target_namespace,
                dry_run=config.dry_run,
            )
        elif action == "node_drain":
            event = await self._random_node_drain(dry_run=config.dry_run)
        elif action == "network_partition":
            event = await self.random_network_partition(
                namespace=config.target_namespace,
                duration_s=0,  # manual cleanup via DELETE /api/network-policies
                dry_run=config.dry_run,
            )
        else:
            event = ClusterEvent(
                event_id=_new_event_id(),
                timestamp=_now(),
                event_type="chaos_random",
                target="N/A",
                namespace=config.target_namespace,
                status="failed",
                details=f"Unknown chaos action: {action}",
            )

        # Update rate-limit timer on any non-rate-limited attempt
        self._last_chaos_time = time.monotonic()
        self._last_event = event
        return event

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def random_pod_delete(
        self,
        namespace: str,
        dry_run: bool = False,
    ) -> ClusterEvent:
        """
        Pick a random Running pod in *namespace* and delete it.

        In dry-run mode the pod is selected but not deleted.

        Parameters
        ----------
        namespace:
            Kubernetes namespace to target.
        dry_run:
            If True, log the selected pod but skip the delete call.

        Returns
        -------
        ClusterEvent
            Audit record.
        """
        # Fetch pods without label filter — chaos should be broadly applicable
        pods = await self._k8s.list_pods(namespace=namespace, label_selector="")
        running_pods = [p for p in pods if p.status == "Running"]

        if not running_pods:
            return ClusterEvent(
                event_id=_new_event_id(),
                timestamp=_now(),
                event_type="chaos_random",
                target="N/A",
                namespace=namespace,
                status="failed",
                details=f"No running pods found in namespace '{namespace}'",
            )

        # Pick a random victim
        victim = random.choice(running_pods)
        logger.info(
            "ChaosEngine: random_pod_delete selected %s/%s (dry_run=%s)",
            namespace,
            victim.name,
            dry_run,
        )

        if dry_run:
            return ClusterEvent(
                event_id=_new_event_id(),
                timestamp=_now(),
                event_type="chaos_random",
                target=victim.name,
                namespace=namespace,
                status="success",
                details=(
                    f"[DRY RUN] Would delete pod {namespace}/{victim.name}. "
                    "No changes made to cluster."
                ),
            )

        # Actually delete the pod
        event = await self._k8s.delete_pod(
            name=victim.name,
            namespace=namespace,
            grace_period=0,
        )
        # Override event_type to chaos_random for audit clarity
        event.event_type = "chaos_random"
        event.details = f"[CHAOS] " + event.details
        return event

    async def random_network_partition(
        self,
        namespace: str,
        duration_s: int = 0,
        dry_run: bool = False,
    ) -> ClusterEvent:
        """
        Apply a network isolation policy to a randomly-selected pod.

        A NetworkPolicy is created that blocks all ingress and egress for the
        chosen pod.  The policy persists until deleted via the API; the
        *duration_s* parameter is reserved for future auto-cleanup logic.

        Parameters
        ----------
        namespace:
            Kubernetes namespace to target.
        duration_s:
            Duration in seconds after which the partition should be removed
            (0 = no auto-removal; operator must delete manually).
        dry_run:
            If True, log the action but do not create the NetworkPolicy.

        Returns
        -------
        ClusterEvent
            Audit record.
        """
        pods = await self._k8s.list_pods(namespace=namespace, label_selector="")
        running_pods = [p for p in pods if p.status == "Running"]

        if not running_pods:
            return ClusterEvent(
                event_id=_new_event_id(),
                timestamp=_now(),
                event_type="chaos_random",
                target="N/A",
                namespace=namespace,
                status="failed",
                details=f"No running pods found in namespace '{namespace}'",
            )

        victim = random.choice(running_pods)
        policy_name = f"chaos-partition-{victim.name}"

        logger.info(
            "ChaosEngine: random_network_partition targeting %s/%s (dry_run=%s)",
            namespace,
            victim.name,
            dry_run,
        )

        if dry_run:
            return ClusterEvent(
                event_id=_new_event_id(),
                timestamp=_now(),
                event_type="chaos_random",
                target=victim.name,
                namespace=namespace,
                status="success",
                details=(
                    f"[DRY RUN] Would create NetworkPolicy '{policy_name}' to isolate "
                    f"pod {namespace}/{victim.name}. No changes made to cluster."
                ),
            )

        # Create a NetworkPolicy that targets the pod by name label
        event = await self._k8s.create_network_partition(
            target_namespace=namespace,
            target_pod_selector={"statefulset.kubernetes.io/pod-name": victim.name},
            name=policy_name,
        )
        event.event_type = "chaos_random"
        event.details = f"[CHAOS] " + event.details
        return event

    async def _random_node_drain(self, dry_run: bool = False) -> ClusterEvent:
        """
        Pick a random worker node and drain it.

        Control-plane / master nodes are excluded to prevent taking down the
        Kubernetes API server during a chaos experiment.

        Parameters
        ----------
        dry_run:
            If True, log the action without modifying the cluster.

        Returns
        -------
        ClusterEvent
            Audit record.
        """
        nodes = await self._k8s.list_nodes()
        # Only target schedulable worker nodes
        worker_nodes = [
            n for n in nodes
            if n.schedulable and "control-plane" not in n.roles and "master" not in n.roles
        ]

        if not worker_nodes:
            return ClusterEvent(
                event_id=_new_event_id(),
                timestamp=_now(),
                event_type="chaos_random",
                target="N/A",
                namespace="",
                status="failed",
                details="No schedulable worker nodes found for drain",
            )

        victim = random.choice(worker_nodes)
        logger.info(
            "ChaosEngine: random_node_drain selected %s (dry_run=%s)",
            victim.name,
            dry_run,
        )

        if dry_run:
            return ClusterEvent(
                event_id=_new_event_id(),
                timestamp=_now(),
                event_type="chaos_random",
                target=victim.name,
                namespace="",
                status="success",
                details=(
                    f"[DRY RUN] Would drain node {victim.name}. "
                    "No changes made to cluster."
                ),
            )

        event = await self._k8s.drain_node(
            node_name=victim.name,
            ignore_daemonsets=True,
            force=False,
        )
        event.event_type = "chaos_random"
        event.details = f"[CHAOS] " + event.details
        return event
