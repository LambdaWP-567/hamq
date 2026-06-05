#!/usr/bin/env bash
# =============================================================================
# setup-k3s-single.sh — idempotent setup/teardown for a single-node k3s cluster
#
# Usage:
#   bash infra/setup-k3s-single.sh [setup|teardown]
#
# Runs as the current user; uses passwordless sudo for operations that need it.
# Safe to run repeatedly — all steps are idempotent.
# =============================================================================

set -euo pipefail
export LANG=C LC_ALL=C

ACTION="${1:-setup}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

K3S_VERSION="v1.35.5+k3s1"
CLUSTER_IP="192.168.1.22"
HAMQ_HOSTS="producer.hamq.test consumer.hamq.test arbiter.hamq.test controller.hamq.test"

log()   { printf '\033[0;32m[%s] [INFO]  %s\033[0m\n' "$(date '+%H:%M:%S')" "$*" >&2; }
warn()  { printf '\033[0;33m[%s] [WARN]  %s\033[0m\n' "$(date '+%H:%M:%S')" "$*" >&2; }
error() { printf '\033[0;31m[%s] [ERROR] %s\033[0m\n' "$(date '+%H:%M:%S')" "$*" >&2; exit 1; }
step()  {
  echo >&2
  printf '\033[1;34m══════════════════════════════════════════════════════\033[0m\n' >&2
  printf '\033[1;34m  %s\033[0m\n' "$*" >&2
  printf '\033[1;34m══════════════════════════════════════════════════════\033[0m\n' >&2
}

# =============================================================================
# TEARDOWN
# =============================================================================
do_teardown() {
  step "Teardown — uninstall k3s"
  if command -v k3s-uninstall.sh &>/dev/null; then
    sudo k3s-uninstall.sh
    log "k3s uninstalled"
  else
    warn "k3s-uninstall.sh not found — nothing to remove"
  fi

  step "Teardown — remove /etc/hosts entries"
  for host in $HAMQ_HOSTS; do
    sudo sed -i "/${host}/d" /etc/hosts
  done
  log "/etc/hosts cleaned"
}

# =============================================================================
# SETUP
# =============================================================================
do_setup() {
  # ── 1. k3s ──────────────────────────────────────────────────────────────────
  step "1 — k3s"
  if systemctl is-active k3s &>/dev/null; then
    INSTALLED=$(k3s --version 2>/dev/null | awk '{print $3}' || echo "unknown")
    log "k3s already running: $INSTALLED"
  else
    log "Installing k3s ${K3S_VERSION} ..."
    curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="${K3S_VERSION}" sh -
    sudo systemctl enable --now k3s
    log "k3s installed and started"
  fi

  # Wait for API server
  log "Waiting for API server ..."
  for i in $(seq 1 30); do
    if kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml cluster-info &>/dev/null 2>&1; then
      log "API server ready (attempt $i)"
      break
    fi
    sleep 2
  done

  # ── 2. Node readiness ───────────────────────────────────────────────────────
  step "2 — Node ready"
  kubectl wait node --all --for=condition=Ready --timeout=120s
  log "Node is Ready"
  kubectl get nodes -o wide

  # ── 3. Traefik (built into k3s) ─────────────────────────────────────────────
  step "3 — Traefik ingress"
  kubectl rollout status deployment/traefik -n kube-system --timeout=120s || \
    kubectl rollout status daemonset/traefik  -n kube-system --timeout=120s || \
    warn "Traefik not yet fully ready — continuing"

  TRAEFIK_IP=$(kubectl get svc traefik -n kube-system \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
  log "Traefik LoadBalancer IP: ${TRAEFIK_IP:-not yet assigned}"

  # ── 4. /etc/hosts entries ────────────────────────────────────────────────────
  step "4 — /etc/hosts"
  # Remove any old hamq.test entries then add a fresh consolidated line
  sudo sed -i '/hamq\.test/d' /etc/hosts
  HOSTS_LINE="${CLUSTER_IP}  ${HAMQ_HOSTS}"
  echo "$HOSTS_LINE" | sudo tee -a /etc/hosts >/dev/null
  log "Added: $HOSTS_LINE"
  grep "hamq.test" /etc/hosts

  # ── 5. local-path StorageClass ───────────────────────────────────────────────
  step "5 — StorageClass"
  if kubectl get storageclass local-path &>/dev/null; then
    log "local-path StorageClass present"
  else
    warn "local-path StorageClass not found — it should be installed by k3s automatically"
  fi

  # ── 6. Helm repos ────────────────────────────────────────────────────────────
  step "6 — Helm repos"
  helm repo add strimzi https://strimzi.io/charts/ 2>/dev/null || true
  helm repo update
  log "Helm repos up to date"

  # ── 7. Summary ───────────────────────────────────────────────────────────────
  step "Setup complete"
  log "Cluster info:"
  kubectl cluster-info
  log ""
  log "Ready to deploy HAMq:"
  log "  gh workflow run deploy.yml"
  log "  — or — bash infra/deploy.sh"
}

# =============================================================================
# Dispatch
# =============================================================================
case "$ACTION" in
  setup)    do_setup    ;;
  teardown) do_teardown ;;
  *) error "Unknown action: $ACTION (expected: setup|teardown)" ;;
esac
