# Kafka Cluster Component

This component deploys a **highly available Apache Kafka cluster** via the [Strimzi Kafka Operator](https://strimzi.io/) in KRaft mode (no Zookeeper required since Strimzi 0.40+).

## Architecture

```
┌─────────────────────────── Kubernetes Namespace: kafka ──────────────────────────────┐
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐ │
│  │                      Strimzi Kafka Operator (Deployment)                         │ │
│  │  Watches: Kafka, KafkaNodePool, KafkaTopic, KafkaUser CRDs                       │ │
│  └──────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                        │
│  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐        │
│  │  KafkaNodePool       │  │  KafkaNodePool       │  │  KafkaNodePool       │        │
│  │  dual-role-0         │  │  dual-role-1         │  │  dual-role-2         │        │
│  │  roles: broker       │  │  roles: broker       │  │  roles: broker       │        │
│  │        + controller  │  │        + controller  │  │        + controller  │        │
│  └──────────────────────┘  └──────────────────────┘  └──────────────────────┘        │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐ │
│  │  Strimzi Entity Operator                                                         │ │
│  │  Topic Operator: reconciles KafkaTopic CRs with actual Kafka topics              │ │
│  │  User Operator:  reconciles KafkaUser CRs  with ACLs and TLS certificates        │ │
│  └──────────────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

## Key Configuration for High Availability

| Parameter | Value | Why |
|-----------|-------|-----|
| `replicas` | 3 | Quorum = majority of 3 = 2 nodes can survive 1 failure |
| `acks` | all | Producer waits for all ISR replicas to acknowledge |
| `replication.factor` | 3 | Each partition has 3 copies |
| `min.insync.replicas` | 2 | Write succeeds only if ≥ 2 replicas confirm |
| `auto.create.topics.enable` | false | Prevents accidental topic creation with wrong RF |

With these settings: **a single broker failure causes zero message loss**. The topic remains writable as long as ≥ 2 replicas are in-sync.

## Prerequisites

- Kubernetes 1.25+
- Helm 3.12+
- cert-manager 1.13+ (for TLS certificate management)
- Strimzi Kafka Operator installed (or set `strimzi.install: true`)
- Storage class that supports `ReadWriteOnce` (most cloud providers)

## Installation

### 1. Add Helm Repositories

```bash
helm repo add strimzi https://strimzi.io/charts/
helm repo update
```

### 2. Install Strimzi Operator (if not already installed)

```bash
helm install strimzi-operator strimzi/strimzi-kafka-operator \
  --namespace kafka \
  --create-namespace \
  --version 0.43.0 \
  --set watchAnyNamespace=false \
  --set defaultImageRegistry=quay.io
```

### 3. Deploy the Kafka Cluster

```bash
# With default settings (3 brokers, 10Gi storage, TLS)
helm install kafka-cluster ./helm \
  --namespace kafka \
  --create-namespace \
  --wait \
  --timeout 10m

# Custom settings
helm install kafka-cluster ./helm \
  --namespace kafka \
  --set kafka.replicas=5 \
  --set kafka.storage.size=50Gi \
  --set kafka.storage.storageClass=premium-rwo
```

### 4. Verify the Cluster

```bash
# Check pod status (all 3 should be Running)
kubectl get pods -n kafka -l strimzi.io/cluster=hamq-kafka

# Check the Kafka CR status
kubectl get kafka -n kafka hamq-kafka -o jsonpath='{.status.conditions}'

# Check that the bootstrap service exists
kubectl get svc -n kafka | grep bootstrap
```

## Connecting External Clients

After deployment, Strimzi creates these Kubernetes Services:

| Service | DNS Name | Port | Protocol |
|---------|----------|------|----------|
| Bootstrap (plain) | `hamq-kafka-kafka-bootstrap.kafka.svc.cluster.local` | 9092 | PLAINTEXT |
| Bootstrap (TLS) | `hamq-kafka-kafka-bootstrap.kafka.svc.cluster.local` | 9093 | TLS |
| External LoadBalancer | `<EXTERNAL_IP>` | 9094 | TLS |

### Extracting the CA Certificate

Strimzi stores the cluster CA certificate in a Secret:

```bash
# Extract for use in producer/consumer
kubectl get secret hamq-kafka-cluster-ca-cert \
  -n kafka \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > ca.crt
```

### Extracting User Certificates (mTLS)

```bash
# Producer certificate (after KafkaUser 'hamq-producer' is created)
kubectl get secret hamq-producer \
  -n kafka \
  -o jsonpath='{.data.user\.crt}' | base64 -d > user.crt

kubectl get secret hamq-producer \
  -n kafka \
  -o jsonpath='{.data.user\.key}' | base64 -d > user.key
```

## Topics

The chart pre-creates the following topics:

| Topic | Partitions | Replication Factor | Retention |
|-------|-----------|-------------------|-----------|
| `hamq-messages` | 12 | 3 | 7 days |
| `hamq-dlq` | 3 | 3 | 7 days |

`hamq-messages` uses 12 partitions to support up to 10 parallel producers without contention.

## Monitoring

When `monitoring.enabled: true`, the chart creates:
- A `ServiceMonitor` for Prometheus to scrape Kafka JMX metrics (port 9404)
- A `ServiceMonitor` for the KafkaExporter (consumer group lag)

### Important Metrics

| Metric | Alert Threshold | Meaning |
|--------|----------------|---------|
| `kafka_controller_active_controller_count` | < 1 | No active controller — cluster unavailable |
| `kafka_server_replica_manager_under_replicated_partitions` | > 0 | Partitions without full replication |
| `kafka_consumer_group_lag` | > 10000 | Consumer is falling behind |
| `kafka_server_broker_state` | ≠ 3 | Broker not in running state |

## Scaling

### Scale Up (add brokers)

```bash
helm upgrade kafka-cluster ./helm \
  --namespace kafka \
  --set kafka.replicas=5 \
  --reuse-values
```

Strimzi will add the new pods and rebalance partitions automatically (with Cruise Control if enabled).

### Scale Down

> ⚠️  Before scaling down, ensure all partitions have their leader moved off the pods being removed. Use `kafka-reassign-partitions.sh` or Cruise Control.

## Backup and Restore

Kafka stores data in the PersistentVolumes mounted at `/var/lib/kafka/data`. For backup:

1. Use `kafka-dump-log.sh` to export topic data
2. Or snapshot the underlying PVs (cloud provider volume snapshots)
3. MirrorMaker2 can replicate to another cluster in real-time

## Troubleshooting

### Broker stuck in CrashLoopBackOff
```bash
kubectl logs -n kafka <pod-name> --previous
# Common causes: storage full, misconfigured KRaft quorum, certificate expiry
```

### Under-replicated partitions after broker restart
```bash
# Check ISR status
kubectl exec -n kafka hamq-kafka-dual-role-0 -- \
  kafka-topics.sh --bootstrap-server localhost:9092 --describe \
  | grep "UnderReplicated"
```

### Certificate expired
```bash
# Strimzi auto-renews certs 30 days before expiry via cert-manager
# Force renewal:
kubectl annotate secret hamq-kafka-cluster-ca-cert \
  -n kafka \
  strimzi.io/force-renew=true
```
