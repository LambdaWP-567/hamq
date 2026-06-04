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

---

## Test Cluster Deployment (KVM / k3s)

This section documents how to spin up a local 3-node k3s cluster on KVM, deploy HAMq to it, and access all UIs from the host LAN.

### Requirements

| Requirement | Version / Notes |
|-------------|----------------|
| Linux host | Debian / Ubuntu recommended |
| CPU | Intel/AMD with VT-x or AMD-V (`/dev/kvm` must exist) |
| RAM | ≥ 8 GB (3 × 2 GB VMs + 2 GB host headroom) |
| Disk | ≥ 40 GB free |
| `helm` | v3.x or v4.x |
| `kubectl` | any recent version |
| GitHub PAT | `read:packages` scope — for pulling GHCR images |

Packages installed automatically by `infra/setup-cluster.sh`:
`qemu-kvm libvirt-daemon-system libvirt-clients virtinst cloud-image-utils`

### 1 — Provision the k3s cluster

```bash
sudo bash infra/setup-cluster.sh 2>&1 | tee /tmp/cluster-setup.log
```

Creates 3 Ubuntu 24.04 VMs (`k3s-cp`, `k3s-w1`, `k3s-w2`) on libvirt NAT network `192.168.122.0/24`, installs k3s via k3sup, and writes `infra/kubeconfig`.

### 2 — Install MetalLB and expose UIs to the LAN

```bash
sudo bash infra/setup-metallb.sh 2>&1 | tee /tmp/metallb-setup.log
```

- Disables k3s built-in `servicelb`
- Installs MetalLB with L2 pool `192.168.122.200–210`
- Traefik gets `192.168.122.200` as its LoadBalancer IP
- Creates proxy `Endpoints + Ingress` in the existing single-node k3s cluster (reachable at `192.168.1.22`) so that `*.hamq.local` is accessible from the full LAN on port 80
- Adds `/etc/hosts` entries on the host

### 3 — Deploy HAMq

```bash
export GHCR_TOKEN=<your-github-pat>
bash infra/deploy.sh 2>&1 | tee /tmp/deploy.log
```

Deploys Strimzi + Kafka 4.1.0 (3 brokers) and all 4 application components.

### Access the UIs

Add this line to `/etc/hosts` on **any machine on the LAN**:

```
192.168.1.22  producer.hamq.local  consumer.hamq.local  arbiter.hamq.local  controller.hamq.local
```

Then open in a browser:

| Service | URL | Default credentials |
|---------|-----|---------------------|
| Producer | http://producer.hamq.local | admin / admin |
| Consumer | http://consumer.hamq.local | admin / admin |
| Arbiter  | http://arbiter.hamq.local  | admin / admin |
| Controller | http://controller.hamq.local | admin / admin |

### Tear down

```bash
# Keep Ubuntu base image (fast re-provision)
sudo bash infra/teardown-cluster.sh

# Wipe everything including base image, SSH key, k3sup
sudo bash infra/teardown-cluster.sh --purge
```

### Network topology

```
LAN (192.168.1.0/24)
  │
  ├── cubecluster  192.168.1.22   ← host + single-node k3s (existing)
  │     │  Traefik :80 proxies *.hamq.local → 192.168.122.200
  │     │
  │     └── virbr0  192.168.122.1  (libvirt NAT bridge)
  │           │
  │           ├── k3s-cp   192.168.122.10   control-plane
  │           ├── k3s-w1   192.168.122.159  worker
  │           └── k3s-w2   192.168.122.18   worker
  │                 │
  │                 └── MetalLB → Traefik  192.168.122.200
  │                       routes producer/consumer/arbiter/controller
```
