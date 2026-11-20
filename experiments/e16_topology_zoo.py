#!/usr/bin/env python3
"""E16: Control-plane admission latency scaling and rule-count proxy on Geant2012 vs Team16 7-switch."""

from __future__ import annotations

import argparse
import csv
import math
import os
import random
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import networkx as nx


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def load_geant_topology(graphml_path: Path):
    """Load GraphML as simple undirected graph s1..sN with ITU-T G.114 5 us/km delay and 100 Mbps."""
    import topology.topology_spec as topo_spec

    raw = nx.read_graphml(str(graphml_path))
    simple = nx.Graph()
    node_order = sorted(raw.nodes(), key=lambda x: str(x))
    mapping = {orig: f"s{idx + 1}" for idx, orig in enumerate(node_order)}

    coords: Dict[str, Tuple[float, float]] = {}
    for orig, sname in mapping.items():
        attrs = raw.nodes[orig]
        simple.add_node(sname)
        lat = attrs.get("Latitude")
        lon = attrs.get("Longitude")
        if lat is not None and lon is not None:
            try:
                coords[sname] = (float(lat), float(lon))
            except (TypeError, ValueError):
                pass

    fallback_edges = 0
    for u_orig, v_orig in raw.edges():
        if u_orig == v_orig:
            continue
        u = mapping[u_orig]
        v = mapping[v_orig]
        if simple.has_edge(u, v):
            continue
        if u in coords and v in coords:
            dist_km = _haversine_km(coords[u][0], coords[u][1], coords[v][0], coords[v][1])
            delay_ms = max(0.05, dist_km * 0.005)
        else:
            delay_ms = 1.0
            fallback_edges += 1
        lo, hi = sorted((u, v), key=lambda s: int(s[1:]))
        simple.add_edge(
            u,
            v,
            name=f"{lo}-{hi}",
            bw_mbps=100.0,
            delay_ms=delay_ms,
            inferred=False,
        )

    hosts = tuple(
        topo_spec.Host(
            name=f"h{idx + 1}",
            ip=f"10.0.{idx + 1}.1",
            switch=f"s{idx + 1}",
            role="geant-host",
        )
        for idx in range(len(node_order))
    )

    port_map: Dict[Tuple[str, str], int] = {}
    for h in hosts:
        port_map[(h.switch, h.name)] = 1
    port_counts = {s: 1 for s in simple.nodes()}
    for u, v in simple.edges():
        port_counts[u] += 1
        port_map[(u, v)] = port_counts[u]
        port_counts[v] += 1
        port_map[(v, u)] = port_counts[v]

    return simple, hosts, port_map, fallback_edges


def build_team16_port_map() -> Dict[Tuple[str, str], int]:
    from topology.topology_spec import HOSTS, LINKS, SWITCHES

    pm: Dict[Tuple[str, str], int] = {}
    counts = {sw: 0 for sw in SWITCHES}
    for h in HOSTS:
        counts[h.switch] += 1
        pm[(h.switch, h.name)] = counts[h.switch]
    for link in LINKS:
        counts[link.a] += 1
        pm[(link.a, link.b)] = counts[link.a]
        counts[link.b] += 1
        pm[(link.b, link.a)] = counts[link.b]
    return pm


def benchmark_topology(
    topo_name: str,
    graph: nx.Graph,
    hosts: tuple,
    port_map: Dict[Tuple[str, str], int],
    ks: List[int],
    runs: int,
    raw_dir: Path,
) -> List[dict]:
    import topology.topology_spec as topo_spec
    import src.pathing.compute as compute_mod
    import src.admission.residual as residual_mod
    import src.enforcement.flowmod as flowmod_mod
    from src.admission.feasibility import assess
    from src.common import db as dbm
    from src.common.models import Guarantee, IntentRecord, IntentState, Match

    orig_spec_hosts = topo_spec.HOSTS
    orig_comp_hosts = compute_mod.HOSTS
    orig_flow_hosts = flowmod_mod.HOSTS
    orig_spec_build = topo_spec.build_graph
    orig_res_build = residual_mod.build_graph

    topo_spec.HOSTS = hosts
    compute_mod.HOSTS = hosts
    flowmod_mod.HOSTS = hosts
    topo_spec.build_graph = lambda: graph.copy()
    residual_mod.build_graph = lambda: graph.copy()

    # Keep only pairs in the same connected component with distinct switches.
    components = {node: comp for comp in nx.connected_components(graph) for node in comp}
    valid_pairs = [
        (h_src, h_dst)
        for h_src in hosts
        for h_dst in hosts
        if h_src.switch != h_dst.switch and components[h_src.switch] == components[h_dst.switch]
    ]
    assert valid_pairs, f"No valid connected host pairs in {topo_name}"

    tmp_root = Path(tempfile.mkdtemp(prefix=f"team16-e16-{topo_name}-"))
    results = []
    try:
        for k in ks:
            for seed in range(1, runs + 1):
                db_path = tmp_root / f"{topo_name}_k{k:02d}_s{seed:02d}.db"
                if db_path.exists():
                    db_path.unlink()
                os.environ["TEAM16_DB_PATH"] = str(db_path)
                conn = dbm.connect()
                dbm.init_db(conn)

                rng = random.Random(seed * 1000 + k)
                admitted = []
                for idx in range(1, k + 1):
                    src_h, dst_h = rng.choice(valid_pairs)
                    rec = IntentRecord(
                        id=f"INT-{1000 + idx:04d}",
                        tenant=f"tenant-{idx}",
                        priority=2,
                        match=Match(
                            src=f"{src_h.ip}/32",
                            dst=f"{dst_h.ip}/32",
                            proto="udp",
                            dport=6000 + idx,
                        ),
                        guarantee=Guarantee(min_bandwidth_mbps=1.0),
                    )
                    decision, plan = assess(conn, rec, graph)
                    assert decision.admitted and plan is not None, (
                        f"{topo_name} k={k} seed={seed} failed admitting #{idx}: {decision.reason}"
                    )
                    rec.state = IntentState.ACTIVE
                    rec.current_path = plan
                    dbm.save_intent(conn, rec)
                    dbm.save_path(conn, plan)
                    admitted.append((rec, plan))

                probe_src, probe_dst = rng.choice(valid_pairs)
                probe_intent = IntentRecord(
                    id=f"INT-9{k:03d}",
                    tenant="probe-tenant",
                    priority=2,
                    match=Match(
                        src=f"{probe_src.ip}/32",
                        dst=f"{probe_dst.ip}/32",
                        proto="udp",
                        dport=7999,
                    ),
                    guarantee=Guarantee(min_bandwidth_mbps=1.0),
                )
                t0 = time.perf_counter()
                probe_decision, probe_plan = assess(conn, probe_intent, graph)
                latency_ms = (time.perf_counter() - t0) * 1000.0
                assert probe_decision.admitted and probe_plan is not None, (
                    f"{topo_name} k={k} seed={seed} probe failed: {probe_decision.reason}"
                )

                # Rule-count proxy across switches (software model)
                sw_counts: Dict[str, int] = defaultdict(int)
                for rec, plan in admitted:
                    rules = flowmod_mod.rules_for_path(plan, rec, port_map)
                    for r in rules:
                        sw_counts[r["switch"]] += 1
                max_rules = max(sw_counts.values()) if sw_counts else 0
                total_rules = sum(sw_counts.values())
                max_rules_strict_x2 = 2 * max_rules
                conn.close()

                out_path = raw_dir / f"redfill_e16_{topo_name}_k{k:02d}_seed{seed:02d}.csv"
                now_ts = int(time.time())
                with out_path.open("w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["run_id", "timestamp", "metric", "value", "unit"])
                    w.writerow([seed, now_ts, "admission_latency_ms", f"{latency_ms:.6f}", "ms"])
                    w.writerow([seed, now_ts, "max_rules_per_switch", max_rules, "entries"])
                    w.writerow([seed, now_ts, "max_rules_strict_x2", max_rules_strict_x2, "entries"])
                    w.writerow([seed, now_ts, "total_rules", total_rules, "entries"])
                    w.writerow([seed, now_ts, "active_intents", k, "count"])
                results.append({
                    "topology": topo_name,
                    "k": k,
                    "seed": seed,
                    "admission_latency_ms": latency_ms,
                    "max_rules": max_rules,
                    "max_rules_strict_x2": max_rules_strict_x2,
                    "out_path": out_path,
                })
            print(
                f"E16 {topo_name:14s} k={k:2d} ({runs} runs): "
                f"mean_lat={sum(r['admission_latency_ms'] for r in results[-runs:])/runs:.3f} ms, "
                f"max_rules_sw={max(r['max_rules'] for r in results[-runs:])}"
            )
    finally:
        topo_spec.HOSTS = orig_spec_hosts
        compute_mod.HOSTS = orig_comp_hosts
        flowmod_mod.HOSTS = orig_flow_hosts
        topo_spec.build_graph = orig_spec_build
        residual_mod.build_graph = orig_res_build
        shutil.rmtree(tmp_root, ignore_errors=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graphml",
        type=Path,
        default=Path("experiments/results/redfill_2026-11/E16/Geant2012.graphml"),
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("experiments/results/raw"))
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()

    os.environ.setdefault(
        "TEAM16_DB_PATH",
        str(Path(tempfile.gettempdir()) / "team16_e16_init.db"),
    )
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    ks = [1, 2, 4, 8, 16, 32, 64]

    import topology.topology_spec as topo_spec

    g7 = topo_spec.build_graph()
    h7 = topo_spec.HOSTS
    pm7 = build_team16_port_map()
    print(f"Team16 7-switch: nodes={g7.number_of_nodes()} links={g7.number_of_edges()}")
    benchmark_topology("team16_7sw", g7, h7, pm7, ks, args.runs, args.raw_dir)

    if args.graphml.exists():
        gg, hg, pmg, fallback_edges = load_geant_topology(args.graphml)
        print(
            f"Geant2012: nodes={gg.number_of_nodes()} links={gg.number_of_edges()} "
            f"fallback_1ms_edges={fallback_edges}"
        )
        benchmark_topology("geant2012", gg, hg, pmg, ks, args.runs, args.raw_dir)
    else:
        print(f"SKIP Geant2012: {args.graphml} not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
