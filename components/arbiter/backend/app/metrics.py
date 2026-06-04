"""
Prometheus metrics for the HAMq Arbiter.

Metrics are collected via the prometheus-client library and exposed on
GET /metrics in the standard Prometheus text exposition format.

Metric naming follows the prometheus naming conventions:
  hamq_arbiter_<name>_{total,seconds,ratio,...}

Usage
-----
Import the metric objects directly; no initialisation needed:

    from app.metrics import reconcile_runs_total, loss_rate_gauge
    reconcile_runs_total.inc()
    loss_rate_gauge.labels(producer_id="producer-1").set(0.05)
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Counters — monotonically increasing totals
# ---------------------------------------------------------------------------

reconcile_runs_total = Counter(
    name="hamq_arbiter_reconcile_runs_total",
    documentation=(
        "Total number of reconciliation passes completed (both scheduled and manual)."
    ),
)

missing_messages_total = Counter(
    name="hamq_arbiter_missing_messages_total",
    documentation=(
        "Cumulative number of messages detected as missing (present at producer, "
        "absent at consumer) across all reconcile passes.  Labelled by producer_id "
        "so you can distinguish between producers in a multi-producer setup."
    ),
    labelnames=["producer_id"],
)

reconcile_errors_total = Counter(
    name="hamq_arbiter_reconcile_errors_total",
    documentation=(
        "Total number of reconcile passes that raised an unhandled exception "
        "(e.g., Producer/Consumer API unreachable)."
    ),
)

alert_events_total = Counter(
    name="hamq_arbiter_alert_events_total",
    documentation=(
        "Total number of alert events fired because loss_rate exceeded the "
        "configured ALERT_LOSS_RATE_THRESHOLD.  Labelled by producer_id."
    ),
    labelnames=["producer_id"],
)

# ---------------------------------------------------------------------------
# Gauges — instantaneous values that can go up or down
# ---------------------------------------------------------------------------

loss_rate_gauge = Gauge(
    name="hamq_arbiter_loss_rate",
    documentation=(
        "Current message loss rate for a producer (missing / sent in the most "
        "recent reconcile window).  Ranges from 0.0 (no loss) to 1.0 (all lost). "
        "Labelled by producer_id."
    ),
    labelnames=["producer_id"],
)

sent_gauge = Gauge(
    name="hamq_arbiter_sent_count",
    documentation=(
        "Number of messages the producer reported sending in the most recent "
        "reconcile window.  Labelled by producer_id."
    ),
    labelnames=["producer_id"],
)

received_gauge = Gauge(
    name="hamq_arbiter_received_count",
    documentation=(
        "Number of producer-sent messages confirmed received by the consumer in "
        "the most recent reconcile window.  Labelled by producer_id."
    ),
    labelnames=["producer_id"],
)

arbiter_running_gauge = Gauge(
    name="hamq_arbiter_running",
    documentation=(
        "1 if the background reconcile loop is currently active, 0 if stopped."
    ),
)

# ---------------------------------------------------------------------------
# Histograms — distribution of values over time
# ---------------------------------------------------------------------------

reconcile_duration_seconds = Histogram(
    name="hamq_arbiter_reconcile_duration_seconds",
    documentation=(
        "Wall-clock time in seconds for a complete reconcile pass "
        "(from first Producer API call to final audit writes)."
    ),
    # Buckets cover sub-second network calls up to slow 30-second timeouts
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
