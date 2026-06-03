# HAMq Architecture

## Table of Contents

- [System Overview](#system-overview)
- [Component Descriptions](#component-descriptions)
- [Message Format](#message-format)
- [Network Topology](#network-topology)
- [TLS / mTLS Setup](#tls--mtls-setup)
- [High-Availability Guarantees](#high-availability-guarantees)
- [Producer Resilience](#producer-resilience)
- [Message Flow](#message-flow)

---

## System Overview

HAMq (Highly Available Message Queue) is a Kubernetes-native, production-grade message broker system built on Apache Kafka (via Strimzi Operator in KRaft mode). The system is designed for zero-message-loss operation under partial infrastructure failures, rolling restarts, and deliberate chaos-engineering scenarios.

```
╔══════════════════════════════════════════════════════════════════════╗
║                      Cluster A  —  Kafka Cluster                    ║
║  ┌────────────────────────────────────────────────────────────────┐  ║
║  │         Strimzi Kafka  ·  KRaft  ·  3 Nodes (dual-role)       │  ║
║  │    TLS listeners  ·  RF=3  ·  min.insync.replicas=2           │  ║
║  │    acks=all  ·  cert-manager PKI  ·  Prometheus metrics       │  ║
║  │                                                                │  ║
║  │   [Broker/Controller 0]  [Broker/Controller 1]  [B/C 2]       │  ║
║  └────────────────────────────────────────────────────────────────┘  ║
╚══════════════════════════════════════════════════════════════════════╝
          ▲  Write (TLS/mTLS)                ▼  Read (TLS/mTLS)
          │                                  │
┌─────────────────────┐            ┌─────────────────────┐
│   Producer          │            │   Consumer           │
│   Cluster B         │            │   Cluster C          │
│  ─────────────────  │            │  ─────────────────   │
│  Python FastAPI     │            │  Python FastAPI      │
│  React UI           │            │  React UI            │
│  SQLite Buffer      │            │  REST + WebSocket    │
│  Retry Loop         │            │  Sequence Tracker    │
│  DNS Discovery      │            │  Gap Detection       │
└─────────────────────┘            └─────────────────────┘
          │                                  │
          └──────────────┬───────────────────┘
                         │  sequence + delivery data
                ┌────────────────────┐
                │   Arbiter          │
                │   Cluster D        │
                │  ─────────────────  │
                │  Python FastAPI    │
                │  React UI          │
                │  Gap Analysis      │
                │  Loss Reporting    │
                └────────────────────┘
                         │  operational signals
                ┌────────────────────┐
                │   Controller       │
                │   Cluster E        │
                │  ─────────────────  │
                │  Python FastAPI    │
                │  React UI          │
                │  K8s API access    │
                │  Chaos Engineering │
                │  Lifecycle Mgmt    │
                └────────────────────┘
```

---

## Component Descriptions

### Kafka Cluster (Cluster A)

The Kafka cluster is the central message bus. It runs inside its own dedicated Kubernetes cluster to isolate blast radius from application workloads.

| Property | Value |
|---|---|
| Operator | Strimzi Kafka Operator 0.43.0 |
| Kafka version | 3.8.0 |
| Mode | KRaft (no ZooKeeper) |
| Node count | 3 (dual-role: controller + broker) |
| Replication factor | 3 |
| min.insync.replicas | 2 |
| Authentication | mTLS (TLS client certificates) |
| TLS PKI | cert-manager ClusterIssuer |
| Metrics | JMX Prometheus Exporter |

All three nodes act as both Raft controllers and Kafka brokers. In KRaft mode the metadata quorum (controller ring) is embedded inside the broker process, eliminating the ZooKeeper dependency and reducing operational surface area.

### Producer (Cluster B)

The Producer component generates messages and publishes them to the `hamq-messages` Kafka topic. Its primary design goal is **zero data loss**: if the Kafka cluster is temporarily unavailable the producer buffers messages locally in SQLite and retires asynchronously.

Key behaviours:
- Configurable publish frequency: 1 – 1 000 msg/s
- Local SQLite write-ahead buffer (WAL mode) before Kafka confirmation
- Async background retry loop drains buffer once connectivity resumes
- DNS-based bootstrap server discovery (Kubernetes Service DNS, never hardcoded IPs)
- mTLS client certificate (issued by cert-manager) for Kafka authentication
- FastAPI HTTP API for control and status
- React SPA web UI for live monitoring

### Consumer (Cluster C)

The Consumer subscribes to `hamq-messages`, tracks sequence numbers, and persists received messages. It exposes a REST API and WebSocket endpoint for downstream dashboards and for the Arbiter.

Key behaviours:
- Consumer group: `hamq-consumer-group`
- Sequence number tracking per `producer_id`
- Gap detection: identifies missing sequence numbers
- Configurable auto-commit interval
- mTLS client certificate for Kafka authentication
- FastAPI HTTP + WebSocket API
- React SPA web UI

### Arbiter (Cluster D)

The Arbiter compares the producer's send ledger with the consumer's receive ledger to compute authoritative message-loss and out-of-order delivery statistics.

Key behaviours:
- Polls Producer API (sent counts / sequence ranges) and Consumer API (received sequences)
- Computes: loss rate, duplicate rate, latency percentiles, gap histogram
- Emits Prometheus metrics and structured JSON reports
- FastAPI HTTP API
- React SPA web UI with live dashboards

### Controller (Cluster E)

The Controller orchestrates lifecycle operations and chaos experiments across all clusters using the Kubernetes API.

Key behaviours:
- Kubernetes API access (RBAC-limited ServiceAccount)
- Controlled rolling restarts, broker pod deletions
- Network partition simulation (NetworkPolicy injection)
- Scenario scripting: pre-defined chaos sequences with configurable blast parameters
- Stores scenario results; integrates with Arbiter for loss attribution
- FastAPI HTTP API
- React SPA web UI

---

## Message Format

Every message published to `hamq-messages` is a JSON object conforming to the following schema:

```json
{
  "id":           "<uuid-v4>",
  "sequence":     42,
  "producer_id":  "producer-pod-0",
  "timestamp":    "2026-01-15T12:34:56.789012Z",
  "frequency_hz": 10.0,
  "payload": {
    "data":     "<base64-encoded-string>",
    "checksum": "<sha256-hex-digest-of-data>"
  }
}
```

### Field Reference

| Field | Type | Description |
|---|---|---|
| `id` | UUID v4 string | Globally unique message identifier, generated at publish time |
| `sequence` | int64 | Monotonically increasing per-producer sequence number starting at 1; used by Consumer and Arbiter for gap detection |
| `producer_id` | string | Kubernetes Pod name of the originating producer instance, e.g. `producer-0` |
| `timestamp` | ISO 8601 (UTC) | UTC wall-clock time at the moment the message was generated |
| `frequency_hz` | float64 | Configured publish frequency at the time this message was produced |
| `payload.data` | string | Application payload (base64-encoded arbitrary bytes) |
| `payload.checksum` | sha256 hex | SHA-256 digest of the raw (pre-base64) payload bytes; allows integrity verification at the consumer |

The Consumer validates `payload.checksum` against `payload.data` on every received message and increments a `hamq_consumer_checksum_failures_total` Prometheus counter on mismatch.

---

## Network Topology

HAMq uses a **hybrid multi-cluster** topology: the Kafka cluster lives in a dedicated cluster (Cluster A) to isolate I/O-intensive broker workloads, while application components (Producer, Consumer, Arbiter, Controller) each live in separate lightweight clusters. This matches common enterprise patterns where messaging infrastructure is shared across multiple application teams.

```
Internet / Corporate WAN
         │
         │  (all traffic TLS encrypted)
         │
┌────────▼────────────────────────────────────────────────────────────────┐
│  Cluster A  —  Kafka  (cloud or bare-metal, dedicated node pool)        │
│                                                                         │
│  External LoadBalancer Service  →  port 9094  (external TLS listener)  │
│  Internal ClusterIP Service     →  port 9093  (in-cluster TLS)         │
│  Prometheus ServiceMonitor      →  port 9404  (metrics scrape)         │
└─────────────────────────────────────────────────────────────────────────┘
         ▲ bootstrap: <kafka-lb-ip>:9094
         │  (DNS entry or static LB IP configured via values.yaml)
         │
┌────────┴──────────┐  ┌────────────────────┐  ┌──────────────────────┐
│  Cluster B        │  │  Cluster C          │  │  Cluster D / E       │
│  Producer         │  │  Consumer           │  │  Arbiter/Controller  │
│  :8000 (API)      │  │  :8001 (API)        │  │  :8002/:8003 (API)   │
│  :3000 (UI)       │  │  :3001 (UI)         │  │  :3002/:3003 (UI)    │
└───────────────────┘  └────────────────────┘  └──────────────────────┘
         │  REST                  │  REST                   │  REST
         └────────────────────────┴─────────────────────────┘
                                Arbiter polls all
```

### Service Discovery

Kafka bootstrap addresses are injected at deploy-time via Helm values (environment variables). Inside Cluster A, in-cluster consumers use the Kubernetes Service DNS name (`hamq-kafka-kafka-bootstrap.kafka.svc.cluster.local:9093`). External consumers use the LoadBalancer IP or a stable DNS CNAME that points to the LoadBalancer.

The Producer implements **runtime DNS re-resolution**: it resolves the bootstrap hostname every N seconds and reconnects if the resolved IP changes, handling rolling LB IP changes transparently.

---

## TLS / mTLS Setup

All Kafka communication is TLS-encrypted. Client authentication uses mutual TLS (mTLS): both broker and client present certificates issued by the same cert-manager ClusterIssuer.

### Certificate Hierarchy

```
ClusterIssuer: selfsigned-issuer  (cert-manager, bootstrapped once)
       │
       ├── CA Certificate  →  kafka-cluster-ca  (Strimzi-managed)
       │       │
       │       ├── Broker certificate  (per-broker SAN, auto-rotated by Strimzi)
       │       ├── KafkaUser: hamq-producer  →  client cert in Secret
       │       └── KafkaUser: hamq-consumer  →  client cert in Secret
       │
       └── CA Certificate  →  kafka-clients-ca  (Strimzi-managed)
```

### How Strimzi manages certificates

1. Strimzi creates two `Secret` objects: `hamq-kafka-cluster-ca-cert` (cluster CA) and `hamq-kafka-clients-ca-cert` (clients CA).
2. For each `KafkaUser` resource with `authentication.type: tls`, Strimzi's User Operator issues a signed client certificate stored in `Secret/<username>`.
3. Applications mount the secrets as volumes or env vars to obtain `ca.crt`, `user.crt`, `user.key`.
4. cert-manager (via the `certManager.issuerName` value) is used for any additional certificates (e.g., Ingress TLS, inter-component mTLS).

### Application mTLS configuration

Each application component receives three environment variables:

```
KAFKA_CA_CERT        = /certs/ca.crt
KAFKA_CLIENT_CERT    = /certs/user.crt
KAFKA_CLIENT_KEY     = /certs/user.key
```

These are mounted from the Strimzi-generated `KafkaUser` secret into the application pod.

---

## High-Availability Guarantees

HAMq's durability posture is "at-least-once delivery with producer-side exactly-once deduplication".

| Guarantee | Mechanism |
|---|---|
| No message loss | `acks=all` — broker only acks after all ISR replicas have written |
| Survive 1 broker failure | RF=3 means 2 replicas remain after 1 failure |
| No silent write degradation | `min.insync.replicas=2` — producer gets an error (not silent drop) if fewer than 2 replicas are in sync |
| Producer survives broker outage | Local SQLite buffer + async retry loop |
| No split-brain | KRaft quorum requires majority (2 of 3) for leader elections |
| Metadata durability | KRaft log stored on same persistent volumes as broker data |
| Consumer progress durability | Consumer group offsets stored in `__consumer_offsets` topic (RF=3) |

### Failure scenarios

| Scenario | Behaviour |
|---|---|
| 1 broker pod restart | Leader election completes in ~5 s; zero producer errors (remaining ISR ≥ 2) |
| 2 broker pods down simultaneously | Producer receives `NotEnoughReplicasException`; messages buffered locally; recovered when brokers return |
| Network partition isolating 1 broker | Partitioned broker removed from ISR; cluster continues with 2 replicas |
| Kafka cluster fully down | Producer buffers to SQLite; consumer pauses; Arbiter reports outage; Controller may trigger restart |
| Rolling restart (1 broker at a time) | Zero data loss; leader elections staggered by PodDisruptionBudget |

---

## Producer Resilience

The Producer's durability architecture is designed to survive any partial Kafka outage without losing messages.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Producer Component                                                  │
│                                                                      │
│  ┌──────────────┐   write    ┌──────────────────────────────────┐   │
│  │  Generator   │──────────▶│  SQLite Buffer (WAL mode)         │   │
│  │  (freq_hz)   │           │  table: pending_messages          │   │
│  └──────────────┘           │  columns: id, payload, created_at │   │
│                              └──────────────┬───────────────────┘   │
│                                             │  drain loop            │
│                              ┌──────────────▼───────────────────┐   │
│                              │  Kafka Publisher                  │   │
│                              │  confluent-kafka-python           │   │
│                              │  acks=all, retries=MAX_INT        │   │
│                              │  delivery.timeout.ms=120000       │   │
│                              └──────────────┬───────────────────┘   │
│                                             │  on ack                │
│                              ┌──────────────▼───────────────────┐   │
│                              │  Delete from SQLite buffer        │   │
│                              └───────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

### Retry logic

1. **Generate**: A background coroutine generates messages at the configured `frequency_hz`. Each message is first written to SQLite (WAL + fsync) so it survives a producer pod restart.
2. **Publish**: A separate drain coroutine reads un-acked messages from SQLite and calls `producer.produce()`. The Kafka client library handles retries internally with exponential back-off.
3. **Confirm**: On delivery callback (`on_delivery(err, msg)`), if `err is None` the message row is deleted from SQLite. If `err` is non-None the message remains in SQLite for the next drain cycle.
4. **DNS re-resolution**: The Kafka bootstrap hostname is re-resolved every 60 seconds. If the IP changes (e.g., LoadBalancer IP rotated), the producer client is reinitialised transparently.

### Buffer limits

The SQLite buffer is bounded by `PRODUCER_BUFFER_MAX_MESSAGES` (default: 1 000 000). When the buffer is full, new message generation is paused (back-pressure) rather than dropping messages. An alert fires on `hamq_producer_buffer_size > 10000`.

---

## Message Flow

```
Producer                  Kafka Cluster              Consumer
   │                           │                         │
   │  1. generate message       │                         │
   │  2. write to SQLite        │                         │
   │──────────── produce() ────▶│                         │
   │             (TLS/mTLS)     │  3. replicate to ISR   │
   │                           │◀─────────────────────── │
   │                           │  4. acks=all: all ISR   │
   │◀───────── delivery ack ───│     confirmed           │
   │  5. delete from SQLite    │                         │
   │                           │──── poll() ────────────▶│
   │                           │  6. consumer reads      │
   │                           │     (TLS/mTLS)          │
   │                           │                         │ 7. validate checksum
   │                           │                         │ 8. track sequence
   │                           │                         │ 9. commit offset
   │                           │                         │
   │                     Arbiter polls                    │
   │◀────────── GET /status ───────────────── REST ──────▶│
   │  10. sent_sequences        │           received_seqs │
   │                           │                         │
   │                    Arbiter computes delta            │
   │                    lost = sent - received            │
   │                    emits Prometheus metrics          │
```

Steps 1–5 ensure the producer never loses a message: the SQLite write is synchronous; the Kafka publish and the SQLite delete are decoupled by the drain loop. If the producer pod crashes between steps 2 and 5, the message will be re-sent after restart (at-least-once semantics).
