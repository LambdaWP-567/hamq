#!/usr/bin/env bash
# =============================================================================
# teardown-cluster.sh
# Completely removes the 3-node k3s KVM cluster and all associated resources.
#
# Removes:
#   - k3s-cp, k3s-w1, k3s-w2 VMs (destroyed + undefined)
#   - qcow2 overlay disk images
#   - cloud-init seed ISOs and work directory
#   - k3s-hamq context from /root/.kube/config
#   - infra/kubeconfig
#
# Does NOT remove:
#   - Ubuntu 24.04 base image (expensive to re-download; use --purge to remove)
#   - KVM/libvirt packages
#   - SSH keypair at /root/.ssh/k3s-cluster
#   - k3sup binary
#
# Usage:
#   sudo bash infra/teardown-cluster.sh           # keep base image
#   sudo bash infra/teardown-cluster.sh --purge   # also remove base image + SSH key + k3sup
# =============================================================================

set -euo pipefail

PURGE=false
[[ "${1:-}" == "--purge" ]] && PURGE=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="/tmp/k3s-setup"
IMG_DIR="/var/lib/libvirt/images"
BASE_IMAGE="${IMG_DIR}/ubuntu-24.04-base.img"
SSH_KEY_PATH="/root/.ssh/k3s-cluster"
K3SUP_BIN="/usr/local/bin/k3sup"
KUBECONFIG_OUT="${SCRIPT_DIR}/kubeconfig"

VMS=(k3s-cp k3s-w1 k3s-w2)

log()   { printf '\033[0;32m[%s] [INFO]  %s\033[0m\n' "$(date '+%H:%M:%S')" "$*"; }
warn()  { printf '\033[0;33m[%s] [WARN]  %s\033[0m\n' "$(date '+%H:%M:%S')" "$*" >&2; }
step()  {
  echo
  printf '\033[1;34m══════════════════════════════════════════════════════\033[0m\n'
  printf '\033[1;34m  STEP: %s\033[0m\n' "$*"
  printf '\033[1;34m══════════════════════════════════════════════════════\033[0m\n'
}

[[ $EUID -eq 0 ]] || { echo "Run as root (sudo bash $0)"; exit 1; }

log "Teardown mode: PURGE=$PURGE"
log "VMs targeted  : ${VMS[*]}"
log "Image dir     : $IMG_DIR"
log "Work dir      : $WORK_DIR"

# ─── Destroy and undefine VMs ─────────────────────────────────────────────────
step "Destroy and undefine VMs"

for vm in "${VMS[@]}"; do
  if ! virsh dominfo "$vm" &>/dev/null; then
    log "[$vm] Not defined in libvirt — skipping"
    continue
  fi

  local_state=$(virsh domstate "$vm" 2>/dev/null | tr -d ' \n' || echo unknown)
  log "[$vm] Current state: $local_state"

  if [[ "$local_state" == "running" || "$local_state" == "paused" ]]; then
    log "[$vm] Destroying (force-stopping)..."
    virsh destroy "$vm"
    log "[$vm] Destroyed"
  fi

  log "[$vm] Undefining domain (removing from libvirt)..."
  virsh undefine "$vm" --remove-all-storage 2>/dev/null || virsh undefine "$vm"
  log "[$vm] Undefined"
done

log "Remaining domains:"
virsh list --all | sed 's/^/  /'

# ─── Remove disk images ───────────────────────────────────────────────────────
step "Remove overlay disk images"

for vm in "${VMS[@]}"; do
  disk="${IMG_DIR}/${vm}.qcow2"
  if [[ -f "$disk" ]]; then
    log "Removing $disk ($(du -h "$disk" | cut -f1))"
    rm -f "$disk"
    log "  Removed"
  else
    log "$disk not found — already clean"
  fi
done

# ─── Remove work directory (cloud-init ISOs, tmp files) ───────────────────────
step "Remove cloud-init work directory"

if [[ -d "$WORK_DIR" ]]; then
  log "Removing $WORK_DIR ..."
  rm -rf "$WORK_DIR"
  log "Removed"
else
  log "$WORK_DIR not found — already clean"
fi

# ─── Remove kubeconfig ────────────────────────────────────────────────────────
step "Remove kubeconfig"

if [[ -f "$KUBECONFIG_OUT" ]]; then
  log "Removing $KUBECONFIG_OUT"
  rm -f "$KUBECONFIG_OUT"
  log "Removed"
else
  log "$KUBECONFIG_OUT not found — already clean"
fi

# Remove k3s-hamq context from /root/.kube/config if present
if [[ -f /root/.kube/config ]] && grep -q 'k3s-hamq' /root/.kube/config; then
  log "Removing k3s-hamq context from /root/.kube/config..."
  kubectl config delete-context k3s-hamq 2>/dev/null || true
  kubectl config delete-cluster k3s-hamq 2>/dev/null || true
  kubectl config unset "users.k3s-hamq" 2>/dev/null || true
  log "Context removed"
fi

# ─── Purge extras (base image, SSH key, k3sup) ────────────────────────────────
if [[ "$PURGE" == true ]]; then
  step "PURGE — removing base image, SSH key, k3sup"

  if [[ -f "$BASE_IMAGE" ]]; then
    log "Removing base image $BASE_IMAGE ($(du -h "$BASE_IMAGE" | cut -f1))..."
    rm -f "$BASE_IMAGE"
    log "Removed"
  fi

  if [[ -f "$SSH_KEY_PATH" ]]; then
    log "Removing SSH private key $SSH_KEY_PATH"
    rm -f "$SSH_KEY_PATH" "${SSH_KEY_PATH}.pub"
    log "Removed"
  fi

  if [[ -x "$K3SUP_BIN" ]]; then
    log "Removing k3sup binary $K3SUP_BIN"
    rm -f "$K3SUP_BIN"
    log "Removed"
  fi
else
  log "Skipping base image / SSH key / k3sup (re-run with --purge to remove those too)"
fi

# ─── Summary ──────────────────────────────────────────────────────────────────
echo
printf '\033[1;32m══════════════════════════════════════════════════════\033[0m\n'
printf '\033[1;32m  Teardown complete\033[0m\n'
printf '\033[1;32m══════════════════════════════════════════════════════\033[0m\n'
log "Remaining images in $IMG_DIR:"
ls -lh "$IMG_DIR"/ 2>/dev/null | sed 's/^/  /' || log "  (empty)"
log ""
log "To fully re-provision: sudo bash infra/setup-cluster.sh"
log "To also wipe base image next teardown: sudo bash infra/teardown-cluster.sh --purge"
