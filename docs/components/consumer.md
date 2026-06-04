# Consumer Component

The Consumer subscribes to the `hamq-messages` Kafka topic, tracks sequence numbers per producer, detects gaps, persists received messages, and exposes REST and WebSocket APIs for downstream dashboards and the Arbiter.

---

## Table of Contents

- [Architecture](#architecture)
- [Key Behaviours](#key-behaviours)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Web UI](#web-ui)
- [Metrics](#metrics)
- [Deployment](#deployment)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Consumer Pod (Cluster C)                                            │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Kafka Consumer (confluent-kafka-python)                      │   │
│  │  group.id = hamq-consumer-group                              │   │
│  │  enable.auto.commit = true                                   │   │
│  │  auto.commit.interval.ms = 5000                              │   │
│  │  max.poll.interval.ms = 300000                               │   │
│  └────────────────────────────┬─────────────────────────────────┘   │
│                               │ poll(timeout_ms=1000)                │
│                               ▼                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Message Processor                                            │   │
│  │  1. Parse JSON                                                │   │
│  │  2. Validate payload.checksum (SHA-256)                       │   │
│  │  3. Track sequence per producer_id                           │   │
│  │  4. Detect gaps: expected_seq != received_seq                │   │
│  │  5. Persist to SQLite                                         │   │
│  └────────────────────────────┬─────────────────────────────────┘   │
│                               │                                      │
│  ┌────────────────────────────▼─────────────────────────────────┐   │
│  │  SQLite Store (/data/consumer.db)                             │   │
│  │  table: received_messages                                    │   │
│  │  table: sequence_state (per producer_id last_sequence)       │   │
│  │  table: gaps (producer_id, gap_start, gap_end, detected_at)  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  FastAPI HTTP server (:8001) + WebSocket (:8001/ws/messages)  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  React SPA (:3001)                                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Key Behaviours

### Sequence tracking

For each `producer_id` seen, the Consumer maintains `last_sequence` in a `sequence_state` table. When a message arrives:

1. The received `sequence` is compared with `last_sequence + 1`.
2. If equal: update `last_sequence`; no gap.
3. If greater: a gap of `sequence - last_sequence - 1` messages has been detected. The gap is recorded in the `gaps` table. `last_sequence` is updated to the received value.
4. If less than or equal to `last_sequence`: the message is a **duplicate** or **out-of-order delivery**. The duplicate counter is incremented.

### Gap detection

A gap occurs when `received_sequence > expected_sequence`. Gaps are reported to the Arbiter via the REST API and are visible in the web UI and Prometheus metrics.

Note: gaps may be temporary (messages reordered due to Kafka partition leadership changes) or permanent (lost messages). The Arbiter determines which by cross-referencing with the Producer's sent ledger.

### Checksum validation

Each received message's `payload.data` (base64-decoded) is hashed with SHA-256 and compared to `payload.checksum`. Mismatches increment `hamq_consumer_checksum_failures_total` and are logged at WARNING level. The message is still persisted (the checksum failure is an application-level data corruption indicator, not a Kafka-level issue).

### Offset commit behaviour

Offsets are committed automatically every `auto.commit.interval.ms` (default 5 000 ms). This provides at-least-once delivery semantics: if the consumer pod restarts, messages from the last commit window may be re-processed. The sequence tracker handles duplicates (behaviour 4 above).

For exactly-once semantics, set `enable.auto.commit=false` and commit offsets manually after successful persistence. This can be configured via `consumer.manualCommit: true` in `values.yaml`.

### Consumer group and partition assignment

The consumer group ID is `hamq-consumer-group`. With a single replica, all 12 partitions of `hamq-messages` are assigned to that one consumer. With multiple replicas, Kafka distributes partitions across replicas using the default range or sticky assignor.

---

## Configuration

### Helm values (`components/consumer/helm/values.yaml`)

| Key | Default | Description |
|-----|---------|-------------|
| `kafka.bootstrapServers` | `""` | **Required.** Kafka bootstrap `host:port` |
| `kafka.topic` | `hamq-messages` | Topic to consume from |
| `kafka.caSecretName` | `hamq-kafka-cluster-ca-cert` | Secret containing `ca.crt` |
| `kafka.userSecretName` | `hamq-consumer` | Secret containing `user.crt`, `user.key` |
| `consumer.groupId` | `hamq-consumer-group` | Kafka consumer group ID |
| `consumer.autoCommitIntervalMs` | `5000` | Offset auto-commit interval in ms |
| `consumer.maxPollIntervalMs` | `300000` | Max time between polls before rebalance |
| `consumer.manualCommit` | `false` | Use manual offset commit for stronger durability |
| `consumer.dbPath` | `/data/consumer.db` | SQLite persistence path (should be on PVC) |
| `consumer.retentionRows` | `1000000` | Max rows to retain in `received_messages` |
| `image.repository` | `ghcr.io/lambdawp-567/hamq-consumer` | Container image |
| `image.tag` | `latest` | Image tag |
| `replicaCount` | `1` | Consumer replicas (each gets a subset of partitions) |
| `persistence.enabled` | `true` | Mount a PVC for SQLite |
| `persistence.size` | `5Gi` | PVC size |
| `api.port` | `8001` | FastAPI HTTP port |
| `ui.port` | `3001` | React SPA port |
| `logLevel` | `info` | Python logging level |

### Environment variable mapping

See the [Deployment guide environment variable table](../deployment.md#consumer-cluster-c).

---

## API Endpoints

The Consumer exposes a FastAPI HTTP server on port `8001`.

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status": "ok"}` |
| `GET` | `/ready` | Returns 200 when Kafka is connected and consuming, 503 otherwise |

### Consumer status

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/consumer/stats` | Aggregate statistics |
| `GET` | `/api/v1/consumer/status` | Current run state, partition assignments |
| `GET` | `/api/v1/consumer/sequences` | Per-producer last received sequence numbers |
| `GET` | `/api/v1/consumer/gaps` | List of detected gaps |

#### Stats response schema

```json
{
  "state": "running",
  "total_received": 14987,
  "total_gaps": 2,
  "total_gap_messages": 5,
  "total_duplicates": 1,
  "total_checksum_failures": 0,
  "kafka_connected": true,
  "consumer_group": "hamq-consumer-group",
  "assigned_partitions": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
  "consumer_lag_total": 0,
  "last_received_at": "2026-01-15T12:34:56.789012Z",
  "uptime_seconds": 148.7
}
```

#### Sequences response schema

```json
{
  "sequences": {
    "producer-0": {
      "last_sequence": 14987,
      "first_seen_at": "2026-01-15T12:32:00.000000Z",
      "last_seen_at": "2026-01-15T12:34:56.789012Z"
    }
  }
}
```

#### Gaps response schema

```json
{
  "gaps": [
    {
      "producer_id": "producer-0",
      "gap_start": 1234,
      "gap_end": 1236,
      "size": 3,
      "detected_at": "2026-01-15T12:33:10.000000Z"
    }
  ]
}
```

### Message retrieval

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/messages/{id}` | Retrieve a specific message by ID |
| `GET` | `/api/v1/messages?producer_id=X&limit=100&offset=0` | List received messages (filterable by producer) |

### WebSocket

| Path | Protocol | Description |
|------|----------|-------------|
| `/ws/messages` | WebSocket | Streams each received message as JSON to connected clients |
| `/ws/stats` | WebSocket | Pushes stats updates every second |

---

## Web UI

The React SPA is served on port `3001` and connects to the FastAPI server via WebSocket.

### Dashboard features

- **Live message stream** — real-time feed of incoming messages via WebSocket
- **Stats panel** — total received, total gaps, total duplicates, consumer lag
- **Sequence tracker** — table showing per-producer last sequence, gap count
- **Gap log** — timeline of detected sequence gaps with size and timestamp
- **Throughput chart** — messages received per second over last 5 minutes
- **Partition assignment panel** — which partitions this consumer holds and their lag
- **Checksum failure log** — messages that failed integrity validation

---

## Metrics

The Consumer exposes Prometheus metrics on `/metrics` (port `8001`).

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `hamq_consumer_messages_received_total` | Counter | `producer_id`, `topic` | Total messages received |
| `hamq_consumer_gaps_detected_total` | Counter | `producer_id` | Total sequence gaps detected |
| `hamq_consumer_gap_messages_total` | Counter | `producer_id` | Total missing messages (sum of gap sizes) |
| `hamq_consumer_duplicates_total` | Counter | `producer_id` | Total duplicate messages received |
| `hamq_consumer_checksum_failures_total` | Counter | `producer_id` | Messages with invalid payload checksum |
| `hamq_consumer_lag_messages` | Gauge | `topic`, `partition`, `group` | Consumer group lag per partition |
| `hamq_consumer_kafka_connected` | Gauge | — | 1 if connected, 0 if not |
| `hamq_consumer_processing_latency_seconds` | Histogram | `producer_id` | Time from message timestamp to consumer receipt |

### Alert rules (recommended)

```yaml
- alert: HAMqConsumerGapDetected
  expr: increase(hamq_consumer_gaps_detected_total[5m]) > 0
  labels:
    severity: warning
  annotations:
    summary: "Consumer detected sequence gaps — potential message loss"

- alert: HAMqConsumerLagHigh
  expr: hamq_consumer_lag_messages > 1000
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Consumer group lag is growing"

- alert: HAMqConsumerKafkaDisconnected
  expr: hamq_consumer_kafka_connected == 0
  for: 30s
  labels:
    severity: critical
  annotations:
    summary: "Consumer cannot reach Kafka"
```

---

## Deployment

```bash
# Install
helm install hamq-consumer components/consumer/helm \
  --namespace hamq \
  --set kafka.bootstrapServers="kafka.hamq.example.com:9094" \
  --set kafka.caSecretName=hamq-kafka-cluster-ca-cert \
  --set kafka.userSecretName=hamq-consumer

# Scale to consume more partitions in parallel
helm upgrade hamq-consumer components/consumer/helm \
  --namespace hamq \
  --set replicaCount=3 \
  --reuse-values
```

> **Note on scaling:** The `hamq-messages` topic has 12 partitions. With `replicaCount: 3`, each replica processes 4 partitions. Each replica maintains its own SQLite database. The Arbiter must be configured to query all consumer replicas (or an aggregator endpoint) to build a complete received-sequence picture.
