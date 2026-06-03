# Kafka Cluster Component

The `kafka-cluster` component deploys an Apache Kafka 3.8 cluster in KRaft mode using the Strimzi Kafka Operator. It provides the central message bus for all HAMq components.

---

## Table of Contents

- [Overview](#overview)
- [Strimzi KRaft Mode Setup](#strimzi-kraft-mode-setup)
- [Configuration Parameters](#configuration-parameters)
- [Scaling](#scaling)
- [Monitoring with Prometheus](#monitoring-with-prometheus)
- [Backup and Restore](#backup-and-restore)
- [Security](#security)
- [Operational Runbook](#operational-runbook)

---

## Overview

| Property | Value |
|----------|-------|
| Kafka version | 3.8.0 |
| Operator | Strimzi 0.43.0 |
| Consensus | KRaft (no ZooKeeper) |
| Node count | 3 (dual-role: controller + broker) |
| Replication factor | 3 |
| min.insync.replicas | 2 |
| Authentication | mTLS (TLS client certificates) |
| TLS PKI | cert-manager ClusterIssuer |
| Metrics | JMX Prometheus Exporter |

---

## Strimzi KRaft Mode Setup

### What is KRaft?

KRaft (Kafka Raft) replaces ZooKeeper as Kafka's metadata consensus layer. Starting with Kafka 3.3, KRaft is production-ready and is the only supported mode from Kafka 4.0. HAMq runs KRaft mode with Strimzi 0.43.0+.

Benefits over ZooKeeper mode:
- Fewer components to operate (no ZooKeeper ensemble).
- Faster partition re-assignment and leader election.
- Metadata stored in an internal Raft log on the same persistent volume as broker data.
- Supports larger partition counts.

### KafkaNodePool

Strimzi KRaft mode uses the `KafkaNodePool` custom resource to assign roles to broker pods. HAMq uses a single `dual-role` pool where every node is simultaneously a Raft controller and a Kafka broker:

```yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaNodePool
metadata:
  name: dual-role
  labels:
    strimzi.io/cluster: hamq-kafka
spec:
  replicas: 3
  roles:
    - controller
    - broker
  storage:
    type: persistent-claim
    size: 10Gi
    class: standard
```

### Kafka resource annotations

The `Kafka` custom resource must be annotated to enable KRaft and node pools:

```yaml
metadata:
  annotations:
    strimzi.io/node-pools: enabled
    strimzi.io/kraft: enabled
```

### Quorum and availability

With 3 dual-role nodes, the KRaft quorum requires a majority (2 of 3) to elect a leader and process metadata changes. The system tolerates the loss of exactly 1 node while remaining fully operational.

| Nodes down | KRaft quorum | Kafka writes |
|------------|-------------|--------------|
| 0 | Healthy | Full throughput |
| 1 | Healthy (2/3 quorum) | Full throughput (ISR=2) |
| 2 | **Lost** | Kafka unavailable |
| 3 | Lost | Unavailable |

---

## Configuration Parameters

All parameters are set in `components/kafka-cluster/helm/values.yaml`. The key sections are:

### `kafka` — broker configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `kafka.name` | `hamq-kafka` | Strimzi cluster name (used as label and prefix for all resources) |
| `kafka.version` | `3.8.0` | Kafka version |
| `kafka.replicas` | `3` | Number of broker+controller nodes |
| `kafka.storage.type` | `persistent-claim` | Storage type (`persistent-claim` or `ephemeral`). Always use `persistent-claim` in production |
| `kafka.storage.size` | `10Gi` | PVC size per node |
| `kafka.storage.storageClass` | `standard` | Kubernetes StorageClass name |
| `kafka.storage.deleteClaim` | `false` | Whether to delete PVCs when the cluster is deleted. Keep `false` in production |
| `kafka.resources.requests.memory` | `2Gi` | Memory request per broker pod |
| `kafka.resources.limits.memory` | `4Gi` | Memory limit per broker pod |
| `kafka.jvmOptions.xmx` | `1536m` | JVM max heap. Should be ~60% of memory limit |
| `kafka.jvmOptions.xms` | `1536m` | JVM initial heap. Set equal to xmx for stable GC |

### `kafka.listeners`

| Parameter | Default | Description |
|-----------|---------|-------------|
| `kafka.listeners.plain.port` | `9092` | Plaintext listener (no auth — for internal dev only) |
| `kafka.listeners.plain.enabled` | `true` | Enable plaintext listener |
| `kafka.listeners.tls.port` | `9093` | In-cluster TLS listener with mTLS authentication |
| `kafka.listeners.tls.enabled` | `true` | Enable TLS listener |
| `kafka.listeners.external.port` | `9094` | External LoadBalancer listener (TLS) |
| `kafka.listeners.external.type` | `loadbalancer` | External listener type |
| `kafka.listeners.external.enabled` | `true` | Enable external listener |

### `kafka.config`

| Parameter | Default | Kafka config key | Description |
|-----------|---------|-----------------|-------------|
| `kafka.config.defaultReplicationFactor` | `3` | `default.replication.factor` | Default RF for new topics |
| `kafka.config.minInsyncReplicas` | `2` | `min.insync.replicas` | Minimum ISR for acks=all |
| `kafka.config.offsetsTopicReplicationFactor` | `3` | `offsets.topic.replication.factor` | RF for `__consumer_offsets` |
| `kafka.config.transactionStateLogReplicationFactor` | `3` | `transaction.state.log.replication.factor` | RF for transactions topic |
| `kafka.config.transactionStateLogMinIsr` | `2` | `transaction.state.log.min.isr` | Min ISR for transactions topic |
| `kafka.config.logRetentionHours` | `168` | `log.retention.hours` | Log retention (7 days) |
| `kafka.config.logSegmentBytes` | `1073741824` | `log.segment.bytes` | Log segment size (1 GiB) |
| `kafka.config.autoCreateTopicsEnable` | `false` | `auto.create.topics.enable` | Require explicit KafkaTopic creation |

### `topics` — pre-created topics

| Topic | Partitions | RF | Retention |
|-------|-----------|-----|-----------|
| `hamq-messages` | 12 | 3 | 7 days |
| `hamq-dlq` | 3 | 3 | default |

### `users` — KafkaUser resources

| User | Auth | ACLs |
|------|------|------|
| `hamq-producer` | TLS client cert | Write, Create, Describe on `hamq-messages` |
| `hamq-consumer` | TLS client cert | Read, Describe on `hamq-messages`; Read on group `hamq-consumer-group` |

---

## Scaling

### Horizontal scaling (add brokers)

To add a broker node, increase `kafka.replicas`:

```bash
helm upgrade hamq-kafka components/kafka-cluster/helm \
  --namespace kafka \
  --set kafka.replicas=5 \
  --wait --timeout 15m
```

Strimzi will provision the new pod, mount a new PVC, and the broker will join the cluster. Kafka will **not** automatically rebalance partitions. Use Cruise Control or `kafka-reassign-partitions.sh` to rebalance.

### Vertical scaling (increase resources)

Update `kafka.resources` in `values.yaml` and run `helm upgrade`. Strimzi will perform a rolling restart of all brokers. Ensure `kafka.jvmOptions.xmx` is updated proportionally.

### Partition count

The `hamq-messages` topic is created with 12 partitions. For higher throughput increase `topics.messages.partitions`. Note that reducing partition count is not supported by Kafka; you must recreate the topic (with data loss or a migration window).

---

## Monitoring with Prometheus

### JMX Prometheus Exporter

The Kafka chart deploys a JMX Prometheus Exporter sidecar on each broker pod, scraping all JMX metrics and exposing them on port `9404`. The exporter config is stored in a `ConfigMap` named `kafka-metrics`.

### ServiceMonitor

When `monitoring.serviceMonitor.enabled: true`, the chart creates a Prometheus `ServiceMonitor` resource that instructs the Prometheus Operator to scrape all broker pods every 30 seconds.

```bash
# Verify ServiceMonitor was created
kubectl get servicemonitor -n monitoring

# Check that Prometheus has picked up the targets
# (access Prometheus UI → Status → Targets and search for "kafka")
```

### Key metrics

| Metric | Description |
|--------|-------------|
| `kafka_server_replicamanager_underreplicatedpartitions` | Should be 0; spikes indicate broker issues |
| `kafka_server_replicamanager_leadercount` | Number of partition leaders on this broker |
| `kafka_server_brokertopicmetrics_messagesinpersec` | Ingestion rate |
| `kafka_server_brokertopicmetrics_bytesoutpersec` | Egress rate |
| `kafka_controller_kafkacontroller_activecontrollercount` | Must equal 1 across the cluster |
| `kafka_log_log_size` | Total log size per topic-partition |
| `kafka_network_requestmetrics_totaltimems` | Request latency percentiles |

### Grafana dashboards

With `monitoring.grafana.dashboards.enabled: true`, the chart creates a ConfigMap in `monitoring.grafana.dashboards.namespace` (default: `monitoring`) containing a pre-built Grafana dashboard JSON. Grafana must be configured with sidecar label `grafana_dashboard: "1"`.

The dashboard includes:
- Cluster health overview (under-replicated partitions, offline partitions)
- Throughput (messages/s, bytes/s) per topic
- Consumer group lag
- Request latency heatmap
- JVM GC metrics

---

## Backup and Restore

Kafka is a distributed commit log. "Backup" in Kafka context means ensuring topic data can be recovered after a catastrophic cluster loss.

### Option 1: MirrorMaker 2 (disaster recovery cluster)

For production environments, deploy a secondary Kafka cluster and use Kafka MirrorMaker 2 (MM2) to replicate all topics:

```yaml
# mirrormaker2.yaml — example MM2 configuration
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaMirrorMaker2
metadata:
  name: hamq-mm2
spec:
  version: "3.8.0"
  replicas: 1
  connectCluster: target
  clusters:
    - alias: source
      bootstrapServers: hamq-kafka-kafka-bootstrap.kafka.svc.cluster.local:9093
      tls:
        trustedCertificates:
          - secretName: hamq-kafka-cluster-ca-cert
            certificate: ca.crt
    - alias: target
      bootstrapServers: <dr-kafka-bootstrap>:9093
  mirrors:
    - sourceCluster: source
      targetCluster: target
      sourceConnector:
        config:
          replication.factor: 3
          offset-syncs.topic.replication.factor: 3
```

### Option 2: Volume snapshots (PVC-level backup)

Take snapshots of the broker PVCs. This requires your storage class to support `VolumeSnapshot`:

```bash
# Create a VolumeSnapshot for each broker PVC
for i in 0 1 2; do
  kubectl apply -f - <<EOF
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: hamq-kafka-data-snapshot-${i}
  namespace: kafka
spec:
  volumeSnapshotClassName: csi-hostpath-snapclass
  source:
    persistentVolumeClaimName: data-hamq-kafka-dual-role-${i}
EOF
done
```

**Important:** Snapshot-based restore requires the cluster to be shut down first to avoid log inconsistencies.

### Restore procedure

1. Delete the Kafka cluster:
   ```bash
   kubectl delete kafka hamq-kafka -n kafka
   # Wait for pods to terminate
   ```

2. Restore PVCs from snapshots:
   ```bash
   kubectl apply -f restore-pvcs.yaml
   ```

3. Reinstall the Helm chart (with `kafka.storage.deleteClaim: false`):
   ```bash
   helm install hamq-kafka components/kafka-cluster/helm \
     --namespace kafka \
     --set kafka.storage.deleteClaim=false
   ```

4. Strimzi will reuse the existing PVCs and the cluster will recover.

---

## Security

### mTLS enforcement

The TLS listener (`port: 9093`) and external listener (`port: 9094`) are configured with `authentication.type: tls`, meaning clients must present a valid certificate signed by the `kafka-clients-ca`. The plaintext listener (`port: 9092`) should be disabled or restricted to internal tooling.

To disable the plaintext listener in production:

```yaml
kafka:
  listeners:
    plain:
      enabled: false
```

### ACL authorization

All KafkaUser resources have explicit ACL rules. No user has wildcard permissions. The Entity Operator enforces ACLs in real time — changes to `KafkaUser` resources are applied without broker restart.

### Encryption at rest

Strimzi does not manage encryption at rest. Enable it at the StorageClass / CSI driver level:

- **AWS EKS:** Use gp3 volumes with AWS KMS encryption via the `kms-key-id` StorageClass parameter.
- **GKE:** Use customer-managed encryption keys (CMEK) with persistent disks.
- **Azure AKS:** Use Azure Disk with Server-Side Encryption + customer managed keys.

---

## Operational Runbook

See the [component README](../../components/kafka-cluster/docs/README.md) for a detailed operational runbook including:
- Broker restart procedures
- Partition reassignment
- Certificate rotation
- Log compaction management
- Strimzi operator upgrades
