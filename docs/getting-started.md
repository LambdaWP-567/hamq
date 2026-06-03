# HAMq — Getting Started

This guide walks you from a fresh environment to a running HAMq system with all five components operational.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation Order](#installation-order)
- [Step 1 — Prepare Your Clusters](#step-1--prepare-your-clusters)
- [Step 2 — Install cert-manager](#step-2--install-cert-manager)
- [Step 3 — Deploy the Kafka Cluster](#step-3--deploy-the-kafka-cluster)
- [Step 4 — Deploy Application Components](#step-4--deploy-application-components)
- [Step 5 — Verify the System](#step-5--verify-the-system)
- [Configuration Options](#configuration-options)
- [Basic Usage](#basic-usage)
- [Next Steps](#next-steps)

---

## Prerequisites

### Required CLI tools

| Tool | Minimum version | Install guide |
|------|----------------|---------------|
| `kubectl` | 1.28 | https://kubernetes.io/docs/tasks/tools/ |
| `helm` | 3.12 | https://helm.sh/docs/intro/install/ |
| `jq` | 1.6 | https://jqlang.github.io/jq/download/ |

### Required Kubernetes infrastructure

- **5 Kubernetes clusters** (or 1 cluster with 5 namespaces for a local test).  
  Recommended minimum node specs per cluster:

  | Cluster | Role | Min nodes | Node size |
  |---------|------|-----------|-----------|
  | A | Kafka | 3 | 4 vCPU / 8 GB RAM |
  | B | Producer | 1 | 2 vCPU / 2 GB RAM |
  | C | Consumer | 1 | 2 vCPU / 2 GB RAM |
  | D | Arbiter | 1 | 1 vCPU / 1 GB RAM |
  | E | Controller | 1 | 1 vCPU / 1 GB RAM |

- **Persistent volume provisioner** in Cluster A (e.g., default `standard` StorageClass or cloud-managed CSI driver).
- **LoadBalancer support** in Cluster A for the external Kafka listener (port 9094).

### Helm repositories

Add the following Helm repos before proceeding:

```bash
helm repo add strimzi   https://strimzi.io/charts/
helm repo add jetstack  https://charts.jetstack.io
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

---

## Installation Order

Components **must** be installed in the following order because each depends on resources created by the previous step:

```
1. cert-manager  (Cluster A)
2. Strimzi Kafka Operator  (Cluster A)  — installed automatically by HAMq Helm chart if strimzi.install=true
3. Kafka Cluster  (Cluster A)
4. Producer  (Cluster B)  — needs Kafka bootstrap address and client certificates
5. Consumer  (Cluster C)  — needs Kafka bootstrap address and client certificates
6. Arbiter  (Cluster D)  — needs Producer and Consumer API addresses
7. Controller  (Cluster E)  — needs all other API addresses + kubeconfig/RBAC
```

---

## Step 1 — Prepare Your Clusters

Set your kubeconfig contexts for each cluster. The examples below use context names that match the HAMq conventions; adjust to your actual context names.

```bash
# List available contexts
kubectl config get-contexts

# Rename contexts for convenience (optional)
kubectl config rename-context <your-kafka-context>      kafka-cluster
kubectl config rename-context <your-producer-context>   producer-cluster
kubectl config rename-context <your-consumer-context>   consumer-cluster
kubectl config rename-context <your-arbiter-context>    arbiter-cluster
kubectl config rename-context <your-controller-context> controller-cluster
```

Create the `kafka` namespace in Cluster A:

```bash
kubectl --context kafka-cluster create namespace kafka
```

---

## Step 2 — Install cert-manager

cert-manager is required in Cluster A to bootstrap the TLS PKI. It manages the ClusterIssuer used by Strimzi and by the Helm chart's optional additional certificates.

```bash
helm install cert-manager jetstack/cert-manager \
  --kube-context kafka-cluster \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true \
  --version v1.14.4

# Wait for cert-manager webhooks to become ready
kubectl --context kafka-cluster rollout status deployment/cert-manager \
  -n cert-manager --timeout=120s
kubectl --context kafka-cluster rollout status deployment/cert-manager-webhook \
  -n cert-manager --timeout=120s
```

Create the self-signed ClusterIssuer that the HAMq chart references:

```bash
kubectl --context kafka-cluster apply -f - <<'EOF'
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: selfsigned-issuer
spec:
  selfSigned: {}
EOF
```

> **Production note:** For production deployments replace `selfsigned-issuer` with an issuer backed by your internal PKI (e.g., an ACME issuer or a Vault PKI issuer). Update `certManager.issuerName` and `certManager.issuerKind` in `values.yaml` accordingly.

---

## Step 3 — Deploy the Kafka Cluster

The `hamq-kafka-cluster` Helm chart installs the Strimzi operator (if not already present) and all Kafka resources.

```bash
# Add and update the Strimzi Helm repo (needed even if strimzi.install=true,
# because the chart downloads the dependency)
helm repo add strimzi https://strimzi.io/charts/
helm repo update

# Update Helm chart dependencies (downloads Strimzi sub-chart)
helm dependency update components/kafka-cluster/helm

# Install — the chart creates the Strimzi operator AND the Kafka cluster
helm install hamq-kafka components/kafka-cluster/helm \
  --kube-context kafka-cluster \
  --namespace kafka \
  --create-namespace \
  --wait \
  --timeout 10m
```

### Wait for Kafka to become ready

```bash
# Watch KafkaNodePool readiness (all 3 replicas must be Ready)
kubectl --context kafka-cluster -n kafka get kafkanodepool dual-role -w

# Watch Kafka resource — look for "Ready" condition
kubectl --context kafka-cluster -n kafka get kafka hamq-kafka -w

# List pods; all 3 should be Running
kubectl --context kafka-cluster -n kafka get pods -l strimzi.io/cluster=hamq-kafka
```

Expected output once ready:

```
NAME                          READY   STATUS    RESTARTS   AGE
hamq-kafka-dual-role-0        1/1     Running   0          4m
hamq-kafka-dual-role-1        1/1     Running   0          4m
hamq-kafka-dual-role-2        1/1     Running   0          4m
hamq-kafka-entity-operator-*  2/2     Running   0          2m
```

### Retrieve the external bootstrap address

```bash
kubectl --context kafka-cluster -n kafka \
  get service hamq-kafka-kafka-external-bootstrap \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

Note this IP (or hostname); you will use it as `KAFKA_BOOTSTRAP_SERVERS` for the Producer and Consumer.

---

## Step 4 — Deploy Application Components

### Retrieve client certificates

Strimzi creates a Kubernetes Secret for each `KafkaUser`. Copy these secrets to the application clusters:

```bash
# Export secrets from Cluster A
kubectl --context kafka-cluster -n kafka \
  get secret hamq-producer -o yaml > /tmp/hamq-producer-secret.yaml
kubectl --context kafka-cluster -n kafka \
  get secret hamq-consumer -o yaml > /tmp/hamq-consumer-secret.yaml
kubectl --context kafka-cluster -n kafka \
  get secret hamq-kafka-cluster-ca-cert -o yaml > /tmp/kafka-ca-cert-secret.yaml
```

Import secrets to Cluster B (Producer):

```bash
kubectl --context producer-cluster create namespace hamq || true
kubectl --context producer-cluster -n hamq apply -f /tmp/hamq-producer-secret.yaml
kubectl --context producer-cluster -n hamq apply -f /tmp/kafka-ca-cert-secret.yaml
```

Import secrets to Cluster C (Consumer):

```bash
kubectl --context consumer-cluster create namespace hamq || true
kubectl --context consumer-cluster -n hamq apply -f /tmp/hamq-consumer-secret.yaml
kubectl --context consumer-cluster -n hamq apply -f /tmp/kafka-ca-cert-secret.yaml
```

### Deploy the Producer (Cluster B)

```bash
KAFKA_BOOTSTRAP=<external-bootstrap-ip>:9094   # from Step 3

helm install hamq-producer components/producer/helm \
  --kube-context producer-cluster \
  --namespace hamq \
  --set kafka.bootstrapServers="${KAFKA_BOOTSTRAP}" \
  --set kafka.caSecretName=hamq-kafka-cluster-ca-cert \
  --set kafka.userSecretName=hamq-producer \
  --wait --timeout 5m
```

### Deploy the Consumer (Cluster C)

```bash
helm install hamq-consumer components/consumer/helm \
  --kube-context consumer-cluster \
  --namespace hamq \
  --set kafka.bootstrapServers="${KAFKA_BOOTSTRAP}" \
  --set kafka.caSecretName=hamq-kafka-cluster-ca-cert \
  --set kafka.userSecretName=hamq-consumer \
  --wait --timeout 5m
```

### Deploy the Arbiter (Cluster D)

```bash
PRODUCER_API=http://<producer-loadbalancer-ip>:8000
CONSUMER_API=http://<consumer-loadbalancer-ip>:8001

helm install hamq-arbiter components/arbiter/helm \
  --kube-context arbiter-cluster \
  --namespace hamq \
  --create-namespace \
  --set arbiter.producerApiUrl="${PRODUCER_API}" \
  --set arbiter.consumerApiUrl="${CONSUMER_API}" \
  --wait --timeout 5m
```

### Deploy the Controller (Cluster E)

```bash
helm install hamq-controller components/controller/helm \
  --kube-context controller-cluster \
  --namespace hamq \
  --create-namespace \
  --wait --timeout 5m
```

---

## Step 5 — Verify the System

### Health checks

```bash
# Producer API
curl http://<producer-ip>:8000/health

# Consumer API
curl http://<consumer-ip>:8001/health

# Arbiter API
curl http://<arbiter-ip>:8002/health
```

All should return `{"status": "ok"}`.

### Send a test message burst

```bash
# Start producing at 10 msg/s
curl -X POST http://<producer-ip>:8000/api/v1/producer/start \
  -H 'Content-Type: application/json' \
  -d '{"frequency_hz": 10}'

# Wait 10 seconds, then check stats
sleep 10

curl http://<producer-ip>:8000/api/v1/producer/stats | jq .
curl http://<consumer-ip>:8001/api/v1/consumer/stats | jq .
curl http://<arbiter-ip>:8002/api/v1/report | jq .
```

Expected: `loss_rate` near `0.0`, `duplicate_rate` near `0.0`.

### Open the web UIs

| Component | URL |
|-----------|-----|
| Producer UI | `http://<producer-ip>:3000` |
| Consumer UI | `http://<consumer-ip>:3001` |
| Arbiter UI | `http://<arbiter-ip>:3002` |
| Controller UI | `http://<controller-ip>:3003` |

---

## Configuration Options

All components accept configuration via Helm values. The most commonly overridden values are listed below. See each component's `values.yaml` and `docs/components/` for the full reference.

### Kafka cluster (`components/kafka-cluster/helm/values.yaml`)

| Key | Default | Description |
|-----|---------|-------------|
| `kafka.replicas` | `3` | Number of Kafka broker/controller nodes |
| `kafka.storage.size` | `10Gi` | Persistent volume size per broker |
| `kafka.storage.storageClass` | `standard` | StorageClass for broker PVCs |
| `kafka.config.minInsyncReplicas` | `2` | min.insync.replicas broker config |
| `kafka.listeners.external.enabled` | `true` | Enable external LoadBalancer listener |
| `monitoring.enabled` | `true` | Enable Prometheus metrics |
| `strimzi.install` | `true` | Install Strimzi operator as chart dependency |

### Producer (`components/producer/helm/values.yaml`)

| Key | Default | Description |
|-----|---------|-------------|
| `kafka.bootstrapServers` | `""` | Kafka bootstrap address (required) |
| `producer.frequencyHz` | `10` | Default message publish frequency |
| `producer.bufferMaxMessages` | `1000000` | SQLite buffer size limit |
| `producer.retryIntervalSeconds` | `5` | Retry loop interval |

### Consumer (`components/consumer/helm/values.yaml`)

| Key | Default | Description |
|-----|---------|-------------|
| `kafka.bootstrapServers` | `""` | Kafka bootstrap address (required) |
| `consumer.groupId` | `hamq-consumer-group` | Kafka consumer group ID |
| `consumer.autoCommitIntervalMs` | `5000` | Auto-commit interval |

---

## Basic Usage

### Start / stop message production

```bash
# Start at 100 msg/s
curl -X POST http://<producer-ip>:8000/api/v1/producer/start \
  -H 'Content-Type: application/json' \
  -d '{"frequency_hz": 100}'

# Change frequency on the fly
curl -X PATCH http://<producer-ip>:8000/api/v1/producer/frequency \
  -H 'Content-Type: application/json' \
  -d '{"frequency_hz": 500}'

# Stop
curl -X POST http://<producer-ip>:8000/api/v1/producer/stop
```

### Get a loss report

```bash
curl http://<arbiter-ip>:8002/api/v1/report | jq '{
  loss_rate: .loss_rate,
  duplicate_rate: .duplicate_rate,
  p99_latency_ms: .latency_p99_ms,
  total_sent: .total_sent,
  total_received: .total_received
}'
```

### Trigger a chaos experiment

```bash
# Delete one broker pod (simulates a broker crash)
curl -X POST http://<controller-ip>:8003/api/v1/chaos/broker-restart \
  -H 'Content-Type: application/json' \
  -d '{"broker_index": 0, "delay_seconds": 0}'
```

---

## Next Steps

- Read the full [Architecture guide](architecture.md) to understand durability guarantees and failure scenarios.
- Review the [Deployment guide](deployment.md) for production hardening, multi-cluster networking, and TLS configuration.
- Explore individual component docs in [`docs/components/`](components/).
- Set up Prometheus + Grafana monitoring using the bundled `ServiceMonitor` and dashboard resources.
