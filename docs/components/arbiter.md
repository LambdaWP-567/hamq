# Arbiter Component

The Arbiter is the authoritative message-loss and delivery-quality analyser. It periodically polls the Producer and Consumer APIs, compares their sent and received sequence sets, and computes message loss rate, duplicate rate, and latency statistics.

---

## Table of Contents

- [Architecture](#architecture)
- [Analysis Model](#analysis-model)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Web UI](#web-ui)
- [Metrics](#metrics)
- [Deployment](#deployment)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Arbiter Pod (Cluster D)                                             │
│                                                                      │
│  ┌──────────────────────┐     ┌──────────────────────────────────┐  │
│  │  Poll Scheduler      │────▶│  Producer API Client             │  │
│  │  (every N seconds)   │     │  GET /api/v1/producer/stats      │  │
│  │                      │     │  GET /api/v1/producer/sequences  │  │
│  │                      │     └──────────────────────────────────┘  │
│  │                      │     ┌──────────────────────────────────┐  │
│  │                      │────▶│  Consumer API Client             │  │
│  │                      │     │  GET /api/v1/consumer/stats      │  │
│  │                      │     │  GET /api/v1/consumer/sequences  │  │
│  │                      │     │  GET /api/v1/consumer/gaps       │  │
│  └──────────────────────┘     └──────────────────────────────────┘  │
│             │                                                         │
│             ▼                                                         │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Analysis Engine                                              │   │
│  │  - Compute sent_set, received_set per producer_id            │   │
│  │  - lost_set = sent_set - received_set                        │   │
│  │  - duplicate_set = received_set - sent_set (out-of-window)   │   │
│  │  - Compute latency percentiles from timestamps               │   │
│  │  - Build gap histogram                                        │   │
│  └──────────────────────┬─────────────────────────────────────┘    │
│                          │                                            │
│  ┌───────────────────────▼──────────────────────────────────────┐   │
│  │  Results Store (in-memory + SQLite for historical reports)    │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  FastAPI HTTP server (:8002)  +  Prometheus metrics          │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  React SPA (:3002)                                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Analysis Model

### Inputs

The Arbiter collects two data sets per analysis cycle:

1. **Producer sent set** — from `GET /api/v1/producer/sequences`: the set of sequence numbers that the producer has confirmed delivered to Kafka (i.e., SQLite-deleted).

2. **Consumer received set** — from `GET /api/v1/consumer/sequences` and `GET /api/v1/consumer/gaps`: the set of sequence numbers the consumer has received.

### Computations

For each `producer_id`:

```
sent_set      = {sequences delivered by producer}
received_set  = {sequences received by consumer}

lost_set      = sent_set - received_set        # in sent but not received
extra_set     = received_set - sent_set        # in received but not in sent window
                                                # (can happen with at-least-once)

loss_rate     = |lost_set| / |sent_set|         if |sent_set| > 0 else 0.0
duplicate_rate = |extra_set| / |sent_set|       if |sent_set| > 0 else 0.0
```

### Sequence window

The Arbiter does not hold unbounded sequence sets. Instead it maintains a sliding window of the last `ARBITER_WINDOW_MESSAGES` (default: 100 000) sequence numbers per producer. Sequences outside the window are considered "expired" and are no longer tracked for loss analysis.

### Latency computation

The Arbiter computes end-to-end latency as:

```
latency = consumer_received_at - message.timestamp
```

Where `consumer_received_at` is the time the consumer's poll loop received the message and `message.timestamp` is the UTC timestamp embedded in the message at generation time. The Arbiter computes p50, p90, p99, and p99.9 latency percentiles over the analysis window.

> **Note:** This latency includes: message generation time, Kafka publish time, replication time, and consumer poll time. It does **not** include Arbiter poll interval latency.

---

## Configuration

### Helm values (`components/arbiter/helm/values.yaml`)

| Key | Default | Description |
|-----|---------|-------------|
| `arbiter.producerApiUrl` | `""` | **Required.** Producer API base URL, e.g. `http://producer.hamq.example.com:8000` |
| `arbiter.consumerApiUrl` | `""` | **Required.** Consumer API base URL, e.g. `http://consumer.hamq.example.com:8001` |
| `arbiter.pollIntervalSeconds` | `10` | How often to poll Producer and Consumer APIs |
| `arbiter.windowMessages` | `100000` | Size of the sliding analysis window per producer |
| `arbiter.httpTimeoutSeconds` | `5` | Timeout for outbound HTTP calls to Producer/Consumer |
| `arbiter.retainHistoryDays` | `7` | Days of historical reports to retain in SQLite |
| `image.repository` | `ghcr.io/lambdawp-567/hamq-arbiter` | Container image |
| `image.tag` | `latest` | Image tag |
| `api.port` | `8002` | FastAPI HTTP port |
| `ui.port` | `3002` | React SPA port |
| `logLevel` | `info` | Python logging level |

---

## API Endpoints

The Arbiter exposes a FastAPI HTTP server on port `8002`.

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status": "ok"}` |

### Reports

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/report` | Latest computed report |
| `GET` | `/api/v1/report/history?limit=100&offset=0` | Historical reports |
| `GET` | `/api/v1/report/summary` | High-level summary for dashboard widget |

#### Report response schema

```json
{
  "timestamp": "2026-01-15T12:35:00.000000Z",
  "window_start_sequence": 14900,
  "window_end_sequence": 15000,
  "total_sent": 100,
  "total_received": 98,
  "total_lost": 2,
  "total_duplicates": 0,
  "loss_rate": 0.02,
  "duplicate_rate": 0.0,
  "latency_p50_ms": 12.4,
  "latency_p90_ms": 18.7,
  "latency_p99_ms": 34.2,
  "latency_p999_ms": 89.1,
  "lost_sequences": [14923, 14957],
  "gaps_detected": 2,
  "producers": {
    "producer-0": {
      "total_sent": 100,
      "total_received": 98,
      "loss_rate": 0.02,
      "last_sequence_sent": 15000,
      "last_sequence_received": 15000
    }
  }
}
```

### Per-producer analysis

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/producers` | List all known producers |
| `GET` | `/api/v1/producers/{producer_id}/report` | Per-producer loss report |
| `GET` | `/api/v1/producers/{producer_id}/gaps` | Gaps attributed to this producer |

### WebSocket

| Path | Protocol | Description |
|------|----------|-------------|
| `/ws/report` | WebSocket | Pushes latest report after each analysis cycle |

---

## Web UI

The React SPA is served on port `3002`.

### Dashboard features

- **Loss rate gauge** — large, colour-coded gauge (green < 0.01%, amber < 0.1%, red ≥ 0.1%)
- **Throughput comparison chart** — side-by-side sent vs. received messages/s
- **Latency percentile chart** — p50/p90/p99 over time
- **Gap timeline** — when gaps were detected, attributed to which producer
- **Lost sequence table** — individual sequence numbers confirmed lost
- **Duplicate log** — duplicate deliveries
- **Producer status table** — per-producer loss rate, last sequence, connectivity
- **History panel** — click any historical report to inspect in detail

---

## Metrics

The Arbiter exposes Prometheus metrics on `/metrics`.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `hamq_arbiter_loss_rate` | Gauge | `producer_id` | Current message loss rate (0.0–1.0) |
| `hamq_arbiter_duplicate_rate` | Gauge | `producer_id` | Current duplicate rate |
| `hamq_arbiter_messages_lost_total` | Counter | `producer_id` | Cumulative messages confirmed lost |
| `hamq_arbiter_latency_p50_ms` | Gauge | `producer_id` | p50 end-to-end latency in ms |
| `hamq_arbiter_latency_p99_ms` | Gauge | `producer_id` | p99 end-to-end latency in ms |
| `hamq_arbiter_analysis_cycles_total` | Counter | — | Total analysis cycles completed |
| `hamq_arbiter_producer_api_errors_total` | Counter | `error` | Errors polling Producer API |
| `hamq_arbiter_consumer_api_errors_total` | Counter | `error` | Errors polling Consumer API |

### Alert rules (recommended)

```yaml
- alert: HAMqMessageLoss
  expr: hamq_arbiter_loss_rate > 0.0001
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "HAMq message loss detected: {{ $value | humanizePercentage }}"

- alert: HAMqHighLatency
  expr: hamq_arbiter_latency_p99_ms > 500
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "HAMq p99 latency above 500ms: {{ $value }}ms"
```

---

## Deployment

```bash
helm install hamq-arbiter components/arbiter/helm \
  --namespace hamq \
  --set arbiter.producerApiUrl="http://producer.hamq.example.com:8000" \
  --set arbiter.consumerApiUrl="http://consumer.hamq.example.com:8001"
```
