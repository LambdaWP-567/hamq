# Producer Component

The Producer generates messages at a configurable frequency and publishes them to the `hamq-messages` Kafka topic. Its primary design goal is **zero data loss**: every generated message is durably buffered locally before Kafka delivery is attempted.

---

## Table of Contents

- [Architecture](#architecture)
- [Resilience Mechanisms](#resilience-mechanisms)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Web UI](#web-ui)
- [Metrics](#metrics)
- [Deployment](#deployment)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Producer Pod (Cluster B)                                            │
│                                                                      │
│  ┌──────────────┐   write    ┌──────────────────────────────────┐   │
│  │  Generator   │──────────▶│  SQLite Buffer (WAL mode)         │   │
│  │  coroutine   │           │  db: /data/buffer.db              │   │
│  │  freq_hz     │           │  table: pending_messages          │   │
│  └──────────────┘           │  columns:                         │   │
│                              │    id TEXT PRIMARY KEY            │   │
│                              │    sequence INTEGER               │   │
│                              │    payload TEXT                   │   │
│                              │    created_at TEXT                │   │
│                              │    attempts INTEGER DEFAULT 0     │   │
│                              └──────────────┬───────────────────┘   │
│                                             │  drain loop            │
│                              ┌──────────────▼───────────────────┐   │
│                              │  Kafka Publisher                  │   │
│                              │  confluent-kafka-python           │   │
│                              │  acks=all                         │   │
│                              │  retries=MAX_INT                  │   │
│                              │  delivery.timeout.ms=120000       │   │
│                              │  enable.idempotence=true          │   │
│                              └──────────────┬───────────────────┘   │
│                                             │  on_delivery callback  │
│                              ┌──────────────▼───────────────────┐   │
│                              │  Delete from SQLite               │   │
│                              │  (only on successful delivery)    │   │
│                              └───────────────────────────────────┘   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  DNS Resolver (background, every 60s)                          │  │
│  │  Re-resolves bootstrap hostname; reinitialises Kafka client   │  │
│  │  if resolved IP changes                                        │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  FastAPI HTTP server (:8000)  +  React SPA (:3000)             │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Resilience Mechanisms

### 1. Local SQLite write-ahead buffer

Every message is written to a local SQLite database (WAL + synchronous=FULL mode) **before** being sent to Kafka. This means:

- A producer pod restart after generating but before successfully delivering a message will **not** lose that message — it will be retried on restart.
- The buffer is stored on a Kubernetes `PersistentVolumeClaim` mounted at `/data/buffer.db`.
- Messages are only deleted from the buffer when the Kafka delivery callback reports `err=None` (successful delivery and replication to all ISR brokers, because `acks=all`).

Buffer schema:

```sql
CREATE TABLE pending_messages (
    id          TEXT PRIMARY KEY,
    sequence    INTEGER NOT NULL,
    payload     TEXT NOT NULL,        -- full JSON message body
    created_at  TEXT NOT NULL,        -- ISO 8601 UTC
    attempts    INTEGER DEFAULT 0     -- incremented on each publish attempt
);
```

### 2. Async retry loop

A background asyncio task (`drain_loop`) continuously reads unbuffered messages from SQLite and calls `producer.produce()`:

```
drain_loop:
  while True:
    rows = SELECT * FROM pending_messages ORDER BY sequence LIMIT 100
    for row in rows:
      producer.produce(topic, key=row.id, value=row.payload, callback=on_delivery)
    producer.flush(timeout=5)
    await asyncio.sleep(RETRY_INTERVAL_SECONDS)
```

When Kafka is unavailable, `produce()` will queue messages in the client's internal queue. When the queue is full, `produce()` raises `BufferError`, which is caught and causes the drain loop to back off. The SQLite buffer provides the outer durable queue.

### 3. DNS-based discovery and automatic reconnection

The bootstrap server address is configured as a **hostname**, never a raw IP. A background coroutine re-resolves the hostname every `PRODUCER_DNS_REFRESH_SECONDS` (default: 60) seconds.

If the resolved IP changes (e.g., after a LoadBalancer failover or IP rotation), the Kafka client is gracefully closed and reinitialised with the new address. Active in-flight messages are preserved in the SQLite buffer during reinitialisation.

This mechanism handles:
- Cloud LoadBalancer IP changes after cluster recreation.
- DNS-based failover to a secondary Kafka cluster (disaster recovery).

### 4. Kafka producer hardening

The Kafka client is configured for maximum durability:

| Config | Value | Reason |
|--------|-------|--------|
| `acks` | `all` | Wait for all ISR replicas to confirm write |
| `enable.idempotence` | `true` | Exactly-once semantics at the producer level |
| `retries` | `2147483647` | Retry indefinitely on transient errors |
| `retry.backoff.ms` | `1000` | 1 s back-off between retries |
| `delivery.timeout.ms` | `120000` | 2 min total delivery timeout per message |
| `linger.ms` | `5` | Micro-batch for throughput (5 ms) |
| `batch.size` | `65536` | 64 KiB batch size |

### 5. Back-pressure and buffer limits

When `pending_messages` count exceeds `PRODUCER_BUFFER_MAX_MESSAGES` (default: 1 000 000), the generator coroutine **pauses** (does not drop messages). It resumes automatically when the drain loop reduces the buffer below the threshold.

An alert fires when `hamq_producer_buffer_size > 10 000` — this indicates Kafka has been unreachable for a significant period.

---

## Configuration

### Helm values (`components/producer/helm/values.yaml`)

| Key | Default | Description |
|-----|---------|-------------|
| `kafka.bootstrapServers` | `""` | **Required.** Kafka bootstrap `host:port`. Use the external LB address |
| `kafka.topic` | `hamq-messages` | Kafka topic to publish to |
| `kafka.caSecretName` | `hamq-kafka-cluster-ca-cert` | Secret name containing `ca.crt` |
| `kafka.userSecretName` | `hamq-producer` | Secret name containing `user.crt`, `user.key` |
| `producer.frequencyHz` | `10` | Initial publish frequency in msg/s |
| `producer.bufferMaxMessages` | `1000000` | Max SQLite buffer rows before back-pressure |
| `producer.bufferDbPath` | `/data/buffer.db` | SQLite database path |
| `producer.retryIntervalSeconds` | `5` | Drain loop sleep interval |
| `producer.dnsRefreshSeconds` | `60` | Bootstrap hostname re-resolution interval |
| `image.repository` | `ghcr.io/lambdawp-567/hamq-producer` | Container image |
| `image.tag` | `latest` | Container image tag |
| `replicaCount` | `1` | Number of producer replicas |
| `persistence.enabled` | `true` | Mount a PVC for the SQLite buffer |
| `persistence.size` | `1Gi` | PVC size |
| `resources.requests.memory` | `256Mi` | Memory request |
| `resources.limits.memory` | `512Mi` | Memory limit |
| `api.port` | `8000` | FastAPI HTTP port |
| `ui.port` | `3000` | React SPA port |
| `logLevel` | `info` | Python logging level |

### Environment variable override

All Helm values map to environment variables injected into the container. See the [Deployment guide environment variable table](../deployment.md#producer-cluster-b) for the full mapping.

---

## API Endpoints

The Producer exposes a FastAPI HTTP server on port `8000` (configurable).

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status": "ok"}` when the server is running |
| `GET` | `/ready` | Returns 200 when connected to Kafka, 503 otherwise |

### Producer control

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/producer/start` | `{"frequency_hz": float}` | Start generating and publishing messages |
| `POST` | `/api/v1/producer/stop` | — | Stop the generator; drain loop continues until buffer is empty |
| `PATCH` | `/api/v1/producer/frequency` | `{"frequency_hz": float}` | Update publish frequency without stopping |

### Status and statistics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/producer/stats` | Full statistics snapshot |
| `GET` | `/api/v1/producer/status` | Current run state and buffer size |
| `GET` | `/api/v1/producer/buffer` | Buffer contents (paginated, up to 1000 rows) |

#### Stats response schema

```json
{
  "state": "running",
  "frequency_hz": 100.0,
  "total_generated": 15023,
  "total_delivered": 15020,
  "total_failed": 0,
  "buffer_size": 3,
  "buffer_max": 1000000,
  "kafka_connected": true,
  "bootstrap_servers": "kafka.hamq.example.com:9094",
  "uptime_seconds": 150.4,
  "last_sequence": 15023,
  "last_delivery_at": "2026-01-15T12:34:56.789012Z"
}
```

### Message inspection

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/messages/{id}` | Retrieve a message by ID from the local sent log |
| `GET` | `/api/v1/messages?limit=100&offset=0` | List recently sent messages |

### WebSocket

| Path | Protocol | Description |
|------|----------|-------------|
| `/ws/stats` | WebSocket | Pushes a stats update every second to connected clients |

---

## Web UI

The React SPA is served on port `3000` and connects to the FastAPI server on port `8000` via the WebSocket endpoint.

### Dashboard features

- **Live stats panel** — messages/s, total sent, buffer size, Kafka connectivity indicator
- **Frequency control** — slider to adjust `frequency_hz` in real time (1–1000 msg/s)
- **Start / Stop button** — single-click control
- **Buffer chart** — time-series chart of SQLite buffer depth
- **Throughput chart** — messages per second over the last 5 minutes
- **Recent messages table** — last 100 messages with ID, sequence, timestamp, delivery status
- **Connection indicator** — shows whether Kafka is reachable; DNS resolution status

---

## Metrics

The Producer exposes Prometheus metrics on `/metrics` (port `8000`).

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `hamq_producer_messages_generated_total` | Counter | `producer_id` | Total messages generated |
| `hamq_producer_messages_delivered_total` | Counter | `producer_id`, `topic` | Messages successfully delivered to Kafka |
| `hamq_producer_messages_failed_total` | Counter | `producer_id`, `error` | Delivery failures (after retries exhausted) |
| `hamq_producer_buffer_size` | Gauge | `producer_id` | Current SQLite buffer row count |
| `hamq_producer_frequency_hz` | Gauge | `producer_id` | Current publish frequency |
| `hamq_producer_kafka_connected` | Gauge | `producer_id` | 1 if connected, 0 if not |
| `hamq_producer_delivery_latency_seconds` | Histogram | `producer_id` | End-to-end delivery latency (generate → Kafka ack) |
| `hamq_producer_dns_resolutions_total` | Counter | `producer_id`, `result` | DNS resolution outcomes (`changed`, `unchanged`, `error`) |

### Alert rules (recommended)

```yaml
- alert: HAMqProducerBufferHigh
  expr: hamq_producer_buffer_size > 10000
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Producer buffer growing — Kafka may be unreachable"

- alert: HAMqProducerKafkaDisconnected
  expr: hamq_producer_kafka_connected == 0
  for: 30s
  labels:
    severity: critical
  annotations:
    summary: "Producer cannot reach Kafka"
```

---

## Deployment

```bash
# Install
helm install hamq-producer components/producer/helm \
  --namespace hamq \
  --set kafka.bootstrapServers="kafka.hamq.example.com:9094" \
  --set kafka.caSecretName=hamq-kafka-cluster-ca-cert \
  --set kafka.userSecretName=hamq-producer

# Upgrade with new image tag
helm upgrade hamq-producer components/producer/helm \
  --namespace hamq \
  --set image.tag=v1.2.0 \
  --reuse-values

# Scale to multiple replicas (each replica has its own SQLite buffer PVC)
helm upgrade hamq-producer components/producer/helm \
  --namespace hamq \
  --set replicaCount=3 \
  --reuse-values
```

> **Note on multiple replicas:** Each producer replica generates independent message streams with a unique `producer_id` equal to its pod name. The Arbiter tracks loss per `producer_id`, so scaling to N replicas increases total throughput to `N × frequency_hz`.
