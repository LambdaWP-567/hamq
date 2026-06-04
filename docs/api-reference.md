# API Reference

All HAMq components expose a FastAPI HTTP REST API and a WebSocket endpoint. All endpoints except `/health` and `POST /api/auth/login` require a valid JWT bearer token.

---

## Authentication

### Obtaining a Token

All four components use the same JWT-based authentication flow.

**Request:**

```http
POST /api/auth/login
Content-Type: application/json

{
  "username": "admin",
  "password": "your-password"
}
```

**Response (200 OK):**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Using the token:**

Include the token in the `Authorization` header of all subsequent requests:

```http
GET /api/status
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

Tokens expire after `AUTH_TOKEN_EXPIRE_MINUTES` (default: 1440 minutes = 24 hours).

---

## Producer API

**Base URL:** `http://<producer-host>:8000`

### GET /health

Health check endpoint. No authentication required.

**Response (200 OK):**

```json
{
  "status": "ok"
}
```

### POST /api/auth/login

Obtain a JWT token.

**Request body:**

```json
{
  "username": "admin",
  "password": "secret"
}
```

**Response (200 OK):**

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer"
}
```

**Response (401 Unauthorized):**

```json
{
  "detail": "Invalid credentials"
}
```

### GET /api/status

Returns the current producer state.

**Response (200 OK):**

```json
{
  "producer_id": "producer-0",
  "running": true,
  "frequency_hz": 10.0,
  "sequence_counter": 4821,
  "buffered_count": 0,
  "sent_count": 4821,
  "error_count": 0,
  "kafka_connected": true
}
```

| Field | Type | Description |
|---|---|---|
| `producer_id` | string | Unique identifier for this producer instance |
| `running` | boolean | `true` while the message-generation loop is active |
| `frequency_hz` | float | Current message generation frequency in msg/s |
| `sequence_counter` | integer | Last sequence number assigned (0 = no messages sent yet) |
| `buffered_count` | integer | Messages in the local SQLite buffer awaiting Kafka delivery |
| `sent_count` | integer | Total messages successfully delivered to Kafka this session |
| `error_count` | integer | Total send errors this session |
| `kafka_connected` | boolean | `true` when the Kafka producer client is healthy |

### POST /api/start

Start message generation.

**Request body:**

```json
{
  "action": "start"
}
```

**Response (200 OK):**

```json
{
  "message": "Producer started"
}
```

### POST /api/stop

Stop message generation.

**Request body:**

```json
{
  "action": "stop"
}
```

**Response (200 OK):**

```json
{
  "message": "Producer stopped"
}
```

### PUT /api/frequency

Update the message generation frequency.

**Request body:**

```json
{
  "frequency_hz": 50.0
}
```

Valid range: `1.0` – `1000.0` msg/s.

**Response (200 OK):**

```json
{
  "message": "Frequency updated",
  "frequency_hz": 50.0
}
```

**Response (422 Unprocessable Entity):**

```json
{
  "detail": [
    {
      "loc": ["body", "frequency_hz"],
      "msg": "ensure this value is less than or equal to 1000.0",
      "type": "value_error.number.not_le"
    }
  ]
}
```

### WebSocket /ws/status

Streams live producer status updates every second.

**Connection:** `ws://<producer-host>:8000/ws/status`

**Authentication:** Pass the JWT token as a query parameter:

```
ws://<producer-host>:8000/ws/status?token=<jwt>
```

**Message format (server → client, every 1 second):**

```json
{
  "type": "status_update",
  "producer_id": "producer-0",
  "running": true,
  "frequency_hz": 10.0,
  "sequence_counter": 4825,
  "buffered_count": 2,
  "sent_count": 4823,
  "error_count": 0,
  "kafka_connected": true
}
```

### GET /metrics

Prometheus metrics endpoint (no authentication required).

Returns standard Prometheus text format with metrics including:

- `hamq_producer_messages_sent_total` — counter
- `hamq_producer_buffer_size` — gauge
- `hamq_producer_errors_total` — counter
- `hamq_producer_kafka_connected` — gauge (1 = connected)

---

## Consumer API

**Base URL:** `http://<consumer-host>:8001`

### GET /health

Health check. No authentication required.

**Response (200 OK):**

```json
{
  "status": "ok"
}
```

### POST /api/auth/login

Obtain a JWT token. Same schema as Producer.

### GET /api/status

Returns the current consumer state.

**Response (200 OK):**

```json
{
  "consumer_id": "consumer-1",
  "running": true,
  "kafka_connected": true,
  "received_count": 4820,
  "last_sequence_by_producer": {
    "producer-0": 4821
  },
  "lag_estimate": 1,
  "checksum_errors": 0
}
```

| Field | Type | Description |
|---|---|---|
| `consumer_id` | string | Logical identifier for this consumer instance |
| `running` | boolean | `true` when the Kafka consume loop is active |
| `kafka_connected` | boolean | `true` when the Kafka connection is healthy |
| `received_count` | integer | Total messages received and persisted since start |
| `last_sequence_by_producer` | object | Map of `producer_id` → last sequence number seen |
| `lag_estimate` | integer | Estimated number of messages behind the latest Kafka offset |
| `checksum_errors` | integer | Count of messages with invalid SHA-256 checksums |

### GET /api/messages

Query persisted messages with optional filtering and pagination.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `producer_id` | string | (all) | Filter by producer identity |
| `sequence_from` | integer | 1 | Lower bound of sequence range (inclusive) |
| `sequence_to` | integer | 1000000000 | Upper bound of sequence range (inclusive) |
| `page` | integer | 1 | Page number (1-based) |
| `page_size` | integer | 100 | Messages per page (max 1000) |

**Example request:**

```http
GET /api/messages?producer_id=producer-0&sequence_from=100&sequence_to=200&page=1&page_size=50
Authorization: Bearer <jwt>
```

**Response (200 OK):**

```json
{
  "messages": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "sequence": 100,
      "producer_id": "producer-0",
      "received_at": "2026-01-15T12:34:57.123456Z",
      "timestamp": "2026-01-15T12:34:56.789012Z",
      "frequency_hz": 10.0,
      "payload_data": "SGVsbG8gV29ybGQ=",
      "checksum_valid": true
    }
  ],
  "total": 101,
  "page": 1,
  "page_size": 50
}
```

### WebSocket /ws/status

Streams live consumer status plus recent messages every second.

**Connection:** `ws://<consumer-host>:8001/ws/status?token=<jwt>`

**Message format (server → client, every 1 second):**

```json
{
  "type": "status_update",
  "status": {
    "consumer_id": "consumer-1",
    "running": true,
    "kafka_connected": true,
    "received_count": 4823,
    "last_sequence_by_producer": {
      "producer-0": 4823
    },
    "lag_estimate": 0,
    "checksum_errors": 0
  },
  "recent_messages": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440003",
      "sequence": 4823,
      "producer_id": "producer-0",
      "received_at": "2026-01-15T12:35:01.234567Z",
      "timestamp": "2026-01-15T12:35:01.000000Z",
      "frequency_hz": 10.0,
      "payload_data": "SGVsbG8gV29ybGQ=",
      "checksum_valid": true
    }
  ]
}
```

### GET /metrics

Prometheus metrics endpoint (no authentication required).

Metrics include:

- `hamq_consumer_messages_received_total` — counter
- `hamq_consumer_checksum_failures_total` — counter
- `hamq_consumer_lag_estimate` — gauge
- `hamq_consumer_kafka_connected` — gauge

---

## Arbiter API

**Base URL:** `http://<arbiter-host>:8002`

### GET /health

Health check. No authentication required.

### POST /api/auth/login

Obtain a JWT token. Same schema as Producer.

### GET /api/status

Returns the current arbiter state and latest reconciliation summary.

**Response (200 OK):**

```json
{
  "arbiter_id": "arbiter-1",
  "running": true,
  "last_reconcile_at": "2026-01-15T12:35:00.000000Z",
  "producer_urls": ["http://hamq-producer.hamq.svc.cluster.local:8000"],
  "consumer_url": "http://hamq-consumer.hamq.svc.cluster.local:8001",
  "total_audits": 12,
  "latest_loss_rate": 0.0,
  "latest_gap_count": 0
}
```

### GET /api/audits

List recent audit results.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | integer | 20 | Number of most recent audits to return |

**Response (200 OK):**

```json
{
  "audits": [
    {
      "id": "audit-uuid-1",
      "timestamp": "2026-01-15T12:35:00.000000Z",
      "producer_id": "producer-0",
      "sent_count": 4823,
      "received_count": 4823,
      "missing_sequences": [],
      "loss_rate": 0.0,
      "duplicate_count": 0,
      "checksum_errors": 0
    }
  ],
  "total": 12
}
```

### POST /api/reconcile

Trigger an immediate reconciliation pass (rather than waiting for the scheduled interval).

**Response (200 OK):**

```json
{
  "message": "Reconciliation triggered",
  "audit_id": "audit-uuid-13"
}
```

### GET /api/alerts

List recent alert events.

**Response (200 OK):**

```json
{
  "alerts": [
    {
      "id": "alert-uuid-1",
      "timestamp": "2026-01-15T11:00:00.000000Z",
      "producer_id": "producer-0",
      "loss_rate": 0.025,
      "missing_sequences": [4100, 4101, 4102],
      "severity": "HIGH"
    }
  ]
}
```

### WebSocket /ws/status

Streams live arbiter status and latest audit every second.

**Connection:** `ws://<arbiter-host>:8002/ws/status?token=<jwt>`

**Message format (server → client, every 1 second):**

```json
{
  "type": "status_update",
  "arbiter_id": "arbiter-1",
  "running": true,
  "latest_loss_rate": 0.0,
  "latest_gap_count": 0,
  "last_reconcile_at": "2026-01-15T12:35:00.000000Z"
}
```

### GET /metrics

Prometheus metrics endpoint (no authentication required).

Metrics include:

- `hamq_arbiter_loss_rate` — gauge
- `hamq_arbiter_missing_sequences_total` — counter
- `hamq_arbiter_duplicate_sequences_total` — counter
- `hamq_arbiter_reconcile_duration_seconds` — histogram
- `hamq_arbiter_alerts_fired_total` — counter

---

## Controller API

**Base URL:** `http://<controller-host>:8003`

### GET /health

Health check. No authentication required.

### POST /api/auth/login

Obtain a JWT token. Same schema as Producer.

### GET /api/status

Returns the controller state.

**Response (200 OK):**

```json
{
  "controller_id": "controller-1",
  "running": true,
  "kubernetes_connected": true,
  "active_scenario": null,
  "completed_scenarios": 3,
  "last_action_at": "2026-01-15T12:00:00.000000Z"
}
```

### GET /api/scenarios

List available chaos scenarios.

**Response (200 OK):**

```json
{
  "scenarios": [
    {
      "id": "rolling-restart",
      "name": "Rolling Broker Restart",
      "description": "Restarts Kafka broker pods one at a time with a configurable delay",
      "parameters": {
        "delay_seconds": {"type": "integer", "default": 30, "min": 5}
      }
    },
    {
      "id": "single-broker-kill",
      "name": "Single Broker Kill",
      "description": "Deletes one broker pod and waits for recovery",
      "parameters": {
        "broker_index": {"type": "integer", "default": 0, "min": 0, "max": 2}
      }
    },
    {
      "id": "network-partition",
      "name": "Network Partition",
      "description": "Injects a NetworkPolicy to isolate one broker pod from the others",
      "parameters": {
        "broker_index": {"type": "integer", "default": 0},
        "duration_seconds": {"type": "integer", "default": 60}
      }
    }
  ]
}
```

### POST /api/scenarios/{scenario_id}/run

Execute a chaos scenario.

**Path parameter:** `scenario_id` — one of the IDs from `GET /api/scenarios`

**Request body:**

```json
{
  "parameters": {
    "delay_seconds": 45
  }
}
```

**Response (202 Accepted):**

```json
{
  "run_id": "run-uuid-1",
  "scenario_id": "rolling-restart",
  "status": "running",
  "started_at": "2026-01-15T12:01:00.000000Z"
}
```

### GET /api/scenarios/runs/{run_id}

Get the status of a running or completed scenario execution.

**Response (200 OK):**

```json
{
  "run_id": "run-uuid-1",
  "scenario_id": "rolling-restart",
  "status": "completed",
  "started_at": "2026-01-15T12:01:00.000000Z",
  "completed_at": "2026-01-15T12:03:30.000000Z",
  "steps": [
    {
      "step": 1,
      "action": "delete_pod",
      "target": "hamq-kafka-0",
      "status": "completed",
      "timestamp": "2026-01-15T12:01:05.000000Z"
    },
    {
      "step": 2,
      "action": "wait_for_ready",
      "target": "hamq-kafka-0",
      "status": "completed",
      "timestamp": "2026-01-15T12:01:35.000000Z"
    }
  ],
  "arbiter_audit_id": "audit-uuid-42"
}
```

### DELETE /api/scenarios/runs/{run_id}

Abort a running scenario execution.

**Response (200 OK):**

```json
{
  "message": "Scenario run aborted",
  "run_id": "run-uuid-1"
}
```

### POST /api/restart

Trigger a controlled rolling restart of a specific deployment.

**Request body:**

```json
{
  "namespace": "kafka",
  "deployment": "hamq-kafka",
  "delay_seconds": 30
}
```

**Response (202 Accepted):**

```json
{
  "message": "Rolling restart initiated",
  "run_id": "run-uuid-2"
}
```

### WebSocket /ws/status

Streams live controller status every second.

**Connection:** `ws://<controller-host>:8003/ws/status?token=<jwt>`

**Message format (server → client, every 1 second):**

```json
{
  "type": "status_update",
  "controller_id": "controller-1",
  "running": true,
  "kubernetes_connected": true,
  "active_scenario": {
    "run_id": "run-uuid-1",
    "scenario_id": "rolling-restart",
    "status": "running",
    "current_step": 2
  }
}
```

### GET /metrics

Prometheus metrics endpoint (no authentication required).

Metrics include:

- `hamq_controller_scenarios_run_total` — counter (labelled by `scenario_id`)
- `hamq_controller_scenarios_active` — gauge
- `hamq_controller_k8s_api_errors_total` — counter

---

## Common Error Responses

All endpoints return standard HTTP status codes and a JSON detail body on error.

### 401 Unauthorized

```json
{
  "detail": "Not authenticated"
}
```

Returned when the `Authorization` header is missing or the token is expired.

### 403 Forbidden

```json
{
  "detail": "Not enough permissions"
}
```

### 404 Not Found

```json
{
  "detail": "Resource not found"
}
```

### 422 Unprocessable Entity

```json
{
  "detail": [
    {
      "loc": ["body", "frequency_hz"],
      "msg": "value is not a valid float",
      "type": "type_error.float"
    }
  ]
}
```

### 500 Internal Server Error

```json
{
  "detail": "Internal server error"
}
```

---

## OpenAPI / Swagger UI

Each component exposes an interactive Swagger UI at `/docs` and a machine-readable OpenAPI JSON schema at `/openapi.json`.

| Component | Swagger UI | OpenAPI JSON |
|---|---|---|
| Producer | `http://<host>:8000/docs` | `http://<host>:8000/openapi.json` |
| Consumer | `http://<host>:8001/docs` | `http://<host>:8001/openapi.json` |
| Arbiter | `http://<host>:8002/docs` | `http://<host>:8002/openapi.json` |
| Controller | `http://<host>:8003/docs` | `http://<host>:8003/openapi.json` |
