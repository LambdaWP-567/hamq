# HAMq — Highly Available Message Queue System

A production-grade, Kubernetes-native message broker system built on Apache Kafka (Strimzi), with resilient producers, consumers, a message-loss arbiter, and a chaos-engineering cluster controller.

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                    Cluster A  (Kafka Cluster)                      │
│   ┌──────────────────────────────────────────────────────────┐    │
│   │  Strimzi Kafka  ·  3 Brokers  ·  KRaft  ·  TLS  ·  RF3  │    │
│   │           min.insync.replicas = 2   acks = all           │    │
│   └──────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
         ▲ write (TLS/mTLS)          ▼ read (TLS/mTLS)
┌─────────────────┐          ┌─────────────────┐
│  Producer       │          │  Consumer        │
│  (Cluster B)    │          │  (Cluster C)     │
│  Python FastAPI │          │  Python FastAPI  │
│  React UI       │          │  React UI        │
│  Local Buffer   │          │  REST + WS API   │
└─────────────────┘          └─────────────────┘
         │                            │
         └────────────────────────────┘
                       │ compare
              ┌─────────────────┐
              │  Arbiter        │
              │  (Cluster D)    │
              │  Python FastAPI │
              │  React UI       │
              └─────────────────┘
                       │
              ┌─────────────────┐
              │  Controller     │
              │  (Cluster E)    │
              │  Python FastAPI │
              │  React UI       │
              │  K8s API access │
              └─────────────────┘
```

## Components

| Component | Description | Port |
|-----------|-------------|------|
| [kafka-cluster](components/kafka-cluster/) | Strimzi Kafka HA cluster | 9092 (plain) / 9093 (TLS) |
| [producer](components/producer/) | Resilient message producer (1–1000 msg/s) | 8000 (API) / 3000 (UI) |
| [consumer](components/consumer/) | Message consumer with persistence | 8001 (API) / 3001 (UI) |
| [arbiter](components/arbiter/) | Message-loss detector & reporter | 8002 (API) / 3002 (UI) |
| [controller](components/controller/) | Chaos & cluster lifecycle controller | 8003 (API) / 3003 (UI) |

## Quick Start

```bash
# 1. Install Strimzi operator
helm repo add strimzi https://strimzi.io/charts/
helm install strimzi-operator strimzi/strimzi-kafka-operator -n kafka --create-namespace

# 2. Deploy Kafka cluster
helm install kafka-cluster components/kafka-cluster/helm -n kafka

# 3. Deploy application components
helm install producer    components/producer/helm    -n hamq --create-namespace
helm install consumer    components/consumer/helm    -n hamq
helm install arbiter     components/arbiter/helm     -n hamq
helm install controller  components/controller/helm  -n hamq
```

## Documentation

- [Architecture](docs/architecture.md)
- [Getting Started](docs/getting-started.md)
- [Deployment Guide](docs/deployment.md)
- [Kafka Cluster](docs/components/kafka-cluster.md)
- [Producer](docs/components/producer.md)
- [Consumer](docs/components/consumer.md)
- [Arbiter](docs/components/arbiter.md)
- [Controller](docs/components/controller.md)

## Key Design Decisions

- **No message loss**: `acks=all`, `min.insync.replicas=2`, RF=3, producer local buffer on Kafka unavailability
- **Producer resilience**: Local SQLite buffer + async retry loop; survives broker restarts and IP changes
- **Bootstrap discovery**: DNS-based service discovery (K8s Service names), never hardcoded IPs
- **TLS everywhere**: cert-manager issues certificates; mTLS between components
- **Observability**: Prometheus metrics on all components, Grafana dashboards included

## CI/CD

GitHub Actions pipelines build and push Docker images on every push to `main` or component-specific branches.
See [`.github/workflows/`](.github/workflows/).
