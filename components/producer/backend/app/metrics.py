"""
Prometheus metrics for the HAMq Producer.

All metrics use the ``hamq_producer_`` prefix to avoid collisions with
other services scraped by the same Prometheus instance.

Metrics are module-level singletons; import them directly wherever needed::

    from app.metrics import messages_sent_total
    messages_sent_total.labels(producer_id="p1", topic="hamq").inc()
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

messages_sent_total = Counter(
    name="hamq_producer_messages_sent_total",
    documentation=(
        "Total number of messages successfully delivered to Kafka. "
        "Use rate() in Prometheus to get messages/second."
    ),
    labelnames=["producer_id", "topic"],
)

# ---------------------------------------------------------------------------
# Gauges
# ---------------------------------------------------------------------------

messages_buffered_gauge = Gauge(
    name="hamq_producer_messages_buffered",
    documentation=(
        "Current number of messages waiting in the local SQLite buffer. "
        "A sustained non-zero value indicates Kafka delivery problems."
    ),
    labelnames=["producer_id"],
)

messages_sent_rate = Gauge(
    name="hamq_producer_messages_sent_rate",
    documentation=(
        "Current message send rate in messages per second (exponential moving average). "
        "Updated every second by the producer service."
    ),
    labelnames=["producer_id"],
)

kafka_connection_status = Gauge(
    name="hamq_producer_kafka_connected",
    documentation=(
        "1 when the producer has an active Kafka connection, 0 otherwise. "
        "Alert when this is 0 for more than ~30 seconds."
    ),
    labelnames=["producer_id"],
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

send_latency_seconds = Histogram(
    name="hamq_producer_send_latency_seconds",
    documentation=(
        "End-to-end latency for a single Kafka send (from send() call to broker ack). "
        "Measured only for messages that are actually delivered (not buffered)."
    ),
    # Buckets covering 1 ms → 30 s range; typical p99 should be < 100 ms
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0, 10.0, 30.0],
)
