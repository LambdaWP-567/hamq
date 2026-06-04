#!/usr/bin/env bash
# =============================================================================
# setup-metallb.sh
# 1. Disable k3s built-in servicelb on the control-plane node
# 2. Install MetalLB (L2 mode) with pool 192.168.122.200-210
# 3. Wait for Traefik to receive a MetalLB IP
# 4. Add /etc/hosts entries on this host for *.hamq.local
# 5. Upgrade all app Helm releases with hamq.local ingress hosts
# =============================================================================

set -euo pipefail
export LANG=C LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VALUES_DIR="${SCRIPT_DIR}/values"
export KUBECONFIG="${SCRIPT_DIR}/kubeconfig"

SSH_KEY="/root/.ssh/k3s-cluster"
CP_IP="192.168.122.10"
POOL_START="192.168.122.200"
POOL_END="192.168.122.210"
DOMAIN="hamq.local"

log()  { printf '\033[0;32m[%s] [INFO]  %s\033[0m\n' "$(date '+%H:%M:%S')" "$*" >&2; }
warn() { printf '\033[0;33m[%s] [WARN]  %s\033[0m\n' "$(date '+%H:%M:%S')" "$*" >&2; }
err()  { printf '\033[0;31m[%s] [ERROR] %s\033[0m\n' "$(date '+%H:%M:%S')" "$*" >&2; exit 1; }
step() {
  echo >&2
  printf '\033[1;34m══════════════════════════════════════════════════════\033[0m\n' >&2
  printf '\033[1;34m  %s\033[0m\n' "$*" >&2
  printf '\033[1;34m══════════════════════════════════════════════════════\033[0m\n' >&2
}

[[ $EUID -eq 0 ]] || err "Run as root: sudo bash infra/setup-metallb.sh"
kubectl cluster-info --request-timeout=5s &>/dev/null || err "Cluster unreachable"


# =============================================================================
# STEP 1 — Disable k3s servicelb
# =============================================================================
step "1 — Disable k3s built-in servicelb"

log "Writing /etc/rancher/k3s/config.yaml on $CP_IP..."
ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" ubuntu@"$CP_IP" \
  "sudo bash -c 'echo -e \"disable:\n  - servicelb\" > /etc/rancher/k3s/config.yaml'"

log "Config written. Restarting k3s server..."
ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" ubuntu@"$CP_IP" \
  "sudo systemctl restart k3s"

log "Waiting for k3s API server to come back (up to 2 min)..."
for i in $(seq 1 24); do
  sleep 5
  kubectl cluster-info --request-timeout=3s &>/dev/null && {
    log "API server is back after $((i*5))s"
    break
  }
  log "  attempt $i/24 — not ready yet..."
  [[ $i -eq 24 ]] && err "Cluster API did not recover"
done

log "Waiting for svclb-traefik pods to be removed..."
for i in $(seq 1 18); do
  count=$(kubectl get pods -n kube-system -l app=svclb-traefik --no-headers 2>/dev/null | wc -l || echo 0)
  [[ "$count" -eq 0 ]] && { log "svclb pods removed"; break; }
  log "  $count svclb pod(s) still present, waiting 5s..."
  sleep 5
  [[ $i -eq 18 ]] && warn "svclb pods still present — continuing anyway"
done

log "Nodes:"
kubectl get nodes | sed 's/^/  /'


# =============================================================================
# STEP 2 — Install MetalLB
# =============================================================================
step "2 — Install MetalLB"

helm repo add metallb https://metallb.github.io/metallb 2>/dev/null || true
helm repo update metallb

log "Installing MetalLB..."
helm upgrade --install metallb metallb/metallb \
  -n metallb-system --create-namespace \
  --wait --timeout 3m

log "MetalLB pods:"
kubectl get pods -n metallb-system | sed 's/^/  /'


# =============================================================================
# STEP 3 — Configure IP pool and L2 advertisement
# =============================================================================
step "3 — Configure MetalLB IPAddressPool and L2Advertisement"

log "Pool: ${POOL_START} – ${POOL_END}"

kubectl apply -f - <<EOF
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: hamq-pool
  namespace: metallb-system
spec:
  addresses:
    - ${POOL_START}-${POOL_END}
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: hamq-l2
  namespace: metallb-system
spec:
  ipAddressPools:
    - hamq-pool
EOF

log "MetalLB resources applied"


# =============================================================================
# STEP 4 — Wait for Traefik to receive a MetalLB IP
# =============================================================================
step "4 — Wait for Traefik LoadBalancer IP"

TRAEFIK_IP=""
for i in $(seq 1 30); do
  TRAEFIK_IP=$(kubectl get svc traefik -n kube-system \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
  if [[ -n "$TRAEFIK_IP" ]] && [[ "$TRAEFIK_IP" != "<none>" ]]; then
    log "Traefik LoadBalancer IP: $TRAEFIK_IP"
    break
  fi
  log "  attempt $i/30 — no IP yet, waiting 5s..."
  sleep 5
  [[ $i -eq 30 ]] && err "Traefik did not receive a LoadBalancer IP"
done

log "Traefik service:"
kubectl get svc traefik -n kube-system | sed 's/^/  /'


# =============================================================================
# STEP 5 — /etc/hosts on this host
# =============================================================================
step "5 — /etc/hosts entries on host"

HOSTS_LINE="${TRAEFIK_IP} producer.${DOMAIN} consumer.${DOMAIN} arbiter.${DOMAIN} controller.${DOMAIN}"

# Remove any previous hamq entries
sed -i "/${DOMAIN}/d" /etc/hosts
echo "$HOSTS_LINE" >> /etc/hosts

log "Added to /etc/hosts:"
log "  $HOSTS_LINE"


# =============================================================================
# STEP 6 — Update test values with hamq.local hostnames and deploy
# =============================================================================
step "6 — Update ingress hosts and redeploy all app components"

# Re-write values files with new hostnames
for component in producer consumer arbiter controller; do
  log "Updating infra/values/${component}-test.yaml → ${component}.${DOMAIN}"
  python3 - "${VALUES_DIR}/${component}-test.yaml" "${component}.${DOMAIN}" <<'PYEOF'
import sys, re
path, host = sys.argv[1], sys.argv[2]
with open(path) as f:
    content = f.read()
content = re.sub(r'host:.*\.nip\.io.*', f'host: {host}', content)
content = re.sub(r'host:.*\.hamq\.local.*', f'host: {host}', content)
with open(path, 'w') as f:
    f.write(content)
print(f"  {path} -> host: {host}")
PYEOF
done

# Deploy (or upgrade) each component
deploy() {
  local name=$1 chart=$2 vals=$3
  log "[$name] helm upgrade --install..."
  helm upgrade --install "$name" "${REPO_ROOT}/components/${chart}/helm" \
    -n hamq -f "${VALUES_DIR}/${vals}.yaml" \
    --timeout 4m --wait 2>&1 | grep -E "STATUS|deployed|Error" | head -3
  log "[$name] done"
}

deploy hamq-producer   producer   producer-test
deploy hamq-consumer   consumer   consumer-test
deploy hamq-arbiter    arbiter    arbiter-test
deploy hamq-controller controller controller-test


# =============================================================================
# STEP 7 — Summary
# =============================================================================
step "7 — Done"

log "Pods:"
kubectl get pods -n hamq   | sed 's/^/  [hamq]  /'
kubectl get pods -n kafka  | sed 's/^/  [kafka] /'

log ""
log "Ingress:"
kubectl get ingress -n hamq | sed 's/^/  /'

log ""
log "Access from this host:"
log "  http://producer.${DOMAIN}    (admin / admin)"
log "  http://consumer.${DOMAIN}    (admin / admin)"
log "  http://arbiter.${DOMAIN}     (admin / admin)"
log "  http://controller.${DOMAIN}  (admin / admin)"
log ""
log "MetalLB IP: $TRAEFIK_IP  →  all four UIs via Traefik"
