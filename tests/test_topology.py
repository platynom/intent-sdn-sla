"""
ST-2 gate test: the topology is reproducible and can actually be re-planned on.

This is the acceptance test for brief ST-02. It reasons about the same data the
Mininet script consumes, so a topology that passes here is the topology that boots.

The load-bearing test is `test_three_link_disjoint_paths_exist`. If that fails there
is nowhere to re-plan to, the closed loop is untestable, and the whole project stalls.
"""

from __future__ import annotations

import pytest

nx = pytest.importorskip("networkx")

from topology.topology_spec import (  # noqa: E402
    CRITICAL_PAIR,
    HOSTS,
    LINKS,
    REQUIRED_DISJOINT_PATHS,
    SWITCHES,
    build_graph,
    host_by_name,
    link_names,
    path_bottleneck_mbps,
    path_delay_ms,
)


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #

def test_switch_and_host_counts():
    assert len(SWITCHES) == 7
    assert len(HOSTS) == 8, "the plan specifies an 8-host topology"


def test_every_host_sits_on_a_real_switch():
    for h in HOSTS:
        assert h.switch in SWITCHES, f"{h.name} is attached to unknown {h.switch}"


def test_host_ips_are_unique_and_sequential():
    ips = [h.ip for h in HOSTS]
    assert len(set(ips)) == len(ips), "duplicate host IP"
    for i, h in enumerate(HOSTS, start=1):
        assert h.ip == f"10.0.0.{i}", (
            f"{h.name} must be 10.0.0.{i} to match Mininet's default allocation "
            "and the addresses used in intents/*.yaml"
        )


def test_graph_is_connected():
    assert nx.is_connected(build_graph()), "a partitioned topology is a bug"


def test_link_names_are_canonical_and_unique():
    names = link_names()
    assert len(set(names)) == len(names), "duplicate link"
    for name in names:
        lo, hi = name.split("-")
        assert int(lo[1:]) < int(hi[1:]), (
            f"{name} is not canonical; the intent grammar's avoid_links expects "
            "the lower-numbered switch first"
        )


# --------------------------------------------------------------------------- #
# The load-bearing property
# --------------------------------------------------------------------------- #

def test_three_link_disjoint_paths_exist():
    """
    Without alternatives there is nothing to re-plan to and the closed loop
    cannot be tested. The plan makes this mandatory.
    """
    g = build_graph()
    src = host_by_name(CRITICAL_PAIR[0]).switch
    dst = host_by_name(CRITICAL_PAIR[1]).switch

    count = len(list(nx.edge_disjoint_paths(g, src, dst)))
    assert count >= REQUIRED_DISJOINT_PATHS, (
        f"only {count} link-disjoint path(s) between {src} and {dst}; "
        f"the plan requires at least {REQUIRED_DISJOINT_PATHS}. "
        "Re-planning has nowhere to go."
    )


def test_the_three_paths_have_distinguishable_quality():
    """
    Re-planning is only observable if the alternatives differ. Three identical
    paths would make every metric flat.
    """
    g = build_graph()
    src = host_by_name(CRITICAL_PAIR[0]).switch
    dst = host_by_name(CRITICAL_PAIR[1]).switch
    paths = list(nx.edge_disjoint_paths(g, src, dst))[:REQUIRED_DISJOINT_PATHS]

    delays = sorted(path_delay_ms(p) for p in paths)
    bandwidths = sorted(path_bottleneck_mbps(p) for p in paths)

    assert len(set(delays)) == len(delays), f"paths have identical delay: {delays}"
    assert len(set(bandwidths)) == len(bandwidths), (
        f"paths have identical bandwidth: {bandwidths}"
    )
    assert max(delays) >= 2 * min(delays), (
        f"path delays {delays} are too close for a violation to be induced reliably"
    )


def test_no_single_link_failure_disconnects_the_critical_pair():
    g = build_graph()
    src = host_by_name(CRITICAL_PAIR[0]).switch
    dst = host_by_name(CRITICAL_PAIR[1]).switch
    for link in LINKS:
        h = g.copy()
        h.remove_edge(link.a, link.b)
        assert nx.has_path(h, src, dst), (
            f"removing {link.name} disconnects the critical pair; "
            "Scenario S5 (link failure) would be untestable on that link"
        )


# --------------------------------------------------------------------------- #
# Budgets are sane and match the intents we ship
# --------------------------------------------------------------------------- #

def test_link_budgets_are_positive_and_bounded():
    for link in LINKS:
        assert 0 < link.bw_mbps <= 1000, f"{link.name} bandwidth {link.bw_mbps}"
        assert 0 < link.delay_ms <= 100, f"{link.name} delay {link.delay_ms}"


def test_best_path_can_satisfy_the_urllc_intent():
    """
    intents/s1_urllc_baseline.yaml asks for 20 Mbps and 20 ms. At least one path
    must be able to meet it, or Scenario S1 fails by construction.
    """
    g = build_graph()
    src = host_by_name(CRITICAL_PAIR[0]).switch
    dst = host_by_name(CRITICAL_PAIR[1]).switch
    paths = list(nx.edge_disjoint_paths(g, src, dst))

    feasible = [
        p for p in paths
        if path_bottleneck_mbps(p) >= 20.0 and path_delay_ms(p) <= 20.0
    ]
    assert feasible, (
        "no path satisfies the baseline URLLC intent (20 Mbps, 20 ms). "
        f"paths: {[(path_bottleneck_mbps(p), path_delay_ms(p)) for p in paths]}"
    )


def test_at_least_one_path_violates_the_urllc_latency_bound():
    """
    The oscillation and re-plan scenarios need a *worse* alternative to move to.
    If every path satisfies the SLA, degradation cannot be demonstrated.
    """
    g = build_graph()
    src = host_by_name(CRITICAL_PAIR[0]).switch
    dst = host_by_name(CRITICAL_PAIR[1]).switch
    paths = list(nx.edge_disjoint_paths(g, src, dst))
    assert any(path_delay_ms(p) > 20.0 for p in paths), (
        "every path meets the 20 ms bound, so no scenario can induce a violation "
        "through re-routing alone"
    )


def test_infeasible_intent_really_is_infeasible():
    """intents/s3_infeasible.yaml asks for 500 Mbps. No path may satisfy it."""
    g = build_graph()
    src = host_by_name("h7").switch
    dst = host_by_name("h8").switch
    if src == dst:
        pytest.skip("h7 and h8 share a switch; bandwidth check not meaningful")
    paths = list(nx.all_simple_paths(g, src, dst))
    assert all(path_bottleneck_mbps(p) < 500.0 for p in paths), (
        "Scenario S3 expects a REJECT, but some path can carry 500 Mbps"
    )
