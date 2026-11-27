"""
M4 OVS HTB queue configuration.

Configures OVS QoS and HTB queue records to enforce minimum bandwidth guarantees
on egress ports.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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


# ---------------------------------------------------------------------------
# Link-emulation preservation (E14b finding)
#
# Mininet's TCLink emulates link delay with a ``netem`` qdisc under its own
# root qdisc.  Attaching an OVS ``linux-htb`` QoS record replaces the port's
# root qdisc, which silently removed that netem: a bandwidth-intent port lost
# its emulated delay.  We record the netem parameters before OVS touches the
# port and re-attach an identical netem under every HTB leaf class (one per
# OVS queue, including default queue 0) once ovs-vswitchd has created them.
# Outside Mininet (no netem present, or no ``tc``) this is a no-op.
# ---------------------------------------------------------------------------

# One lock per port: concurrent reroutes onto the same port must not race the
# "get qos" / "create qos" sequence (the last create would orphan the others'
# queues) or the netem restoration.  Under ryu-manager, threading is
# monkey-patched by eventlet, so these are green locks.
_PORT_LOCKS: Dict[str, threading.Lock] = {}
_PORT_LOCKS_GUARD = threading.Lock()


def _port_lock(port: str) -> threading.Lock:
    with _PORT_LOCKS_GUARD:
        return _PORT_LOCKS.setdefault(port, threading.Lock())


_NETEM_VALUE_KEYS = ("limit", "loss", "duplicate", "corrupt", "reorder", "rate")
_ROOT_CLASS = "1:fffe"


def _preserve_enabled() -> bool:
    return os.environ.get("TEAM16_PRESERVE_NETEM", "1") != "0"


def _run_tc(cmd: list[str]) -> str:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return (res.stdout or "").strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise QueueConfigurationError(f"tc command failed ({' '.join(cmd)}): {detail}".strip()) from exc


def _is_time(tok: str) -> bool:
    t = tok.lower()
    return any(t.endswith(u) for u in ("us", "ms", "s")) and t.rstrip("usm.").replace(".", "", 1).isdigit()


def parse_netem_args(line: str) -> Optional[List[str]]:
    """Extract re-appliable netem parameters from one ``tc qdisc show`` line."""
    toks = line.split()
    if "netem" not in toks:
        return None
    args: List[str] = []
    i = toks.index("netem") + 1
    while i < len(toks):
        tok = toks[i]
        if tok == "delay" and i + 1 < len(toks):
            args += ["delay", toks[i + 1]]
            i += 2
            if i < len(toks) and _is_time(toks[i]):  # jitter
                args.append(toks[i])
                i += 1
            continue
        if tok in _NETEM_VALUE_KEYS and i + 1 < len(toks):
            args += [tok, toks[i + 1]]
            i += 2
            continue
        i += 1
    return args or None


def capture_netem(port: str) -> Optional[List[str]]:
    """Return the netem parameters currently on ``port``, or None if there are none."""
    if not _preserve_enabled():
        return None
    try:
        out = _run_tc(["tc", "qdisc", "show", "dev", port])
    except QueueConfigurationError:
        return None
    for line in out.splitlines():
        args = parse_netem_args(line)
        if args:
            return args
    return None


def _htb_leaf_classes(port: str) -> List[str]:
    out = _run_tc(["tc", "class", "show", "dev", port])
    leaves = []
    for line in out.splitlines():
        toks = line.split()
        if len(toks) >= 3 and toks[0] == "class" and toks[1] == "htb":
            cid = toks[2]
            if cid.startswith("1:") and cid != _ROOT_CLASS:
                leaves.append(cid)
    return leaves


def _netem_parents(port: str) -> Set[str]:
    out = _run_tc(["tc", "qdisc", "show", "dev", port])
    parents = set()
    for line in out.splitlines():
        toks = line.split()
        if "netem" in toks and "parent" in toks:
            parents.add(toks[toks.index("parent") + 1])
    return parents


def queue_class_id(queue_id: int) -> str:
    """OVS linux-htb maps queue N to HTB class 1:(N+1); tc prints the minor in hex."""
    return f"1:{int(queue_id) + 1:x}"


def restore_netem(
    port: str,
    netem_args: List[str],
    required_queue_ids: Iterable[int],
    timeout_s: float = 3.0,
) -> List[str]:
    """Attach ``netem_args`` under every HTB leaf class on ``port`` that lacks one.

    Waits (ovs-vswitchd applies QoS asynchronously) until the classes for
    ``required_queue_ids`` exist.  Returns the class ids that received a netem.
    """
    required = {queue_class_id(q) for q in required_queue_ids}
    deadline = time.monotonic() + timeout_s
    while True:
        leaves = _htb_leaf_classes(port)
        if required.issubset(leaves):
            break
        if time.monotonic() >= deadline:
            raise QueueConfigurationError(
                f"HTB classes {sorted(required - set(leaves))} did not appear on {port}; "
                "cannot restore link emulation"
            )
        time.sleep(0.05)
    have = _netem_parents(port)
    added = []
    for cid in leaves:
        if cid not in have:
            _run_tc(["tc", "qdisc", "replace", "dev", port, "parent", cid, "netem", *netem_args])
            added.append(cid)
    return added


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

    with _port_lock(port):
        netem_args = capture_netem(port)

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
                    "queues:0=@q0",
                    f"queues:{queue_id}=@q",
                    "--",
                    # Default queue 0 (HTB class 1:1) carries traffic with no
                    # SET_QUEUE, so it stays shaped and keeps the link's netem.
                    "--id=@q0",
                    "create",
                    "queue",
                    f"other-config:max-rate={qos_max_bps}",
                    "--",
                    "--id=@q",
                    "create",
                    "queue",
                    f"other-config:min-rate={min_bps}",
                    f"other-config:max-rate={max_bps}",
                ])
            if netem_args:
                restore_netem(port, netem_args, [queue_id])
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
