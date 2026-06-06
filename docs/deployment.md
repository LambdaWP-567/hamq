# HAMq — Deployment Guide

---

## Contents

1. [Single-Cluster Deployment (6-node, recommended starting point)](#single-cluster-deployment)
2. [Multi-Cluster Deployment](#multi-cluster-deployment)
3. [TLS Certificate Configuration](#tls-certificate-configuration)
4. [Environment Variables Reference](#environment-variables-reference)
5. [Resource Sizing](#resource-sizing)
6. [Storage Configuration](#storage-configuration)
7. [Network Policies](#network-policies)
8. [Monitoring and Alerting](#monitoring-and-alerting)
9. [Upgrade Procedures](#upgrade-procedures)
10. [Troubleshooting](#troubleshooting)

---

## Single-Cluster Deployment

Deploy all HAMq components onto one Kubernetes cluster. Suitable for development, staging, and production environments where all nodes are in the same region. A 6-node cluster is the recommended minimum for HA: 3 nodes dedicated to Kafka brokers (one per node, enforced by pod anti-affinity) and 3 nodes available for application workloads.

### Prerequisites

| Tool | Minimum version | Install |
|------|----------------|---------|
| `kubectl` | v1.27+ | <https://kubernetes.io/docs/tasks/tools/> |
| `helm` | v3.12+ | <https://helm.sh/docs/intro/install/> |
| Kubernetes cluster | v1.27+ | k3s, k8s, EKS, GKE, AKS, … |
| GitHub PAT | read:packages scope | Required to pull images from GHCR |

Verify cluster access:

```bash
kubectl cluster-info
kubectl get nodes
```

Expected output for a 6-node cluster:
```
NAME        STATUS   ROLES                  AGE
node-cp-1   Ready    control-plane,master   ...
node-cp-2   Ready    control-plane,master   ...
node-cp-3   Ready    control-plane,master   ...
node-w-1    Ready    worker                 ...
node-w-2    Ready    worker                 ...
node-w-3    Ready    worker                 ...
```

### Step 1 — Clone the repository

```bash
git clone https://github.com/LambdaWP-567/hamq.git
cd hamq
```

### Step 2 — Create namespaces

```bash
kubectl create namespace kafka
kubectl create namespace hamq
```

### Step 3 — GHCR image pull secret

HAMq images are hosted on GitHub Container Registry (GHCR). Create a pull secret in both namespaces:

```bash
export GHCR_TOKEN=<your-github-pat>   # needs read:packages scope

for ns in kafka hamq; do
  kubectl create secret docker-registry ghcr-secret \
    --docker-server=ghcr.io \
    --docker-username=lambdawp-567 \
    --docker-password="${GHCR_TOKEN}" \
    -n "${ns}"
done
```

### Step 4 — Auth secrets for app components

Each component uses basic-auth (username / password). The defaults below match the `admin/admin` credentials in the UIs. **Change these for production.**

```bash
for component in producer consumer arbiter controller; do
  kubectl create secret generic "hamq-${component}-auth" \
    --from-literal=username=admin \
    --from-literal=password=admin \
    -n hamq
done
```

### Step 5 — Add the Strimzi Helm repository

```bash
helm repo add strimzi https://strimzi.io/charts/
helm repo update
```

### Step 6 — Deploy Kafka (3 brokers, one per node)

The kafka-cluster chart installs the Strimzi operator and the Kafka cluster in one step.

```bash
helm dependency update components/kafka-cluster/helm

helm upgrade --install kafka-cluster components/kafka-cluster/helm \
  -n kafka \
  --set global.namespace=kafka \
  --set kafka.replicas=3 \
  --set kafka.config.defaultReplicationFactor=3 \
  --set kafka.config.minInsyncReplicas=2 \
  --set kafka.config.offsetsTopicReplicationFactor=3 \
  --set kafka.config.transactionStateLogReplicationFactor=3 \
  --set kafka.config.transactionStateLogMinIsr=2 \
  --set kafka.storage.storageClass=local-path \
  --set kafka.storage.size=20Gi \
  --set kafka.podAntiAffinity=required \
  --set kafka.listeners.tls.enabled=false \
  --set kafka.listeners.external.enabled=false \
  --set topics.messages.replicas=3 \
  --set 'topics.messages.config.minInsyncReplicas=2' \
  --set topics.dlq.replicas=3 \
  --set certManager.enabled=false \
  --set monitoring.enabled=false \
  --timeout 10m \
  --wait=false
```

> **StorageClass:** Replace `local-path` with the StorageClass available in your cluster (`kubectl get storageclass`). For cloud clusters use `gp3` (AWS), `standard-rwo` (GKE), or `managed-premium` (Azure).

Wait for all 3 brokers to become Ready:

```bash
kubectl rollout status statefulset -n kafka --timeout=10m
kubectl get pods -n kafka -o wide
```

Verify one broker per node (anti-affinity):
```
NAME                         READY   NODE
hamq-kafka-dual-role-0       1/1     node-w-1
hamq-kafka-dual-role-1       1/1     node-w-2
hamq-kafka-dual-role-2       1/1     node-w-3
```

### Step 7 — Verify Kafka topics

```bash
kubectl get kafkatopic -n kafka
```

Expected:
```
NAME            PARTITIONS   REPLICAS
hamq-dlq        3            3
hamq-messages   12           3
```

### Step 8 — Deploy application components

All app charts share the same Helm repository root. Adjust `ingress.host` values to match your cluster's DNS / Ingress IP.

> **Tip:** Replace `hamq.example.com` below with your actual domain or nip.io address (e.g. `producer.192-168-1-22.nip.io`).

**Producer:**

```bash
helm upgrade --install hamq-producer components/producer/helm \
  -n hamq \
  --set kafka.bootstrapServers="hamq-kafka-kafka-bootstrap.kafka.svc.cluster.local:9092" \
  --set kafka.tlsEnabled=false \
  --set ingress.enabled=true \
  --set ingress.className=traefik \
  --set ingress.host=producer.hamq.example.com \
  --set persistence.storageClass=local-path \
  --set imagePullSecrets[0].name=ghcr-secret \
  --set monitoring.enabled=false \
  --wait --timeout 3m
```

**Consumer:**

```bash
helm upgrade --install hamq-consumer components/consumer/helm \
  -n hamq \
  --set kafka.bootstrapServers="hamq-kafka-kafka-bootstrap.kafka.svc.cluster.local:9092" \
  --set kafka.tlsEnabled=false \
  --set consumer.autostart=true \
  --set ingress.enabled=true \
  --set ingress.className=traefik \
  --set ingress.host=consumer.hamq.example.com \
  --set persistence.storageClass=local-path \
  --set imagePullSecrets[0].name=ghcr-secret \
  --set monitoring.enabled=false \
  --wait --timeout 3m
```

**Arbiter:**

```bash
helm upgrade --install hamq-arbiter components/arbiter/helm \
  -n hamq \
  --set arbiter.producerApiUrl="http://hamq-producer.hamq.svc.cluster.local:8000" \
  --set arbiter.consumerApiUrl="http://hamq-consumer.hamq.svc.cluster.local:8001" \
  --set ingress.enabled=true \
  --set ingress.className=traefik \
  --set ingress.host=arbiter.hamq.example.com \
  --set imagePullSecrets[0].name=ghcr-secret \
  --wait --timeout 3m
```

**Controller:**

```bash
helm upgrade --install hamq-controller components/controller/helm \
  -n hamq \
  --set controller.kafkaNamespace=kafka \
  --set controller.kafkaClusterName=hamq-kafka \
  --set ingress.enabled=true \
  --set ingress.className=traefik \
  --set ingress.host=controller.hamq.example.com \
  --set imagePullSecrets[0].name=ghcr-secret \
  --wait --timeout 3m
```

### Step 9 — Verify the deployment

```bash
# All pods should be Running/Ready
kubectl get pods -n kafka
kubectl get pods -n hamq

# Ingress routes
kubectl get ingress -n hamq

# Test producer health
curl http://producer.hamq.example.com/api/health

# Test consumer health
curl http://consumer.hamq.example.com/api/health
```

### Step 10 — Open the UIs

| Component | Default URL | Default credentials |
|-----------|-------------|-------------------|
| Producer | `http://producer.hamq.example.com` | admin / admin |
| Consumer | `http://consumer.hamq.example.com` | admin / admin |
| Arbiter | `http://arbiter.hamq.example.com` | admin / admin |
| Controller | `http://controller.hamq.example.com` | admin / admin |

### Convenience: values override file

Instead of passing many `--set` flags, create a `values-production.yaml` file:

```yaml
# infra/values/kafka-prod.yaml
kafka:
  replicas: 3
  config:
    defaultReplicationFactor: 3
    minInsyncReplicas: 2
    offsetsTopicReplicationFactor: 3
    transactionStateLogReplicationFactor: 3
    transactionStateLogMinIsr: 2
  storage:
    storageClass: local-path   # change to your StorageClass
    size: 20Gi
    deleteClaim: false         # keep data on cluster delete
  podAntiAffinity: required
  listeners:
    tls:
      enabled: false
    external:
      enabled: false
topics:
  messages:
    replicas: 3
    config:
      minInsyncReplicas: "2"
  dlq:
    replicas: 3
certManager:
  enabled: false
monitoring:
  enabled: false
```

Then deploy with:

```bash
helm upgrade --install kafka-cluster components/kafka-cluster/helm \
  -n kafka \
  --set global.namespace=kafka \
  -f infra/values/kafka-prod.yaml \
  --wait=false --timeout 10m
```

### Recommended 6-node topology

```
┌──────────────────────────────────────────────────────────────┐
│  Node 1 (worker)     │  hamq-kafka-dual-role-0               │
│  Node 2 (worker)     │  hamq-kafka-dual-role-1               │
│  Node 3 (worker)     │  hamq-kafka-dual-role-2               │
│  Node 4 (worker)     │  hamq-producer, hamq-arbiter          │
│  Node 5 (worker)     │  hamq-consumer                        │
│  Node 6 (control-plane) │  hamq-controller, Strimzi operator  │
└──────────────────────────────────────────────────────────────┘
```

Kafka brokers are spread by the `podAntiAffinity: required` rule. App workloads schedule wherever resources are available. If you want to pin app components to specific nodes, use node labels and `nodeSelector` in each app chart's values:

```bash
# Label nodes for Kafka
kubectl label node node-w-1 node-w-2 node-w-3 hamq-role=kafka

# Label remaining nodes for app workloads
kubectl label node node-w-4 node-w-5 node-w-6 hamq-role=app
```

Then add to each app chart:
```yaml
nodeSelector:
  hamq-role: app
```

### HA failure behaviour

| Failure | Impact | Recovery |
|---------|--------|----------|
| One Kafka broker pod killed | 2/3 ISRs remain, zero message loss | Kubernetes restarts pod automatically |
| One Kafka node lost | Same as above | Pod reschedules to surviving node when it rejoins |
| Producer pod killed | ~30 s gap; SQLite buffer replays queued messages on restart | Kubernetes restarts pod |
| Consumer pod killed | Resumes from last committed offset; no message loss | Kubernetes restarts pod |
| Controller / Arbiter pod killed | UI unavailable; Kafka message flow unaffected | Kubernetes restarts pod |

---

## Multi-Cluster Deployment

For maximum isolation, deploy each component on its own Kubernetes cluster:

```
Cluster A  —  Kafka (Strimzi, KRaft, 3 nodes)
Cluster B  —  Producer
Cluster C  —  Consumer
Cluster D  —  Arbiter
Cluster E  —  Controller
```

For non-production you can collapse all components into a single cluster using separate namespaces. Set `global.namespace` per component and adjust `hostnames`/`bootstrapServers` to point at in-cluster Service DNS names.

### Cross-cluster networking

The only hard network requirement between clusters is that **Cluster B (Producer) and Cluster C (Consumer)** must reach **Cluster A's** external Kafka listener on port `9094`.

All other cross-cluster communication (Arbiter → Producer/Consumer, Controller → all) uses standard HTTP REST APIs.

```
Producer  (Cluster B)  →  port 9094  →  Kafka (Cluster A)
Consumer  (Cluster C)  →  port 9094  →  Kafka (Cluster A)
Arbiter   (Cluster D)  →  port 8000  →  Producer API (Cluster B)
Arbiter   (Cluster D)  →  port 8001  →  Consumer API (Cluster C)
Controller(Cluster E)  →  K8s API    →  Clusters A–D
```

### Required DNS entries

Create stable DNS records (A or CNAME) for all LoadBalancer endpoints. Using IPs directly is fragile because cloud LB IPs can change on cluster recreation.

| DNS name (example) | Target | Port |
|--------------------|--------|------|
| `kafka.hamq.example.com` | Cluster A LB IP | 9094 |
| `producer.hamq.example.com` | Cluster B LB IP | 8000 |
| `consumer.hamq.example.com` | Cluster C LB IP | 8001 |
| `arbiter.hamq.example.com` | Cluster D LB IP | 8002 |
| `controller.hamq.example.com` | Cluster E LB IP | 8003 |

---

## TLS Certificate Configuration

### Overview

HAMq uses a two-layer TLS model:

1. **Strimzi-managed PKI** — Strimzi creates its own CA (`kafka-cluster-ca`, `kafka-clients-ca`) and issues broker and client certificates automatically. No manual cert management is required for broker-to-broker and broker-to-client communication.

2. **cert-manager ClusterIssuer** — used by the HAMq Helm chart for any additional Ingress/Gateway TLS and inter-component mTLS. The default issuer is `selfsigned-issuer`.

### Production PKI recommendations

For production, replace the self-signed issuer with one backed by your PKI:

#### Option A: Internal CA via cert-manager

```bash
kubectl apply -f - <<'EOF'
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: hamq-root-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: hamq-root-ca
  secretName: hamq-root-ca-secret
  privateKey:
    algorithm: ECDSA
    size: 256
  issuerRef:
    name: selfsigned-issuer
    kind: ClusterIssuer
    group: cert-manager.io
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: hamq-ca-issuer
spec:
  ca:
    secretName: hamq-root-ca-secret
EOF
```

Then set in `values.yaml`:

```yaml
certManager:
  issuerName: hamq-ca-issuer
  issuerKind: ClusterIssuer
```

#### Option B: HashiCorp Vault PKI

```yaml
certManager:
  issuerName: vault-issuer
  issuerKind: ClusterIssuer
```

Follow the cert-manager Vault documentation to configure the Vault issuer.

### Certificate rotation

Strimzi automates broker and client certificate renewal. The default renewal window is 30 days before expiry. Monitor certificate expiry via:

```bash
kubectl -n kafka get secret hamq-kafka-cluster-ca-cert \
  -o jsonpath='{.data.ca\.crt}' | base64 -d | \
  openssl x509 -noout -enddate
```

### Distributing client certificates to application clusters

After the Kafka cluster is deployed, Strimzi creates Secrets for each KafkaUser. Use the following pattern to copy them to application clusters:

```bash
#!/usr/bin/env bash
set -euo pipefail

KAFKA_CTX=kafka-cluster
TARGET_CTX=$1       # e.g. producer-cluster
TARGET_NS=hamq
SECRET_NAME=$2      # e.g. hamq-producer

kubectl --context "${KAFKA_CTX}" -n kafka \
  get secret "${SECRET_NAME}" -o json | \
  jq 'del(.metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp, .metadata.annotations, .metadata.ownerReferences)' | \
  kubectl --context "${TARGET_CTX}" -n "${TARGET_NS}" apply -f -

# Also copy the cluster CA cert
kubectl --context "${KAFKA_CTX}" -n kafka \
  get secret hamq-kafka-cluster-ca-cert -o json | \
  jq 'del(.metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp, .metadata.annotations, .metadata.ownerReferences)' | \
  kubectl --context "${TARGET_CTX}" -n "${TARGET_NS}" apply -f -
```

---

## Environment Variables Reference

The following environment variables control each HAMq component. They are injected via Helm chart values into container environment specs.

### Kafka Cluster (broker JVM / config)

These are set via `values.yaml` and rendered into the Strimzi `Kafka` custom resource; they are not pod environment variables.

| Helm value | Kafka config key | Default | Description |
|---|---|---|---|
| `kafka.config.defaultReplicationFactor` | `default.replication.factor` | `3` | Default RF for auto-created topics |
| `kafka.config.minInsyncReplicas` | `min.insync.replicas` | `2` | Minimum ISR count for write acknowledgment |
| `kafka.config.offsetsTopicReplicationFactor` | `offsets.topic.replication.factor` | `3` | RF of `__consumer_offsets` internal topic |
| `kafka.config.logRetentionHours` | `log.retention.hours` | `168` | Log retention (7 days) |
| `kafka.config.autoCreateTopicsEnable` | `auto.create.topics.enable` | `false` | Topics must be pre-created via KafkaTopic resources |
| `kafka.jvmOptions.xmx` | JVM `-Xmx` | `1536m` | Max JVM heap per broker |

### Producer

| Variable | Helm value | Default | Description |
|---|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka.bootstrapServers` | *(required)* | Comma-separated Kafka bootstrap host:port |
| `KAFKA_TOPIC` | `kafka.topic` | `hamq-messages` | Topic to publish to |
| `PRODUCER_FREQUENCY_HZ` | `producer.frequencyHz` | `10` | Initial publish frequency in messages/s |
| `PRODUCER_BUFFER_MAX_MESSAGES` | `producer.bufferMaxMessages` | `1000000` | SQLite buffer size limit |
| `PRODUCER_BUFFER_DB_PATH` | `producer.bufferDbPath` | `/data/buffer.db` | Path to SQLite buffer file (PVC) |
| `PRODUCER_RETRY_INTERVAL_SECONDS` | `producer.retryIntervalSeconds` | `5` | Seconds between drain retries when Kafka is unreachable |
| `API_PORT` | `api.port` | `8000` | FastAPI server port |
| `LOG_LEVEL` | `logLevel` | `info` | Logging level |

### Consumer

| Variable | Helm value | Default | Description |
|---|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka.bootstrapServers` | *(required)* | Kafka bootstrap host:port |
| `KAFKA_TOPIC` | `kafka.topic` | `hamq-messages` | Topic to consume from |
| `KAFKA_GROUP_ID` | `consumer.groupId` | `hamq-consumer-group` | Consumer group identifier |
| `CONSUMER_DB_PATH` | `consumer.dbPath` | `/data/consumer.db` | SQLite path for persisting received messages |
| `API_PORT` | `api.port` | `8001` | FastAPI server port |
| `LOG_LEVEL` | `logLevel` | `info` | Logging level |

### Arbiter

| Variable | Helm value | Default | Description |
|---|---|---|---|
| `PRODUCER_API_URL` | `arbiter.producerApiUrl` | *(required)* | Base URL of the Producer REST API |
| `CONSUMER_API_URL` | `arbiter.consumerApiUrl` | *(required)* | Base URL of the Consumer REST API |
| `ARBITER_POLL_INTERVAL_SECONDS` | `arbiter.pollIntervalSeconds` | `10` | How often to poll Producer and Consumer APIs |
| `API_PORT` | `api.port` | `8002` | FastAPI server port |
| `LOG_LEVEL` | `logLevel` | `info` | Logging level |

### Controller

| Variable | Helm value | Default | Description |
|---|---|---|---|
| `KAFKA_NAMESPACE` | `controller.kafkaNamespace` | `kafka` | Kubernetes namespace where Kafka runs |
| `KAFKA_CLUSTER_NAME` | `controller.kafkaClusterName` | `hamq-kafka` | Strimzi Kafka resource name |
| `API_PORT` | `api.port` | `8003` | FastAPI server port |
| `LOG_LEVEL` | `logLevel` | `info` | Logging level |

---

## Resource Sizing

### Kafka brokers

The default resource values are suitable for moderate workloads (< 10 000 msg/s). For higher throughput:

```yaml
kafka:
  resources:
    requests:
      memory: 4Gi
      cpu: "1"
    limits:
      memory: 8Gi
      cpu: "4"
  jvmOptions:
    xmx: 3072m   # ~60-75% of memory limit
    xms: 3072m   # equal to xmx to avoid GC pauses
  storage:
    size: 100Gi  # throughput × retention period
```

### Application pods

| Component | CPU request | Memory request | CPU limit | Memory limit |
|-----------|-------------|----------------|-----------|--------------|
| Producer | 200m | 256Mi | 1000m | 512Mi |
| Consumer | 200m | 256Mi | 1000m | 512Mi |
| Arbiter | 100m | 128Mi | 500m | 256Mi |
| Controller | 100m | 128Mi | 500m | 256Mi |

---

## Storage Configuration

Kafka brokers require persistent storage. The `storageClass` value must match an available StorageClass in your cluster.

```bash
kubectl get storageclass
```

| Cloud | Recommended StorageClass | Notes |
|-------|--------------------------|-------|
| AWS EKS | `gp3` | Provision with `allowVolumeExpansion: true` |
| GKE | `standard-rwo` | Regional disk for HA |
| Azure AKS | `managed-premium` | Premium SSD |
| On-premises / k3s | `local-path` | Per-node; Kafka protocol-level replication provides HA |

> Kafka already replicates data across brokers (RF=3). Using a replicated block storage (e.g., Ceph) adds a second layer of redundancy but consumes more storage. For most deployments standard block storage per node is sufficient.

---

## Network Policies

Apply the following Kubernetes NetworkPolicies to restrict traffic to Kafka:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: kafka-ingress
  namespace: kafka
spec:
  podSelector:
    matchLabels:
      strimzi.io/cluster: hamq-kafka
  policyTypes:
    - Ingress
  ingress:
    - ports:
        - port: 9092   # plain (in-cluster only)
          protocol: TCP
        - port: 9093   # TLS (in-cluster mTLS)
          protocol: TCP
        - port: 9094   # external (LoadBalancer)
          protocol: TCP
```

---

## Monitoring and Alerting

### Prometheus scraping

The HAMq Kafka chart deploys a `ServiceMonitor` (if `monitoring.serviceMonitor.enabled: true`) that configures Prometheus to scrape the JMX Prometheus Exporter on port `9404` every 30 seconds.

### Key Kafka metrics to alert on

| Metric | Alert threshold | Meaning |
|--------|----------------|---------|
| `kafka_server_replicamanager_underreplicatedpartitions` | > 0 for > 60s | Partition has fewer replicas than RF |
| `kafka_server_replicamanager_offlinepartitionscount` | > 0 | Partition has no leader |
| `kafka_controller_kafkacontroller_activecontrollercount` | != 1 | No active controller or split-brain |
| `hamq_producer_buffer_size` | > 10000 | Producer buffer growing; Kafka may be unreachable |
| `hamq_consumer_lag_messages` | > 1000 | Consumer falling behind |

---

## Upgrade Procedures

### Upgrading the Kafka version

1. Update `kafka.version` in your values file.
2. Check the [Strimzi upgrade guide](https://strimzi.io/docs/operators/latest/deploying#assembly-upgrade-str) for inter-version protocol changes.
3. Run `helm upgrade` — Strimzi performs a rolling restart of brokers.

```bash
helm upgrade kafka-cluster components/kafka-cluster/helm \
  -n kafka --set kafka.version=4.2.0 --wait --timeout 15m
```

### Rolling application component updates

Each app chart uses a `RollingUpdate` strategy. Update the image tag:

```bash
helm upgrade hamq-producer components/producer/helm \
  -n hamq --set image.backend.tag=v1.2.0 --wait --timeout 5m
```

---

## Troubleshooting

### Kafka pods are stuck in `Pending`

```bash
kubectl describe pod <pod-name> -n kafka | grep -A 20 Events
kubectl get pvc -n kafka
kubectl get storageclass
```

Common cause: `kafka.storage.storageClass` does not exist in the cluster. Set it to a StorageClass returned by `kubectl get storageclass`.

If using `podAntiAffinity: required` and a broker can't schedule, the error will be `0/N nodes are available: N node(s) didn't match pod anti-affinity rules`. Either add more nodes or change to `podAntiAffinity: preferred`.

### Kafka cluster not reaching `Ready` state

```bash
kubectl logs -n kafka -l name=strimzi-cluster-operator --tail=100
kubectl get kafka hamq-kafka -n kafka -o jsonpath='{.status.conditions}' | jq .
```

### Producer cannot connect to Kafka

```bash
# Verify bootstrap address is reachable from the producer pod
kubectl exec -n hamq deploy/hamq-producer -- \
  nc -zv hamq-kafka-kafka-bootstrap.kafka.svc.cluster.local 9092

# Check environment variables
kubectl exec -n hamq deploy/hamq-producer -- env | grep KAFKA
```

Common causes:
- `KAFKA_BOOTSTRAP_SERVERS` uses the wrong port (9092 = plain, 9093 = TLS; match `kafka.tlsEnabled`).
- The `kafka` namespace is not reachable from the `hamq` namespace (check NetworkPolicy).

### Consumer group lag is growing

```bash
kubectl logs -n hamq deploy/hamq-consumer --tail=100

# Check consumer group offsets
kubectl exec -n kafka \
  $(kubectl get pod -n kafka -l strimzi.io/cluster=hamq-kafka -o name | head -1) -- \
  bin/kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 \
    --describe --group hamq-consumer-group
```

### Viewing all Prometheus metrics

```bash
kubectl -n kafka port-forward \
  $(kubectl get pod -n kafka -l strimzi.io/name=hamq-kafka-kafka -o name | head -1) \
  9404:9404

curl http://localhost:9404/metrics | grep kafka_server
```
