# HAMq — Production Deployment Guide

This guide covers multi-cluster production deployment, TLS certificate configuration, environment variable reference, and troubleshooting.

---

## Table of Contents

- [Multi-Cluster Setup](#multi-cluster-setup)
- [TLS Certificate Configuration](#tls-certificate-configuration)
- [Environment Variables Reference](#environment-variables-reference)
- [Resource Sizing](#resource-sizing)
- [Storage Configuration](#storage-configuration)
- [Network Policies](#network-policies)
- [Monitoring and Alerting](#monitoring-and-alerting)
- [Upgrade Procedures](#upgrade-procedures)
- [Troubleshooting](#troubleshooting)

---

## Multi-Cluster Setup

### Cluster topology

HAMq is designed for a five-cluster topology. Each cluster has a dedicated role:

```
Cluster A  —  Kafka (Strimzi, KRaft, 3 nodes)
Cluster B  —  Producer
Cluster C  —  Consumer
Cluster D  —  Arbiter
Cluster E  —  Controller
```

For non-production environments you can collapse all components into a single cluster using separate namespaces. Set `global.namespace` per component and adjust `hostnames`/`bootstrapServers` to point at in-cluster Service DNS names.

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
# Create a CA certificate and a ClusterIssuer that uses it
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
| `kafka.config.defaultReplicationFactor` | `default.replication.factor` | `3` | Default RF for auto-created topics (note: `autoCreateTopicsEnable` is `false`) |
| `kafka.config.minInsyncReplicas` | `min.insync.replicas` | `2` | Minimum ISR count for write acknowledgment |
| `kafka.config.offsetsTopicReplicationFactor` | `offsets.topic.replication.factor` | `3` | RF of `__consumer_offsets` internal topic |
| `kafka.config.logRetentionHours` | `log.retention.hours` | `168` | Log retention (7 days) |
| `kafka.config.autoCreateTopicsEnable` | `auto.create.topics.enable` | `false` | Topics must be pre-created via KafkaTopic resources |
| `kafka.jvmOptions.xmx` | JVM `-Xmx` | `1536m` | Max JVM heap per broker |

### Producer (Cluster B)

| Variable | Helm value | Default | Description |
|---|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka.bootstrapServers` | *(required)* | Comma-separated Kafka bootstrap host:port |
| `KAFKA_TOPIC` | `kafka.topic` | `hamq-messages` | Topic to publish to |
| `KAFKA_CA_CERT` | *(mounted from secret)* | `/certs/ca.crt` | Path to cluster CA certificate |
| `KAFKA_CLIENT_CERT` | *(mounted from secret)* | `/certs/user.crt` | Path to client TLS certificate |
| `KAFKA_CLIENT_KEY` | *(mounted from secret)* | `/certs/user.key` | Path to client TLS private key |
| `PRODUCER_FREQUENCY_HZ` | `producer.frequencyHz` | `10` | Initial publish frequency in messages per second |
| `PRODUCER_BUFFER_MAX_MESSAGES` | `producer.bufferMaxMessages` | `1000000` | SQLite buffer size limit; back-pressure applied when reached |
| `PRODUCER_BUFFER_DB_PATH` | `producer.bufferDbPath` | `/data/buffer.db` | Path to SQLite buffer file (should be on a PVC) |
| `PRODUCER_RETRY_INTERVAL_SECONDS` | `producer.retryIntervalSeconds` | `5` | Seconds between drain loop iterations when Kafka is unreachable |
| `PRODUCER_DNS_REFRESH_SECONDS` | `producer.dnsRefreshSeconds` | `60` | How often to re-resolve the bootstrap hostname |
| `PRODUCER_ID` | *(derived from Pod name)* | `$(POD_NAME)` | Unique producer identifier included in every message |
| `API_PORT` | `api.port` | `8000` | FastAPI server port |
| `LOG_LEVEL` | `logLevel` | `info` | Logging level: `debug`, `info`, `warning`, `error` |

### Consumer (Cluster C)

| Variable | Helm value | Default | Description |
|---|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka.bootstrapServers` | *(required)* | Kafka bootstrap host:port |
| `KAFKA_TOPIC` | `kafka.topic` | `hamq-messages` | Topic to consume from |
| `KAFKA_GROUP_ID` | `consumer.groupId` | `hamq-consumer-group` | Consumer group identifier |
| `KAFKA_AUTO_COMMIT_INTERVAL_MS` | `consumer.autoCommitIntervalMs` | `5000` | Offset auto-commit interval |
| `KAFKA_CA_CERT` | *(mounted from secret)* | `/certs/ca.crt` | Path to cluster CA certificate |
| `KAFKA_CLIENT_CERT` | *(mounted from secret)* | `/certs/user.crt` | Path to client TLS certificate |
| `KAFKA_CLIENT_KEY` | *(mounted from secret)* | `/certs/user.key` | Path to client TLS private key |
| `CONSUMER_DB_PATH` | `consumer.dbPath` | `/data/consumer.db` | SQLite path for persisting received messages |
| `API_PORT` | `api.port` | `8001` | FastAPI server port |
| `WS_PORT` | `api.wsPort` | `8001` | WebSocket port (same as API, different path) |
| `LOG_LEVEL` | `logLevel` | `info` | Logging level |

### Arbiter (Cluster D)

| Variable | Helm value | Default | Description |
|---|---|---|---|
| `PRODUCER_API_URL` | `arbiter.producerApiUrl` | *(required)* | Base URL of the Producer REST API |
| `CONSUMER_API_URL` | `arbiter.consumerApiUrl` | *(required)* | Base URL of the Consumer REST API |
| `ARBITER_POLL_INTERVAL_SECONDS` | `arbiter.pollIntervalSeconds` | `10` | How often to poll Producer and Consumer APIs |
| `API_PORT` | `api.port` | `8002` | FastAPI server port |
| `LOG_LEVEL` | `logLevel` | `info` | Logging level |

### Controller (Cluster E)

| Variable | Helm value | Default | Description |
|---|---|---|---|
| `PRODUCER_API_URL` | `controller.producerApiUrl` | *(required)* | Producer API base URL |
| `CONSUMER_API_URL` | `controller.consumerApiUrl` | *(required)* | Consumer API base URL |
| `ARBITER_API_URL` | `controller.arbiterApiUrl` | *(required)* | Arbiter API base URL |
| `KAFKA_NAMESPACE` | `controller.kafkaNamespace` | `kafka` | Kubernetes namespace where Kafka runs |
| `KAFKA_CLUSTER_NAME` | `controller.kafkaClusterName` | `hamq-kafka` | Strimzi Kafka resource name |
| `API_PORT` | `api.port` | `8003` | FastAPI server port |
| `LOG_LEVEL` | `logLevel` | `info` | Logging level |

---

## Resource Sizing

### Kafka brokers (Cluster A)

The default resource values are suitable for moderate workloads (< 10 000 msg/s). For higher throughput adjust the following `values.yaml` keys:

```yaml
kafka:
  resources:
    requests:
      memory: 4Gi    # increase for higher throughput
      cpu: "1"
    limits:
      memory: 8Gi
      cpu: "4"
  jvmOptions:
    xmx: 3072m       # ~60-75% of memory limit
    xms: 3072m       # set equal to xmx to avoid GC pressure
  storage:
    size: 100Gi      # scale to expected data volume × retention period
```

### Application pods

Default resource requests for application components:

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
# List available StorageClasses
kubectl get storageclass
```

For cloud providers:

| Cloud | Recommended StorageClass | Notes |
|-------|--------------------------|-------|
| AWS EKS | `gp3` | Provision with `allowVolumeExpansion: true` |
| GKE | `standard-rwo` | Regional disk for HA |
| Azure AKS | `managed-premium` | Premium SSD |
| On-premises | `local-path` or `rook-ceph` | Ensure replication at storage layer |

Set `kafka.storage.storageClass` in `values.yaml` to your chosen class.

> **Note:** Kafka already replicates data across brokers (RF=3). Using a replicated block storage (e.g., Ceph) adds redundancy at the storage layer, which improves durability but consumes more storage. For most deployments standard block storage per node is sufficient given Kafka's own replication.

---

## Network Policies

Apply the following Kubernetes NetworkPolicies to restrict traffic in Cluster A:

```yaml
# Allow only Producer/Consumer clusters to reach port 9094
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: kafka-external-ingress
  namespace: kafka
spec:
  podSelector:
    matchLabels:
      strimzi.io/cluster: hamq-kafka
  policyTypes:
    - Ingress
  ingress:
    - ports:
        - port: 9094
          protocol: TCP
    - ports:
        - port: 9093
          protocol: TCP
```

---

## Monitoring and Alerting

### Prometheus scraping

The HAMq Kafka chart deploys a `ServiceMonitor` (if `monitoring.serviceMonitor.enabled: true`) that configures Prometheus to scrape the JMX Prometheus Exporter on port `9404` every 30 seconds.

Ensure your Prometheus Operator is watching the `monitoring.serviceMonitor.namespace` namespace (default: `monitoring`).

### Key Kafka metrics to alert on

| Metric | Alert threshold | Meaning |
|--------|----------------|---------|
| `kafka_server_replicamanager_underreplicatedpartitions` | > 0 for > 60s | Partition has fewer replicas than RF |
| `kafka_server_replicamanager_offlinepartitionscount` | > 0 | Partition has no leader |
| `kafka_controller_kafkacontroller_activecontrollercount` | != 1 | No active controller or split-brain |
| `kafka_network_requestmetrics_requestspersec` | sudden drop | Kafka stopped receiving requests |
| `hamq_producer_buffer_size` | > 10000 | Producer buffer growing; Kafka may be unreachable |
| `hamq_consumer_lag_messages` | > 1000 | Consumer falling behind |
| `hamq_arbiter_loss_rate` | > 0.0001 | Message loss detected |

### Grafana dashboards

The chart can deploy pre-built Grafana dashboards as ConfigMaps (set `monitoring.grafana.dashboards.enabled: true`). Grafana must be configured to watch the `monitoring.grafana.dashboards.namespace` namespace for dashboard ConfigMaps (label: `grafana_dashboard: "1"`).

---

## Upgrade Procedures

### Upgrading the Kafka version

1. Update `kafka.version` in `values.yaml`.
2. Check the [Strimzi upgrade guide](https://strimzi.io/docs/operators/latest/deploying#assembly-upgrade-str) for inter-version protocol changes.
3. Run `helm upgrade` — Strimzi performs a rolling restart of brokers.

```bash
helm upgrade hamq-kafka components/kafka-cluster/helm \
  --namespace kafka \
  --set kafka.version=3.9.0 \
  --wait --timeout 15m
```

### Upgrading the Strimzi operator

Update `dependencies[0].version` in `Chart.yaml` and re-run `helm dependency update`. Then upgrade the Helm release. The operator upgrade is non-disruptive if the Kafka version is compatible.

### Rolling application component updates

Each application component Helm chart uses a `RollingUpdate` deployment strategy. Run `helm upgrade` with the new image tag:

```bash
helm upgrade hamq-producer components/producer/helm \
  --namespace hamq \
  --set image.tag=v1.2.0 \
  --wait --timeout 5m
```

---

## Troubleshooting

### Kafka pods are stuck in `Pending`

**Symptom:** `kubectl get pods -n kafka` shows pods in `Pending`.

**Cause / Fix:**

```bash
# Check events
kubectl describe pod <pod-name> -n kafka | grep -A 20 Events

# Common cause: no PVC bound — check StorageClass
kubectl get pvc -n kafka
kubectl get storageclass
```

Set `kafka.storage.storageClass` to a StorageClass that exists in your cluster.

---

### Kafka cluster not reaching `Ready` state

**Symptom:** `kubectl get kafka -n kafka` shows status other than `Ready`.

```bash
# Check Strimzi operator logs
kubectl logs -n kafka -l name=strimzi-cluster-operator --tail=100

# Check Kafka CR status conditions
kubectl get kafka hamq-kafka -n kafka -o jsonpath='{.status.conditions}' | jq .
```

---

### Producer cannot connect to Kafka

**Symptom:** Producer logs show `Connection refused` or `SSL handshake failed`.

```bash
# Verify bootstrap address is reachable
kubectl exec -n hamq <producer-pod> -- \
  nc -zv <kafka-bootstrap-host> 9094

# Verify certificates are mounted correctly
kubectl exec -n hamq <producer-pod> -- ls -la /certs/

# Test TLS handshake
kubectl exec -n hamq <producer-pod> -- \
  openssl s_client -connect <kafka-bootstrap-host>:9094 \
    -CAfile /certs/ca.crt \
    -cert /certs/user.crt \
    -key /certs/user.key \
    -verify_return_error
```

**Common causes:**
- `KAFKA_BOOTSTRAP_SERVERS` points to the internal cluster IP instead of the external LB IP.
- The client certificate Secret was not copied to the application cluster namespace.
- The StorageClass is not `standard` — update `kafka.storage.storageClass`.

---

### Consumer group lag is growing

**Symptom:** `hamq_consumer_lag_messages` is non-zero and increasing.

```bash
# Check consumer pod logs
kubectl logs -n hamq <consumer-pod> --tail=100

# Check consumer group offset lag using kafka-consumer-groups
kubectl exec -n kafka \
  $(kubectl get pod -n kafka -l strimzi.io/cluster=hamq-kafka -o name | head -1) -- \
  bin/kafka-consumer-groups.sh \
    --bootstrap-server localhost:9093 \
    --command-config /tmp/admin.properties \
    --describe --group hamq-consumer-group
```

---

### Strimzi entity operator pod crashlooping

**Symptom:** `hamq-kafka-entity-operator-*` pod repeatedly restarts.

```bash
kubectl logs -n kafka -l strimzi.io/kind=EntityOperator -c topic-operator --tail=50
kubectl logs -n kafka -l strimzi.io/kind=EntityOperator -c user-operator  --tail=50
```

Typical cause: conflicting KafkaTopic or KafkaUser resource definition (e.g., duplicate name, invalid ACL operation). Fix the offending resource and the operator will recover automatically.

---

### Certificate errors after cluster CA rotation

Strimzi rotates the cluster CA annually by default. After rotation, application components must reload the new CA cert:

```bash
# Re-export and re-apply the updated CA secret to application clusters
kubectl --context kafka-cluster -n kafka \
  get secret hamq-kafka-cluster-ca-cert -o json | \
  jq 'del(.metadata.resourceVersion,.metadata.uid,.metadata.creationTimestamp,.metadata.annotations,.metadata.ownerReferences)' | \
  kubectl --context producer-cluster -n hamq apply -f -

# Restart producer to pick up new cert
kubectl --context producer-cluster -n hamq \
  rollout restart deployment/hamq-producer
```

---

### Viewing all Prometheus metrics

```bash
# Port-forward the Kafka JMX exporter metrics endpoint
kubectl -n kafka port-forward \
  $(kubectl get pod -n kafka -l strimzi.io/name=hamq-kafka-kafka -o name | head -1) \
  9404:9404

# Browse metrics
curl http://localhost:9404/metrics | grep kafka_server
```
