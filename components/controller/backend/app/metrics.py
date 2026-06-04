"""
Prometheus metrics for the HAMq Controller.

Exposes operational metrics about the cluster state and controller actions.
The /metrics endpoint is served by prometheus-client's ASGI middleware.

Metrics:
- controller_operations_total: Counter of all operations with operation + status labels
- kafka_pods_ready_gauge: Gauge of currently-ready Kafka broker pods
- nodes_schedulable_gauge: Gauge of schedulable (not cordoned) cluster nodes
- active_network_partitions_gauge: Gauge of currently-active isolation policies
"""

from prometheus_client import Counter, Gauge

# ---------------------------------------------------------------------------
# Counter: every controller operation increments this with its outcome
# ---------------------------------------------------------------------------
# Labels:
#   operation - the operation type (pod_restart, node_drain, etc.)
#   status    - 'success' or 'failed'
controller_operations_total = Counter(
    name="controller_operations_total",
    documentation=(
        "Total number of controller operations performed, "
        "labelled by operation type and outcome."
    ),
    labelnames=["operation", "status"],
)

# ---------------------------------------------------------------------------
# Gauge: current number of ready Kafka broker pods
# ---------------------------------------------------------------------------
# A pod is 'ready' when all its containers pass their readiness probes.
# This metric helps alert on broker availability degradation during chaos tests.
kafka_pods_ready_gauge = Gauge(
    name="kafka_pods_ready",
    documentation="Number of Kafka broker pods currently in the Ready state.",
)

# ---------------------------------------------------------------------------
# Gauge: current number of schedulable (non-cordoned) cluster nodes
# ---------------------------------------------------------------------------
# Drops when nodes are cordoned; recovering after a drain experiment is
# visible in dashboards via this metric.
nodes_schedulable_gauge = Gauge(
    name="nodes_schedulable",
    documentation="Number of cluster nodes that are schedulable (not cordoned).",
)

# ---------------------------------------------------------------------------
# Gauge: current number of active network partition policies
# ---------------------------------------------------------------------------
# A non-zero value indicates an ongoing simulated network partition.
active_network_partitions_gauge = Gauge(
    name="active_network_partitions",
    documentation=(
        "Number of controller-created NetworkPolicy resources currently active "
        "(i.e. simulated network partitions in progress)."
    ),
)
