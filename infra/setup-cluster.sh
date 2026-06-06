#!/usr/bin/env bash
# =============================================================================
# setup-cluster.sh
# Provisions a 3-node k3s Kubernetes cluster on KVM/libvirt
#
# Steps:
#   1. Install KVM stack  (qemu-kvm, libvirt, virtinst, cloud-image-utils)
#   2. Download Ubuntu 24.04 cloud base image
#   3. Build cloud-init seed ISOs and qcow2 overlay disks for each VM
#   4. Launch VMs with virt-install
#   5. Install k3s on the control-plane, join both workers via k3sup
#   6. Write KUBECONFIG to infra/kubeconfig
#
# Usage: sudo bash infra/setup-cluster.sh
#        (must run as root — libvirt image dir and virsh require it)
# =============================================================================

set -euo pipefail

# Force English output from all commands (system is in German locale)
export LANG=C LC_ALL=C

# ─── Logging helpers ─────────────────────────────────────────────────────────
log()   { printf '\033[0;32m[%s] [INFO]  %s\033[0m\n'  "$(date '+%H:%M:%S')" "$*" >&2; }
warn()  { printf '\033[0;33m[%s] [WARN]  %s\033[0m\n'  "$(date '+%H:%M:%S')" "$*" >&2; }
error() { printf '\033[0;31m[%s] [ERROR] %s\033[0m\n'  "$(date '+%H:%M:%S')" "$*" >&2; exit 1; }
step()  {
  echo >&2
  printf '\033[1;34m%s\033[0m\n' "══════════════════════════════════════════════════════" >&2
  printf '\033[1;34m  STEP: %s\033[0m\n' "$*" >&2
  printf '\033[1;34m%s\033[0m\n' "══════════════════════════════════════════════════════" >&2
}
banner() {
  echo >&2
  printf '\033[1;32m%s\033[0m\n' "╔══════════════════════════════════════════════════════╗" >&2
  printf '\033[1;32m  %s\033[0m\n' "$*" >&2
  printf '\033[1;32m%s\033[0m\n' "╚══════════════════════════════════════════════════════╝" >&2
}

# ─── Constants ───────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="/tmp/k3s-setup"
IMG_DIR="/var/lib/libvirt/images"
BASE_IMAGE_URL="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
BASE_IMAGE="${IMG_DIR}/ubuntu-24.04-base.img"
SSH_KEY_PATH="/root/.ssh/k3s-cluster"
K3SUP_BIN="/usr/local/bin/k3sup"
KUBECONFIG_OUT="${SCRIPT_DIR}/kubeconfig"

VMS=(k3s-cp k3s-w1 k3s-w2)
declare -A VM_RAM=( [k3s-cp]=2048 [k3s-w1]=2048 [k3s-w2]=2048 )
declare -A VM_VCPU=( [k3s-cp]=2    [k3s-w1]=2    [k3s-w2]=2    )
declare -A VM_IPS=()

# ─── Root guard ──────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || error "This script must run as root (sudo bash $0)"
[[ -c /dev/kvm ]]  || error "/dev/kvm not present — are KVM kernel modules loaded? (lsmod | grep kvm)"

log "Script directory : $SCRIPT_DIR"
log "Work directory   : $WORK_DIR"
log "Image directory  : $IMG_DIR"
log "SSH key          : $SSH_KEY_PATH"
log "Kubeconfig out   : $KUBECONFIG_OUT"


# =============================================================================
# STEP 1 — Install KVM stack
# =============================================================================
step "1/6 — Install KVM stack"

REQUIRED_PKGS=(
  qemu-kvm
  libvirt-daemon-system
  libvirt-clients
  virtinst
  cloud-image-utils
  genisoimage
  libosinfo-bin        # provides osinfo-query
)

log "Checking which packages need installation..."
TO_INSTALL=()
for pkg in "${REQUIRED_PKGS[@]}"; do
  if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
    log "  [already installed] $pkg"
  else
    log "  [missing]           $pkg"
    TO_INSTALL+=("$pkg")
  fi
done

if [[ ${#TO_INSTALL[@]} -gt 0 ]]; then
  log "Running apt-get update..."
  apt-get update -qq

  log "Installing ${#TO_INSTALL[@]} package(s): ${TO_INSTALL[*]}"
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${TO_INSTALL[@]}"
  log "Package installation finished"
else
  log "All required packages are already installed — skipping apt"
fi

log "Enabling and starting libvirtd service..."
systemctl enable --now libvirtd
log "libvirtd active status : $(systemctl is-active libvirtd)"
log "libvirtd enabled status: $(systemctl is-enabled libvirtd)"

log "Checking default libvirt NAT network..."
if ! virsh net-info default &>/dev/null; then
  error "Default libvirt network not found — this is unexpected after libvirt install"
fi

log "Ensuring default network is active (start is idempotent)..."
virsh net-start default 2>/dev/null && log "Default network started" || log "Default network already active"

virsh net-autostart default
log "Default network set to autostart"

LIBVIRT_BRIDGE=$(virsh net-info default | awk '/Bridge:/{print $2}')
LIBVIRT_NET_RANGE=$(virsh net-dumpxml default | grep -oP '(?<=address=")[0-9.]+(?=".*prefix)' | head -1 || true)
log "Libvirt bridge  : $LIBVIRT_BRIDGE"
log "Full network XML:"
virsh net-dumpxml default | sed 's/^/    /'

log "Step 1 complete — KVM stack ready"


# =============================================================================
# STEP 2 — Download Ubuntu 24.04 cloud image
# =============================================================================
step "2/6 — Ubuntu 24.04 cloud base image"

mkdir -p "$IMG_DIR" "$WORK_DIR"
log "Ensured directories: $IMG_DIR  $WORK_DIR"

if [[ -f "$BASE_IMAGE" ]]; then
  BASE_SIZE=$(du -h "$BASE_IMAGE" | cut -f1)
  log "Base image already present — skipping download"
  log "  Path : $BASE_IMAGE"
  log "  Size : $BASE_SIZE"
else
  log "Downloading Ubuntu 24.04 cloud image..."
  log "  Source : $BASE_IMAGE_URL"
  log "  Dest   : $BASE_IMAGE"
  wget --progress=bar:force:noscroll -O "$BASE_IMAGE" "$BASE_IMAGE_URL" 2>&1 | \
    while IFS= read -r line; do log "  wget: $line"; done || true
  log "Download complete. Size: $(du -h "$BASE_IMAGE" | cut -f1)"
fi

log "Base image info:"
qemu-img info "$BASE_IMAGE" | sed 's/^/  /'

log "Step 2 complete — base image ready"


# =============================================================================
# SSH keypair (between steps 2 and 3)
# =============================================================================
step "SSH keypair for VM access"

if [[ -f "$SSH_KEY_PATH" && -f "${SSH_KEY_PATH}.pub" ]]; then
  log "SSH keypair already exists at $SSH_KEY_PATH"
  log "  Fingerprint: $(ssh-keygen -lf "${SSH_KEY_PATH}.pub")"
else
  log "Generating new ed25519 keypair at $SSH_KEY_PATH..."
  ssh-keygen -t ed25519 -N '' -C 'k3s-cluster-key' -f "$SSH_KEY_PATH"
  log "Keypair generated"
  log "  Private : $SSH_KEY_PATH"
  log "  Public  : ${SSH_KEY_PATH}.pub"
  log "  Fingerprint: $(ssh-keygen -lf "${SSH_KEY_PATH}.pub")"
fi

SSH_PUBKEY=$(cat "${SSH_KEY_PATH}.pub")
log "Public key: $SSH_PUBKEY"


# =============================================================================
# STEP 3 — Cloud-init seed ISOs and disk images
# =============================================================================
step "3/6 — Cloud-init configs and overlay disk images"

# Detect best OS variant for virt-install
detect_os_variant() {
  if osinfo-query os 2>/dev/null | grep -q "ubuntu24.04"; then
    echo "ubuntu24.04"
  elif osinfo-query os 2>/dev/null | grep -q "ubuntu22.04"; then
    warn "ubuntu24.04 not in osinfo-db, using ubuntu22.04 as variant (functionally identical)"
    echo "ubuntu22.04"
  else
    warn "Could not find ubuntu variant in osinfo-db, using generic linux"
    echo "linux2022"
  fi
}
OS_VARIANT=$(detect_os_variant)
log "virt-install os-variant: $OS_VARIANT"

create_vm_assets() {
  local vmname=$1
  local disk="${IMG_DIR}/${vmname}.qcow2"
  local ci_dir="${WORK_DIR}/${vmname}-ci"
  local seed_iso="${WORK_DIR}/${vmname}-seed.iso"

  log "[$vmname] ── creating assets"

  # Overlay disk
  if [[ -f "$disk" ]]; then
    log "[$vmname]   disk image exists: $disk ($(du -h "$disk" | cut -f1))"
  else
    log "[$vmname]   creating 20G qcow2 overlay on base image..."
    qemu-img create -f qcow2 -F qcow2 -b "$BASE_IMAGE" "$disk" 20G
    log "[$vmname]   disk created: $disk"
    qemu-img info "$disk" | sed "s/^/[$vmname]     /"
  fi

  # Seed ISO
  if [[ -f "$seed_iso" ]]; then
    log "[$vmname]   seed ISO exists: $seed_iso ($(du -h "$seed_iso" | cut -f1))"
    return
  fi

  log "[$vmname]   building cloud-init files in $ci_dir"
  mkdir -p "$ci_dir"

  # meta-data
  cat > "${ci_dir}/meta-data" <<EOF
instance-id: ${vmname}-001
local-hostname: ${vmname}
EOF
  log "[$vmname]   meta-data:"
  cat "${ci_dir}/meta-data" | sed "s/^/[$vmname]     /"

  # user-data
  cat > "${ci_dir}/user-data" <<EOF
#cloud-config
hostname: ${vmname}
manage_etc_hosts: true

users:
  - name: ubuntu
    gecos: Ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys:
      - ${SSH_PUBKEY}

package_update: true
packages:
  - curl
  - qemu-guest-agent

runcmd:
  - systemctl enable --now ssh
  - systemctl enable --now qemu-guest-agent
  - echo "$(date): cloud-init done on ${vmname}" >> /var/log/k3s-provision.log
EOF
  log "[$vmname]   user-data written ($(wc -l < "${ci_dir}/user-data") lines)"

  log "[$vmname]   generating seed ISO with cloud-localds..."
  cloud-localds "$seed_iso" "${ci_dir}/user-data" "${ci_dir}/meta-data"
  log "[$vmname]   seed ISO: $seed_iso ($(du -h "$seed_iso" | cut -f1))"
}

for vm in "${VMS[@]}"; do
  create_vm_assets "$vm"
  echo
done

log "Step 3 complete — all VM assets ready"
log "Disk images:"
ls -lh "${IMG_DIR}"/k3s-*.qcow2 2>/dev/null | sed 's/^/  /' || true
log "Seed ISOs:"
ls -lh "${WORK_DIR}"/*-seed.iso 2>/dev/null | sed 's/^/  /' || true


# =============================================================================
# STEP 4 — Launch VMs
# =============================================================================
step "4/6 — Launch VMs with virt-install"

launch_vm() {
  local vmname=$1
  local disk="${IMG_DIR}/${vmname}.qcow2"
  local seed_iso="${WORK_DIR}/${vmname}-seed.iso"
  local ram=${VM_RAM[$vmname]}
  local vcpu=${VM_VCPU[$vmname]}

  if virsh dominfo "$vmname" &>/dev/null; then
    log "[$vmname] Domain already defined in libvirt"
    local state
    state=$(virsh domstate "$vmname" | tr -d ' \n')
    log "[$vmname]   current state: $state"
    if [[ "$state" != "running" ]]; then
      log "[$vmname]   starting domain..."
      virsh start "$vmname"
      log "[$vmname]   domain started"
    else
      log "[$vmname]   already running — nothing to do"
    fi
    return
  fi

  log "[$vmname] Launching new VM via virt-install:"
  log "[$vmname]   os-variant : $OS_VARIANT"
  log "[$vmname]   vCPUs      : $vcpu"
  log "[$vmname]   RAM        : ${ram} MB"
  log "[$vmname]   boot disk  : $disk"
  log "[$vmname]   cloud-init : $seed_iso"
  log "[$vmname]   network    : default (NAT/DHCP)"

  virt-install \
    --name        "$vmname" \
    --ram         "$ram" \
    --vcpus       "$vcpu" \
    --cpu         host \
    --disk        "path=${disk},format=qcow2,bus=virtio,cache=none" \
    --disk        "path=${seed_iso},device=cdrom,readonly=on" \
    --os-variant  "$OS_VARIANT" \
    --network     "network=default,model=virtio" \
    --graphics    none \
    --serial      pty \
    --console     pty,target.type=virtio \
    --noautoconsole \
    --import

  log "[$vmname] VM launched successfully"
}

for vm in "${VMS[@]}"; do
  launch_vm "$vm"
  echo
done

log "All domains after launch:"
virsh list --all | sed 's/^/  /'


# ─── Wait for DHCP leases ────────────────────────────────────────────────────
step "Waiting for VMs to acquire DHCP leases"

get_vm_ip() {
  local vmname=$1
  local mac
  mac=$(virsh domiflist "$vmname" 2>/dev/null | awk '/network/{print $5}')
  [[ -z "$mac" ]] && { echo ""; return; }
  local ip
  ip=$(virsh net-dhcp-leases default 2>/dev/null \
        | grep -i "$mac" \
        | awk '{print $5}' \
        | cut -d/ -f1 \
        | head -1)
  echo "$ip"
}

wait_for_ip() {
  local vmname=$1
  local max_attempts=60
  local attempt=0
  local sleep_secs=10
  log "[$vmname] Polling for DHCP lease (max ${max_attempts} × ${sleep_secs}s)..."
  while true; do
    local ip
    ip=$(get_vm_ip "$vmname")
    if [[ -n "$ip" ]]; then
      log "[$vmname] DHCP lease acquired: $ip"
      echo "$ip"
      return 0
    fi
    attempt=$((attempt + 1))
    if [[ $attempt -ge $max_attempts ]]; then
      error "[$vmname] Timed out waiting for DHCP lease (${max_attempts} attempts)"
    fi
    log "[$vmname]   attempt $attempt/$max_attempts — no lease yet, sleeping ${sleep_secs}s..."
    sleep "$sleep_secs"
  done
}

for vm in "${VMS[@]}"; do
  VM_IPS[$vm]=$(wait_for_ip "$vm")
done

log "IP summary:"
for vm in "${VMS[@]}"; do
  log "  $vm  =>  ${VM_IPS[$vm]}"
done

log "Full DHCP lease table:"
virsh net-dhcp-leases default | sed 's/^/  /'


# ─── Wait for SSH ─────────────────────────────────────────────────────────────
step "Waiting for SSH on all VMs"

wait_for_ssh() {
  local vmname=$1
  local ip=$2
  local max_attempts=72
  local attempt=0
  local sleep_secs=10
  log "[$vmname] Waiting for SSH at ubuntu@${ip} (max ${max_attempts} × ${sleep_secs}s = ~12 min)..."
  while ! ssh \
      -o StrictHostKeyChecking=no \
      -o ConnectTimeout=5 \
      -o BatchMode=yes \
      -o LogLevel=ERROR \
      -i "$SSH_KEY_PATH" \
      "ubuntu@${ip}" 'echo ssh-ok' &>/dev/null; do
    attempt=$((attempt + 1))
    if [[ $attempt -ge $max_attempts ]]; then
      error "[$vmname] SSH timeout after $max_attempts attempts on $ip"
    fi
    log "[$vmname]   attempt $attempt/$max_attempts — SSH not ready, sleeping ${sleep_secs}s..."
    sleep "$sleep_secs"
  done
  log "[$vmname] SSH ready at $ip"

  # Log cloud-init completion status
  local ci_status
  ci_status=$(ssh \
    -o StrictHostKeyChecking=no -o BatchMode=yes -o LogLevel=ERROR \
    -i "$SSH_KEY_PATH" "ubuntu@${ip}" \
    'cloud-init status 2>/dev/null || echo unknown')
  log "[$vmname]   cloud-init status: $ci_status"
}

for vm in "${VMS[@]}"; do
  wait_for_ssh "$vm" "${VM_IPS[$vm]}"
done

log "All VMs are accessible via SSH"


# =============================================================================
# STEP 5 — Install k3s via k3sup
# =============================================================================
step "5/6 — Install k3sup and deploy k3s"

# Install k3sup binary
if [[ -x "$K3SUP_BIN" ]]; then
  log "k3sup already installed: $($K3SUP_BIN version 2>&1 | head -1)"
else
  log "Downloading k3sup from get.k3sup.dev..."
  curl -sLS https://get.k3sup.dev | sh
  if [[ -x "$K3SUP_BIN" ]]; then
    log "k3sup installed: $($K3SUP_BIN version 2>&1 | head -1)"
  else
    error "k3sup not found at $K3SUP_BIN after install script ran"
  fi
fi

CP_IP="${VM_IPS[k3s-cp]}"
W1_IP="${VM_IPS[k3s-w1]}"
W2_IP="${VM_IPS[k3s-w2]}"

log "Control plane IP : $CP_IP"
log "Worker 1 IP      : $W1_IP"
log "Worker 2 IP      : $W2_IP"

# ── Install k3s server on control plane ──────────────────────────────────────
log "Installing k3s server on k3s-cp ($CP_IP)..."
log "  kubeconfig destination: $KUBECONFIG_OUT"
log "  context name          : k3s-hamq"

k3sup install \
  --ip            "$CP_IP" \
  --user          ubuntu \
  --ssh-key       "$SSH_KEY_PATH" \
  --local-path    "$KUBECONFIG_OUT" \
  --context       k3s-hamq \
  --k3s-extra-args "--node-label role=control-plane"

log "k3s server installation complete"

log "Waiting 20s for k3s API server to stabilize..."
sleep 20

log "Verifying API server reachability from host..."
KUBECONFIG="$KUBECONFIG_OUT" kubectl cluster-info | sed 's/^/  /'

# ── Join worker 1 ─────────────────────────────────────────────────────────────
log "Joining k3s-w1 ($W1_IP) as agent..."
k3sup join \
  --ip         "$W1_IP" \
  --server-ip  "$CP_IP" \
  --user       ubuntu \
  --ssh-key    "$SSH_KEY_PATH" \
  --k3s-extra-args "--node-label role=worker"

log "k3s-w1 joined cluster"

# ── Join worker 2 ─────────────────────────────────────────────────────────────
log "Joining k3s-w2 ($W2_IP) as agent..."
k3sup join \
  --ip         "$W2_IP" \
  --server-ip  "$CP_IP" \
  --user       ubuntu \
  --ssh-key    "$SSH_KEY_PATH" \
  --k3s-extra-args "--node-label role=worker"

log "k3s-w2 joined cluster"

log "Waiting 15s for agents to register..."
sleep 15

log "Current node list:"
KUBECONFIG="$KUBECONFIG_OUT" kubectl get nodes -o wide | sed 's/^/  /'


# =============================================================================
# STEP 6 — Finalise KUBECONFIG
# =============================================================================
step "6/6 — KUBECONFIG"

log "Kubeconfig path: $KUBECONFIG_OUT"

# k3sup writes the API server as https://127.0.0.1:6443 in some versions —
# patch it to the real CP IP so kubectl works from the host.
if grep -q '127.0.0.1' "$KUBECONFIG_OUT" 2>/dev/null; then
  log "Patching kubeconfig: 127.0.0.1 -> $CP_IP"
  sed -i "s|https://127.0.0.1:6443|https://${CP_IP}:6443|g" "$KUBECONFIG_OUT"
  log "Patch applied"
else
  log "Kubeconfig already uses correct server address"
fi

log "Final kubeconfig server entry: $(grep 'server:' "$KUBECONFIG_OUT")"

log "Final connectivity check — nodes:"
KUBECONFIG="$KUBECONFIG_OUT" kubectl get nodes -o wide | sed 's/^/  /'

log "System pods:"
KUBECONFIG="$KUBECONFIG_OUT" kubectl get pods -A | sed 's/^/  /'

# Optionally add to /root/.kube/config if it doesn't already have this context
if ! kubectl config get-contexts k3s-hamq &>/dev/null 2>&1; then
  log "Merging k3s-hamq context into /root/.kube/config..."
  mkdir -p /root/.kube
  if [[ -f /root/.kube/config ]]; then
    KUBECONFIG="/root/.kube/config:${KUBECONFIG_OUT}" \
      kubectl config view --flatten > /tmp/kubeconfig-merged
    mv /tmp/kubeconfig-merged /root/.kube/config
    chmod 600 /root/.kube/config
    log "Merged into /root/.kube/config"
  else
    cp "$KUBECONFIG_OUT" /root/.kube/config
    chmod 600 /root/.kube/config
    log "Copied to /root/.kube/config"
  fi
fi

log "Setting k3s-hamq as current context in /root/.kube/config..."
kubectl --kubeconfig=/root/.kube/config config use-context k3s-hamq
log "Active context: $(kubectl --kubeconfig=/root/.kube/config config current-context)"

# Fix ownership so boike user can also use the kubeconfig
chown boike:boike "$KUBECONFIG_OUT"
chmod 600 "$KUBECONFIG_OUT"
log "Kubeconfig ownership: $(ls -la "$KUBECONFIG_OUT")"


# =============================================================================
# Done
# =============================================================================
banner "Cluster provisioning complete"

log ""
log "  VMs:"
for vm in "${VMS[@]}"; do
  log "    %-12s  %s" "$vm" "${VM_IPS[$vm]}"
done
log ""
log "  SSH access:"
log "    ssh -i $SSH_KEY_PATH ubuntu@${CP_IP}   # control-plane"
log "    ssh -i $SSH_KEY_PATH ubuntu@${W1_IP}   # worker 1"
log "    ssh -i $SSH_KEY_PATH ubuntu@${W2_IP}   # worker 2"
log ""
log "  Kubeconfig: $KUBECONFIG_OUT"
log ""
log "  Quick test:"
log "    export KUBECONFIG=$KUBECONFIG_OUT"
log "    kubectl get nodes -o wide"
log ""
log "  To persist across shells, add to /root/.bashrc or /home/boike/.bashrc:"
log "    export KUBECONFIG=$KUBECONFIG_OUT"
log ""
