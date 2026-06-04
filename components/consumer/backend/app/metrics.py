"""
HAMq Consumer — Prometheus Metrics
=====================================
Defines all application-level Prometheus metrics exported via GET /metrics.

Naming convention follows the Prometheus best-practices guide:
  hamq_consumer_<name>_<unit>
"""

from prometheus_client import Counter, Gauge, Histogram

# --------------------------------------------------------------------------- #
#  Counters
# --------------------------------------------------------------------------- #

messages_received_total = Counter(
    "hamq_consumer_messages_received_total",
    "Total number of messages received from Kafka and persisted",
    labelnames=["consumer_id", "producer_id", "topic"],
)
"""
Incremented once per successfully persisted message.
Labels allow Grafana to break down throughput by producer.
"""

messages_checksum_invalid_total = Counter(
    "hamq_consumer_messages_checksum_invalid_total",
    "Number of messages whose payload checksum did not match",
    labelnames=["consumer_id", "producer_id"],
)
"""
Incremented whenever a SHA-256 checksum mismatch is detected.
A non-zero value indicates data corruption or a mismatched producer version.
"""

messages_duplicate_total = Counter(
    "hamq_consumer_messages_duplicate_total",
    "Number of duplicate messages skipped by INSERT OR IGNORE",
    labelnames=["consumer_id", "producer_id"],
)
"""
At-least-once delivery means re-delivery is expected after failures.
This counter distinguishes intentional duplicates from bugs.
"""

kafka_poll_errors_total = Counter(
    "hamq_consumer_kafka_poll_errors_total",
    "Number of errors encountered during Kafka poll",
    labelnames=["consumer_id"],
)
"""Tracks transient Kafka errors and connection interruptions."""

# --------------------------------------------------------------------------- #
#  Gauges
# --------------------------------------------------------------------------- #

consumer_lag_gauge = Gauge(
    "hamq_consumer_lag",
    "Estimated number of unread messages still in the Kafka topic",
    labelnames=["consumer_id", "topic"],
)
"""
Updated after each commit.  A persistently growing lag indicates the consumer
cannot keep up with the produce rate.
"""

kafka_connection_status = Gauge(
    "hamq_consumer_kafka_connected",
    "1 when the Kafka consumer is connected, 0 otherwise",
    labelnames=["consumer_id"],
)
"""Health check gauge — used by alerting rules."""

messages_in_db_gauge = Gauge(
    "hamq_consumer_messages_in_db",
    "Current number of messages stored in SQLite",
    labelnames=["consumer_id"],
)
"""Updated periodically by the background stats task."""

# --------------------------------------------------------------------------- #
#  Histograms
# --------------------------------------------------------------------------- #

processing_latency_seconds = Histogram(
    "hamq_consumer_processing_latency_seconds",
    "Time from message producer timestamp to consumer received_at (end-to-end latency)",
    labelnames=["consumer_id", "producer_id"],
    # Buckets covering 1 ms to 60 s — appropriate for a WAN Kafka deployment.
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)
"""
Measures the wall-clock latency from when the producer generated the message
(payload timestamp field) to when the consumer received and persisted it.
Includes network transit time, Kafka replication time, and processing time.
"""
