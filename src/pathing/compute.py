"""
M3 Path Computation.

Ties Yen's k-shortest paths, guarantee pruning, and best-path selection together
to compute feasible PathPlans for admitted intents.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import networkx as nx

from src.common.models import IntentRecord, PathPlan
from topology.topology_spec import HOSTS
from .prune import prune, select_best
from .yen_ksp import k_shortest_paths


def _resolve_ip_to_switch(ip_str: str):
    """Switch this IP attaches to, or None if it is not in the topology."""
    """Resolve an IP address (with or without CIDR suffix) to its attached switch."""
    raw_ip = ip_str.split("/")[0].strip()
    for host in HOSTS:
        if host.ip == raw_ip:
            return host.switch
    return None


def compute_path(
    intent: IntentRecord,
    graph: nx.Graph,
    tenant_paths: Optional[Dict[str, List[List[str]]]] = None,
) -> Tuple[Optional[PathPlan], Dict[str, str]]:
    """
    Compute a feasible PathPlan for an intent.

    Resolves intent match source and destination to switches, computes candidate
    paths using Yen's algorithm (k=3), prunes candidates against the intent's
    guarantee, and selects the best surviving path.

    Returns:
        (PathPlan, {}) on success, or (None, rejection_reasons) if infeasible.
    """
    src_switch = _resolve_ip_to_switch(intent.match.src)
    dst_switch = _resolve_ip_to_switch(intent.match.dst)

    # An endpoint outside the topology is a user error, not a crash. M2 and the
    # audit log surface this string verbatim.
    for label, ip, switch in (
        ("src", intent.match.src, src_switch),
        ("dst", intent.match.dst, dst_switch),
    ):
        if switch is None:
            return None, {
                ip: f"{label} {ip} is not attached to any host in this topology"
            }

    candidates = k_shortest_paths(graph, source=src_switch, target=dst_switch, k=3, weight="delay_ms")
    if not candidates:
        return None, {"(all)": "no path in topology"}

    surviving, reasons = prune(
        paths=candidates,
        guarantee=intent.guarantee,
        graph=graph,
        tenant_paths=tenant_paths,
    )

    best_switches = select_best(surviving, graph)
    if not best_switches:
        return None, reasons

    # Calculate estimated latency and bottleneck capacity from the graph
    est_latency = 0.0
    bottleneck_bw = float("inf")
    for u, v in zip(best_switches, best_switches[1:]):
        edge_data = graph.get_edge_data(u, v, default={})
        est_latency += float(edge_data.get("delay_ms", 0.0))
        bw = float(edge_data.get("bw_mbps", 0.0))
        if bw < bottleneck_bw:
            bottleneck_bw = bw

    canonical_links = PathPlan.links_for(best_switches)
    plan = PathPlan(
        intent_id=intent.id,
        switches=tuple(best_switches),
        links=canonical_links,
        est_latency_ms=est_latency,
        bottleneck_mbps=bottleneck_bw if bottleneck_bw != float("inf") else 0.0,
    )
    return plan, {}
