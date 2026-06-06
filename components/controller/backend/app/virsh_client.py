from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

VIRSH_URI = "qemu:///system"
# Nodes that ARE the hypervisor host — virsh operations don't apply to them
HOST_NODES: frozenset[str] = frozenset({"cubecluster"})


async def _virsh(*args: str) -> tuple[int, str, str]:
    cmd = ["virsh", "-c", VIRSH_URI, *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    rc = proc.returncode or 0
    return rc, stdout.decode().strip(), stderr.decode().strip()


async def reset_node(domain: str) -> tuple[bool, str]:
    """Hard reset — equivalent to pressing the reset button on the VM."""
    rc, out, err = await _virsh("reset", domain)
    if rc == 0:
        return True, f"Domain {domain} hard-reset"
    return False, err or out


async def reboot_node(domain: str) -> tuple[bool, str]:
    """Graceful ACPI reboot of the VM."""
    rc, out, err = await _virsh("reboot", domain)
    if rc == 0:
        return True, f"Domain {domain} rebooting (ACPI)"
    return False, err or out


async def _get_interfaces(domain: str) -> list[str]:
    rc, out, _ = await _virsh("domiflist", domain)
    if rc != 0:
        return []
    interfaces = []
    for line in out.splitlines()[2:]:  # skip two header rows
        parts = line.split()
        if parts:
            interfaces.append(parts[0])
    return interfaces


async def cut_network(domain: str) -> tuple[bool, str]:
    """Set all VM network interfaces to link-down (simulates unplugging the NIC)."""
    ifaces = await _get_interfaces(domain)
    if not ifaces:
        return False, f"No interfaces found for domain {domain}"
    errors = []
    for iface in ifaces:
        rc, out, err = await _virsh("domif-setlink", domain, iface, "down")
        if rc != 0:
            errors.append(f"{iface}: {err or out}")
    if errors:
        return False, "; ".join(errors)
    return True, f"Network cut for {domain} (interfaces: {', '.join(ifaces)})"


async def restore_network(domain: str) -> tuple[bool, str]:
    """Restore all VM network interfaces to link-up."""
    ifaces = await _get_interfaces(domain)
    if not ifaces:
        return False, f"No interfaces found for domain {domain}"
    errors = []
    for iface in ifaces:
        rc, out, err = await _virsh("domif-setlink", domain, iface, "up")
        if rc != 0:
            errors.append(f"{iface}: {err or out}")
    if errors:
        return False, "; ".join(errors)
    return True, f"Network restored for {domain} (interfaces: {', '.join(ifaces)})"


def is_kvm_node(node_name: str) -> bool:
    """True when virsh operations are applicable to this node."""
    return node_name not in HOST_NODES
