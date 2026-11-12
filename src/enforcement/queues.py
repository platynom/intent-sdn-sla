"""
M4 OVS HTB queue configuration.

Configures OVS QoS and HTB queue records to enforce minimum bandwidth guarantees
on egress ports.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.common import db as dbm


class QueueConfigurationError(RuntimeError):
    """Raised when an OVS QoS or queue configuration command fails."""


def _run_cmd(cmd: list[str]) -> str:
    """Execute ovs-vsctl command and raise QueueConfigurationError on failure."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise QueueConfigurationError(
            f"ovs-vsctl command failed ({' '.join(cmd)}): {detail}".strip()
        ) from exc


def ensure_queue(
    switch: str,
    port: str,
    min_mbps: float,
    max_mbps: Optional[float] = None,
    egress_peer: Optional[str] = None,
    queue_id: Optional[int] = None,
    intent_id: Optional[str] = None,
    conn: Any = None,
) -> int:
    """
    Create or reuse an HTB QoS record on the specified switch port and configure a queue.

    Rates are converted from Mbps to bits per second (min_bps = min_mbps * 1_000_000).
    Reuses existing QoS record on the port if present to avoid duplicate ineffective QoS records.
    Returns the allocated deterministic queue id.
    """
    from topology.topology_spec import link_capacity_mbps

    link_cap_mbps: Optional[float] = None
    if egress_peer is not None:
        link_cap_mbps = link_capacity_mbps(switch, egress_peer)
    if max_mbps is None:
        if link_cap_mbps is None:
            raise ValueError("egress_peer is required when max_mbps is not provided")
        max_mbps = link_cap_mbps
    root_max_mbps = link_cap_mbps if link_cap_mbps is not None else max_mbps
    min_bps = int(min_mbps * 1_000_000)
    max_bps = int(max_mbps * 1_000_000)
    qos_max_bps = int(root_max_mbps * 1_000_000)

    owns_conn = False
    had_existing_row = False
    if queue_id is None:
        if intent_id is not None:
            if conn is None:
                conn = dbm.connect()
                owns_conn = True
            existing_rows = {
                (r["switch"], r["port"]) for r in dbm.intent_queues_for(conn, intent_id)
            }
            had_existing_row = (switch, port) in existing_rows
            queue_id = dbm.allocate_queue_id(
                conn, intent_id, switch, port, min_bps=min_bps, max_bps=max_bps
            )
        else:
            queue_id = 1

    try:
        # Check if a QoS record already exists on this port
        existing_qos = _run_cmd(["ovs-vsctl", "--if-exists", "get", "port", port, "qos"])
        existing_qos = existing_qos.strip("[]\"' \n")

        if existing_qos and existing_qos != "[]":
            _run_cmd([
                "ovs-vsctl",
                "--",
                "set",
                "qos",
                existing_qos,
                f"other-config:max-rate={qos_max_bps}",
                f"queues:{queue_id}=@q",
                "--",
                "--id=@q",
                "create",
                "queue",
                f"other-config:min-rate={min_bps}",
                f"other-config:max-rate={max_bps}",
            ])
        else:
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
                f"other-config:max-rate={qos_max_bps}",
                f"queues:{queue_id}=@q",
                "--",
                "--id=@q",
                "create",
                "queue",
                f"other-config:min-rate={min_bps}",
                f"other-config:max-rate={max_bps}",
            ])
    except Exception:
        if intent_id is not None and conn is not None and not had_existing_row:
            conn.execute(
                "DELETE FROM intent_queues WHERE intent_id = ? AND switch = ? AND port = ?",
                (intent_id, switch, port),
            )
            conn.commit()
        raise
    finally:
        if owns_conn and conn is not None:
            conn.close()

    return int(queue_id)


def remove_queue_entry(
    switch: str,
    port: str,
    queue_id: int,
    ignore_errors: bool = True,
) -> None:
    """Remove a single per-intent queue ID from a port's QoS record in OVS."""
    try:
        existing_qos = _run_cmd(["ovs-vsctl", "--if-exists", "get", "port", port, "qos"])
        existing_qos = existing_qos.strip("[]\"' \n")
        if not existing_qos or existing_qos == "[]":
            return
        queues_val = _run_cmd(["ovs-vsctl", "--if-exists", "get", "qos", existing_qos, "queues"])
        q_map: Dict[str, str] = {}
        if queues_val:
            for part in queues_val.replace("{", "").replace("}", "").split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    q_map[k.strip()] = v.strip()
        target_uuid = q_map.get(str(queue_id))
        _run_cmd(["ovs-vsctl", "remove", "qos", existing_qos, "queues", str(queue_id)])
        if target_uuid:
            _run_cmd(["ovs-vsctl", "--if-exists", "destroy", "queue", target_uuid])
    except Exception:
        if not ignore_errors:
            raise


def remove_intent_queues(
    conn: Any,
    intent_id: str,
    keep_ports: Optional[Iterable[Tuple[str, str]]] = None,
    ignore_errors: bool = True,
) -> List[Dict[str, Any]]:
    """Delete persisted queue allocations for intent_id (except keep_ports) and remove from OVS."""
    removed = dbm.delete_intent_queues(conn, intent_id, keep_ports=keep_ports)
    for row in removed:
        remove_queue_entry(
            row["switch"],
            row["port"],
            int(row["queue_id"]),
            ignore_errors=ignore_errors,
        )
    return removed


def update_intent_queue_rates(
    conn: Any,
    intent_id: str,
    min_mbps: float,
    ignore_errors: bool = True,
) -> None:
    """Update the enforced HTB min-rate for all queues belonging to intent_id (M1)."""
    rows = dbm.intent_queues_for(conn, intent_id)
    for row in rows:
        max_mbps = float(row["max_bps"]) / 1_000_000.0 if row.get("max_bps") else min_mbps
        try:
            ensure_queue(
                switch=row["switch"],
                port=row["port"],
                min_mbps=min_mbps,
                max_mbps=max_mbps,
                queue_id=int(row["queue_id"]),
                intent_id=intent_id,
                conn=conn,
            )
        except Exception:
            if not ignore_errors:
                raise


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
