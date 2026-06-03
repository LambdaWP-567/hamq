# Controller Component

The Controller orchestrates lifecycle operations and chaos engineering experiments across all HAMq clusters using the Kubernetes API. It provides scripted and ad-hoc mechanisms to test the system's durability guarantees under failure conditions.

---

## Table of Contents

- [Architecture](#architecture)
- [Chaos Capabilities](#chaos-capabilities)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Web UI](#web-ui)
- [RBAC Requirements](#rbac-requirements)
- [Metrics](#metrics)
- [Deployment](#deployment)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Controller Pod (Cluster E)                                          │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Kubernetes API Client (in-cluster ServiceAccount)            │   │
│  │  Target clusters: A (kafka), B (producer), C (consumer)       │   │
│  │  Access: Pod delete, NetworkPolicy create/delete, scale       │   │
│  └──────────────────────────────┬─────────────────────────────┘    │
│                                  │                                    │
│  ┌───────────────────────────────▼──────────────────────────────┐   │
│  │  Scenario Engine                                              │   │
│  │  - Scenario definitions (YAML/JSON)                          │   │
│  │  - Step executor (serial or parallel)                        │   │
│  │  - Wait conditions (pod ready, metric threshold)             │   │
│  │  - Result collector (Arbiter report snapshot per step)       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Component API Clients                                        │   │
│  │  Producer: GET /stats, POST /start, POST /stop               │   │
│  │  Consumer: GET /stats, GET /sequences                        │   │
│  │  Arbiter: GET /report                                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Results Store (SQLite: /data/controller.db)                  │   │
│  │  Scenario runs, per-step Arbiter snapshots, timing           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  FastAPI HTTP server (:8003)  +  React SPA (:3003)            │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Chaos Capabilities

### Broker pod deletion (crash simulation)

Deletes one or more Kafka broker pods to simulate a crash. Kafka's built-in leader election and ISR recovery mechanisms are exercised:

```bash
# Via API
curl -X POST http://<controller-ip>:8003/api/v1/chaos/broker-restart \
  -H 'Content-Type: application/json' \
  -d '{"broker_index": 1, "delay_seconds": 0}'
```

**System behaviour:** With RF=3 and min.insync.replicas=2, losing one broker leaves the cluster fully operational. The Arbiter should report zero message loss.

### Simultaneous broker deletion (ISR quorum violation)

Deletes 2 of 3 brokers simultaneously to verify that the producer correctly receives `NotEnoughReplicasException` and buffers messages locally:

```bash
curl -X POST http://<controller-ip>:8003/api/v1/chaos/multi-broker-restart \
  -d '{"broker_indices": [0, 1], "delay_seconds": 0}'
```

**Expected behaviour:** Producer buffer size spikes; after brokers recover, all buffered messages are delivered; Arbiter reports zero loss.

### Network partition (NetworkPolicy injection)

Injects a Kubernetes `NetworkPolicy` that isolates one broker from the others, simulating a network partition:

```bash
curl -X POST http://<controller-ip>:8003/api/v1/chaos/network-partition \
  -d '{"broker_index": 2, "duration_seconds": 30}'
```

The Controller removes the NetworkPolicy after `duration_seconds`. The isolated broker is evicted from ISRs during the partition and re-joins after network restoration.

### Rolling restart

Performs a controlled rolling restart of all broker pods, one at a time, with a configurable wait between each:

```bash
curl -X POST http://<controller-ip>:8003/api/v1/chaos/rolling-restart \
  -d '{"wait_seconds_between_brokers": 60}'
```

**Expected behaviour:** Zero message loss throughout, assuming PodDisruptionBudget is enforced.

### Producer restart

Restarts the producer pod to verify that the SQLite buffer survives and no messages are lost:

```bash
curl -X POST http://<controller-ip>:8003/api/v1/chaos/producer-restart
```

### Controlled scenario scripts

Pre-defined scenarios combine multiple chaos steps with measurement points:

| Scenario | Steps |
|----------|-------|
| `single-broker-failure` | Start producer → delete broker 0 → wait recovery → stop → report |
| `dual-broker-failure` | Start producer → delete brokers 0,1 → wait recovery → stop → report |
| `rolling-restart-under-load` | Start producer at 1000 msg/s → rolling restart → stop → report |
| `network-partition-30s` | Start producer → isolate broker 2 for 30 s → stop → report |
| `producer-crash-recovery` | Start producer → delete producer pod → restart → stop → report |

---

## Configuration

### Helm values (`components/controller/helm/values.yaml`)

| Key | Default | Description |
|-----|---------|-------------|
| `controller.producerApiUrl` | `""` | **Required.** Producer API base URL |
| `controller.consumerApiUrl` | `""` | **Required.** Consumer API base URL |
| `controller.arbiterApiUrl` | `""` | **Required.** Arbiter API base URL |
| `controller.kafkaNamespace` | `kafka` | Namespace where Kafka pods run |
| `controller.kafkaClusterName` | `hamq-kafka` | Strimzi Kafka resource name (used to build pod label selectors) |
| `controller.producerNamespace` | `hamq` | Namespace where Producer runs |
| `controller.consumerNamespace` | `hamq` | Namespace where Consumer runs |
| `controller.httpTimeoutSeconds` | `10` | Timeout for outbound API calls |
| `controller.resultRetentionDays` | `30` | Days of scenario results to retain |
| `image.repository` | `ghcr.io/lambdawp-567/hamq-controller` | Container image |
| `image.tag` | `latest` | Image tag |
| `api.port` | `8003` | FastAPI HTTP port |
| `ui.port` | `3003` | React SPA port |
| `logLevel` | `info` | Python logging level |
| `rbac.create` | `true` | Create RBAC ServiceAccount and ClusterRole |

### Environment variables

See the [Deployment guide environment variable table](../deployment.md#controller-cluster-e).

---

## API Endpoints

The Controller exposes a FastAPI HTTP server on port `8003`.

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status": "ok"}` |

### Chaos operations (ad-hoc)

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/chaos/broker-restart` | `{"broker_index": int, "delay_seconds": int}` | Delete one broker pod |
| `POST` | `/api/v1/chaos/multi-broker-restart` | `{"broker_indices": [int], "delay_seconds": int}` | Delete multiple broker pods |
| `POST` | `/api/v1/chaos/network-partition` | `{"broker_index": int, "duration_seconds": int}` | Isolate a broker via NetworkPolicy |
| `POST` | `/api/v1/chaos/rolling-restart` | `{"wait_seconds_between_brokers": int}` | Rolling restart of all brokers |
| `POST` | `/api/v1/chaos/producer-restart` | — | Delete producer pod |
| `POST` | `/api/v1/chaos/consumer-restart` | — | Delete consumer pod |

### Scenario management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/scenarios` | List all available scenario definitions |
| `POST` | `/api/v1/scenarios/{name}/run` | Execute a named scenario |
| `GET` | `/api/v1/scenarios/{name}/runs` | List historical runs for a scenario |
| `GET` | `/api/v1/scenarios/runs/{run_id}` | Full result for a specific run |

#### Scenario run response schema

```json
{
  "run_id": "a7f3b2c1-...",
  "scenario": "single-broker-failure",
  "started_at": "2026-01-15T12:30:00.000000Z",
  "finished_at": "2026-01-15T12:32:15.000000Z",
  "status": "completed",
  "steps": [
    {
      "name": "start_producer",
      "started_at": "2026-01-15T12:30:00.000000Z",
      "duration_seconds": 0.2,
      "status": "ok"
    },
    {
      "name": "delete_broker_0",
      "started_at": "2026-01-15T12:30:05.000000Z",
      "duration_seconds": 0.5,
      "status": "ok"
    },
    {
      "name": "wait_recovery",
      "started_at": "2026-01-15T12:30:05.500000Z",
      "duration_seconds": 45.3,
      "status": "ok"
    }
  ],
  "arbiter_report_before": { "loss_rate": 0.0, "total_sent": 5000 },
  "arbiter_report_after":  { "loss_rate": 0.0, "total_sent": 7234 },
  "verdict": "PASS",
  "notes": "Zero message loss during single broker failure as expected"
}
```

### Kubernetes operations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/k8s/pods?namespace=kafka` | List pods in a namespace |
| `GET` | `/api/v1/k8s/nodes` | List cluster nodes |
| `GET` | `/api/v1/k8s/kafka/status` | Current Kafka cluster status from Strimzi |

### WebSocket

| Path | Protocol | Description |
|------|----------|-------------|
| `/ws/scenarios` | WebSocket | Streams live step updates during scenario execution |

---

## Web UI

The React SPA is served on port `3003`.

### Dashboard features

- **Scenario launcher** — dropdown of available scenarios, run button, live log of steps
- **Live step progress** — real-time status of in-progress scenario steps
- **Results history** — table of past scenario runs, PASS/FAIL verdict, link to detail view
- **Run detail view** — timeline of steps, before/after Arbiter report comparison, message loss chart
- **Ad-hoc chaos panel** — quick buttons for individual chaos operations
- **Cluster health overview** — Kafka pod status, producer/consumer connectivity from all clusters
- **Kubernetes resource browser** — pods, deployments, and events in watched namespaces

---

## RBAC Requirements

The Controller requires Kubernetes API access to the clusters it manages. The Helm chart creates a `ServiceAccount` with a `ClusterRole` binding (or targeted `Role` bindings if `rbac.clusterScoped: false`).

### Required permissions (Cluster A — Kafka)

```yaml
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "delete"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["get", "list", "create", "delete"]
  - apiGroups: ["kafka.strimzi.io"]
    resources: ["kafkas", "kafkanodepools"]
    verbs: ["get", "list"]
```

### Required permissions (Cluster B/C — Producer/Consumer)

```yaml
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "patch"]
```

> **Security note:** The Controller has pod-delete permissions on the Kafka namespace. This is intentional (chaos engineering requires it) but should be restricted by namespace scope. Never give the Controller cluster-wide pod-delete permissions in production.

---

## Metrics

The Controller exposes Prometheus metrics on `/metrics`.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `hamq_controller_scenarios_run_total` | Counter | `scenario`, `verdict` | Total scenario runs by outcome |
| `hamq_controller_chaos_ops_total` | Counter | `operation`, `status` | Individual chaos operation counts |
| `hamq_controller_scenario_duration_seconds` | Histogram | `scenario` | Duration of scenario runs |
| `hamq_controller_k8s_api_errors_total` | Counter | `operation`, `error` | Kubernetes API call errors |

---

## Deployment

```bash
helm install hamq-controller components/controller/helm \
  --namespace hamq \
  --set controller.producerApiUrl="http://producer.hamq.example.com:8000" \
  --set controller.consumerApiUrl="http://consumer.hamq.example.com:8001" \
  --set controller.arbiterApiUrl="http://arbiter.hamq.example.com:8002" \
  --set controller.kafkaNamespace=kafka \
  --set controller.kafkaClusterName=hamq-kafka
```

### Cross-cluster kubeconfig

By default the Controller uses its in-cluster ServiceAccount token, which only provides access to the cluster it runs in (Cluster E). To control Clusters A–D, provide kubeconfigs as Kubernetes Secrets:

```bash
# Create a kubeconfig secret for Cluster A (Kafka)
kubectl -n hamq create secret generic kafka-kubeconfig \
  --from-file=kubeconfig=/path/to/cluster-a-kubeconfig

# Reference in values.yaml
# controller:
#   externalKubeconfigs:
#     kafka:
#       secretName: kafka-kubeconfig
#       key: kubeconfig
```
