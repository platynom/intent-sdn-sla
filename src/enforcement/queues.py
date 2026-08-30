"""
M4 OVS HTB queue configuration.

Configures OVS QoS and HTB queue records to enforce minimum bandwidth guarantees
on egress ports.
"""

from __future__ import annotations

import subprocess
from typing import Optional


def _run_cmd(cmd: list[str]) -> str:
    """Execute ovs-vsctl command safely."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def ensure_queue(
    switch: str,
    port: str,
    min_mbps: float,
    max_mbps: Optional[float] = None,
) -> int:
    """
    Create or reuse an HTB QoS record on the specified switch port and configure a queue.

    Rates are converted from Mbps to bits per second (min_bps = min_mbps * 1_000_000).
    Reuses existing QoS record on the port if present to avoid duplicate ineffective QoS records.
    Returns the queue id (e.g. 1).
    """
    min_bps = int(min_mbps * 1_000_000)
    max_bps_clause = f",other-config:max-rate={int(max_mbps * 1_000_000)}" if max_mbps is not None else ""

    # Check if a QoS record already exists on this port
    # ovs-vsctl get port <port> qos
    existing_qos = _run_cmd(["ovs-vsctl", "--if-exists", "get", "port", port, "qos"])
    existing_qos = existing_qos.strip("[]\"' \n")

    queue_id = 1

    if existing_qos and existing_qos != "[]":
        # Reuse existing QoS record: add/replace queue 1
        _run_cmd([
            "ovs-vsctl",
            "--",
            "set",
            "qos",
            existing_qos,
            f"queues:{queue_id}=@q",
            "--",
            "--id=@q",
            "create",
            "queue",
            f"other-config:min-rate={min_bps}{max_bps_clause}",
        ])
    else:
        # Create a new QoS record and attach to port
        _run_cmd([
            "ovs-vsctl",
            "--",
            "set",
            "port",
            port,
            "qos=@newqos",
            "--",
            "--id=@newqos",
            "create",
            "qos",
            "type=linux-htb",
            f"other-config:max-rate={min_bps * 10}",
            f"queues:{queue_id}=@q",
            "--",
            "--id=@q",
            "create",
            "queue",
            f"other-config:min-rate={min_bps}{max_bps_clause}",
        ])

    return queue_id


def clear_queues(switch: str, port: str) -> None:
    """
    Clear QoS and queues attached to a switch port. Safe to call when nothing is configured.
    """
    existing_qos = _run_cmd(["ovs-vsctl", "--if-exists", "get", "port", port, "qos"])
    existing_qos = existing_qos.strip("[]\"' \n")

    if existing_qos and existing_qos != "[]":
        # Get queue UUIDs to destroy them
        queues_val = _run_cmd(["ovs-vsctl", "--if-exists", "get", "qos", existing_qos, "queues"])
        # Clear port qos reference
        _run_cmd(["ovs-vsctl", "clear", "port", port, "qos"])
        # Destroy qos record
        _run_cmd(["ovs-vsctl", "--if-exists", "destroy", "qos", existing_qos])
        # Clean up queue records
        if queues_val:
            for part in queues_val.replace("{", "").replace("}", "").split(","):
                if "=" in part:
                    q_uuid = part.split("=")[1].strip()
                    if q_uuid:
                        _run_cmd(["ovs-vsctl", "--if-exists", "destroy", "queue", q_uuid])
