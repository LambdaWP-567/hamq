#!/usr/bin/env bash
# =============================================================================
# deploy.sh — deploy HAMq to the k3s test cluster (single-node)
#
# Requires:
#   - KUBECONFIG env var pointing at the k3s cluster, OR infra/kubeconfig
#   - helm, kubectl in PATH
#   - GHCR_TOKEN env var (GitHub PAT with read:packages scope)
# =============================================================================

set -euo pipefail
export LANG=C LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VALUES_DIR="${SCRIPT_DIR}/values"

# Respect an existing KUBECONFIG (e.g. /etc/rancher/k3s/k3s.yaml on the runner),
# falling back to the local infra/kubeconfig for manual runs.
export KUBECONFIG="${KUBECONFIG:-${SCRIPT_DIR}/kubeconfig}"

GHCR_USER="lambdawp-567"
# Set GHCR_TOKEN env var before running: export GHCR_TOKEN=<your-pat>
GHCR_TOKEN="${GHCR_TOKEN:?GHCR_TOKEN env var must be set (GitHub PAT with read:packages)}"

KAFKA_NS="kafka"
APP_NS="hamq"

TRAEFIK_IP="192.168.1.22"

# ─── Logging ─────────────────────────────────────────────────────────────────
log()   { printf '\033[0;32m[%s] [INFO]  %s\033[0m\n' "$(date '+%H:%M:%S')" "$*" >&2; }
warn()  { printf '\033[0;33m[%s] [WARN]  %s\033[0m\n' "$(date '+%H:%M:%S')" "$*" >&2; }
error() { printf '\033[0;31m[%s] [ERROR] %s\033[0m\n' "$(date '+%H:%M:%S')" "$*" >&2; exit 1; }
step()  {
  echo >&2
  printf '\033[1;34m══════════════════════════════════════════════════════\033[0m\n' >&2
  printf '\033[1;34m  %s\033[0m\n' "$*" >&2
  printf '\033[1;34m══════════════════════════════════════════════════════\033[0m\n' >&2
}

# ─── Guards ──────────────────────────────────────────────────────────────────
[[ -f "$KUBECONFIG" ]] || error "Kubeconfig not found at $KUBECONFIG — run setup-cluster.sh first"
kubectl cluster-info --request-timeout=5s &>/dev/null || error "Cannot reach k3s cluster — is it running?"
command -v helm &>/dev/null  || error "helm not found in PATH"
log "Cluster reachable — $(kubectl get nodes --no-headers | wc -l) nodes"


# =============================================================================
# STEP 1 — Namespaces
# =============================================================================
step "1 — Namespaces"
for ns in "$KAFKA_NS" "$APP_NS"; do
  if kubectl get ns "$ns" &>/dev/null; then
    log "Namespace $ns already exists"
  else
    kubectl create ns "$ns"
    log "Created namespace $ns"
  fi
done


# =============================================================================
# STEP 2 — GHCR imagePullSecret
# =============================================================================
step "2 — GHCR imagePullSecret (ghcr-secret)"
for ns in "$KAFKA_NS" "$APP_NS"; do
  if kubectl get secret ghcr-secret -n "$ns" &>/dev/null; then
    log "ghcr-secret already exists in $ns"
  else
    kubectl create secret docker-registry ghcr-secret \
      --docker-server=ghcr.io \
      --docker-username="$GHCR_USER" \
      --docker-password="$GHCR_TOKEN" \
      -n "$ns"
    log "Created ghcr-secret in $ns"
  fi
done


# =============================================================================
# STEP 3 — Auth secrets for app components
# =============================================================================
step "3 — Auth secrets"

create_auth_secret() {
  local name=$1 ns=$2 user=$3 password=$4
  if kubectl get secret "$name" -n "$ns" &>/dev/null; then
    log "Secret $name already exists in $ns"
    return
  fi
  kubectl create secret generic "$name" \
    --from-literal=username="$user" \
    --from-literal=password="$password" \
    -n "$ns"
  log "Created secret $name in $ns (user=$user)"
}

create_auth_secret hamq-producer-auth   "$APP_NS" admin admin
create_auth_secret hamq-consumer-auth   "$APP_NS" admin admin
create_auth_secret hamq-arbiter-auth    "$APP_NS" admin admin
create_auth_secret hamq-controller-auth "$APP_NS" admin admin


# =============================================================================
# STEP 4 — Helm repos
# =============================================================================
step "4 — Helm repos"
helm repo add strimzi https://strimzi.io/charts/ 2>/dev/null || true
helm repo update
log "Helm repos up to date"


# =============================================================================
# STEP 5 — Kafka (Strimzi operator + cluster)
# =============================================================================
step "5 — Kafka: helm dependency update"
helm dependency update "${REPO_ROOT}/components/kafka-cluster/helm" 2>&1 | sed 's/^/  /'
log "Dependencies ready"

step "5 — Kafka: helm install/upgrade"
helm upgrade --install kafka-cluster \
  "${REPO_ROOT}/components/kafka-cluster/helm" \
  -n "$KAFKA_NS" \
  -f "${VALUES_DIR}/kafka-test.yaml" \
  --set global.namespace="$KAFKA_NS" \
  --timeout 5m \
  --wait=false
log "Kafka chart submitted"


# =============================================================================
# STEP 6 — Wait for Strimzi operator, then Kafka brokers
# =============================================================================
step "6 — Wait for Strimzi operator pod"
log "Waiting for Strimzi cluster-operator deployment..."
kubectl rollout status deployment/strimzi-cluster-operator \
  -n "$KAFKA_NS" --timeout=300s
log "Strimzi operator is ready"

step "6 — Wait for Kafka broker (KafkaNodePool)"
log "Waiting for Kafka broker pod to be Running (up to 10 min)..."
for attempt in $(seq 1 60); do
  ready=$(kubectl get pods -n "$KAFKA_NS" \
    -l strimzi.io/name=hamq-kafka-kafka \
    --no-headers 2>/dev/null \
    | grep -c "Running" || true)
  total=$(kubectl get pods -n "$KAFKA_NS" \
    -l strimzi.io/name=hamq-kafka-kafka \
    --no-headers 2>/dev/null \
    | wc -l || true)
  log "  attempt $attempt/60 — brokers Running: $ready/$total"
  if [[ "$ready" -ge 1 ]]; then
    log "Kafka broker is Running"
    break
  fi
  if [[ $attempt -eq 60 ]]; then
    warn "Timeout waiting for broker — current pod state:"
    kubectl get pods -n "$KAFKA_NS" | sed 's/^/  /'
    error "Kafka did not become ready in time"
  fi
  sleep 10
done

log "Kafka pod summary:"
kubectl get pods -n "$KAFKA_NS" | sed 's/^/  /'


# =============================================================================
# STEP 7 — App components
# =============================================================================
deploy_app() {
  local name=$1 chart=$2 values=$3
  step "7 — Deploy $name"
  if helm status "$name" -n "$APP_NS" &>/dev/null; then
    log "$name already installed — upgrading"
  fi
  helm upgrade --install "$name" \
    "${REPO_ROOT}/components/${chart}/helm" \
    -n "$APP_NS" \
    -f "${values}" \
    --force-conflicts \
    --timeout 3m \
    --wait
  log "$name deployed"
  kubectl get pods -n "$APP_NS" -l "app.kubernetes.io/name=${chart}" \
    --no-headers 2>/dev/null | sed 's/^/  /' || true
}

deploy_app hamq-producer   producer   "${VALUES_DIR}/producer-test.yaml"
deploy_app hamq-consumer   consumer   "${VALUES_DIR}/consumer-test.yaml"
deploy_app hamq-arbiter    arbiter    "${VALUES_DIR}/arbiter-test.yaml"
deploy_app hamq-controller controller "${VALUES_DIR}/controller-test.yaml"

# Cockpit has no pods — it's a reverse-proxy to the host Cockpit service
step "7 — Deploy cockpit ingress"
helm upgrade --install hamq-cockpit \
  "${REPO_ROOT}/components/cockpit/helm" \
  -n "$APP_NS" \
  -f "${VALUES_DIR}/cockpit-test.yaml" \
  --timeout 1m
log "Cockpit ingress deployed"


# =============================================================================
# STEP 8 — Summary
# =============================================================================
step "8 — Deployment complete"

log "All pods:"
kubectl get pods -n "$KAFKA_NS" | sed 's/^/  [kafka]   /'
kubectl get pods -n "$APP_NS"   | sed 's/^/  [hamq]    /'

log ""
log "Ingress rules:"
kubectl get ingress -n "$APP_NS" | sed 's/^/  /'

log ""
log "Access URLs (add to /etc/hosts if nip.io DNS doesn't resolve):"
log "  Producer   : http://producer.${TRAEFIK_IP}.nip.io"
log "  Consumer   : http://consumer.${TRAEFIK_IP}.nip.io"
log "  Arbiter    : http://arbiter.${TRAEFIK_IP}.nip.io"
log "  Controller : http://controller.${TRAEFIK_IP}.nip.io"
log "  Cockpit    : http://cockpit.${TRAEFIK_IP}.nip.io"
log ""
log "  Default credentials: admin / admin"
log ""
log "To watch pods live:"
log "  watch kubectl get pods -A"
