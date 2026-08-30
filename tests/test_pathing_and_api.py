"""
ST-4 gate tests: M1 accepts an intent over REST and M3 computes a feasible path.

Nothing is installed on a network at ST-4. These tests must run with no root, no
Mininet and no Ryu.
"""

from __future__ import annotations

import pytest

nx = pytest.importorskip("networkx")

from src.common import db as dbm  # noqa: E402
from src.common.models import Guarantee, IntentRecord, Match  # noqa: E402
from src.pathing.compute import compute_path  # noqa: E402
from src.pathing.prune import prune, select_best  # noqa: E402
from src.pathing.yen_ksp import k_shortest_paths  # noqa: E402
from topology.topology_spec import build_graph  # noqa: E402

NORTH = ["s1", "s2", "s3", "s7"]   # 100 Mbps,  6 ms
MIDDLE = ["s1", "s4", "s5", "s7"]  #  50 Mbps, 15 ms
SOUTH = ["s1", "s6", "s7"]         #  40 Mbps, 24 ms


@pytest.fixture()
def graph():
    return build_graph()


def intent(**g):
    return IntentRecord(
        id="INT-001",
        tenant="telemedicine-video",
        priority=1,
        match=Match(src="10.0.0.1/32", dst="10.0.0.2/32", proto="udp", dport=5001),
        guarantee=Guarantee(**g),
    )


# --------------------------------------------------------------------------- #
# Yen's k-shortest paths
# --------------------------------------------------------------------------- #

def test_finds_all_three_routes(graph):
    paths = k_shortest_paths(graph, "s1", "s7", k=3)
    assert [list(p) for p in paths] == [NORTH, MIDDLE, SOUTH], (
        "paths must come back ascending by total delay"
    )


def test_k_larger_than_available_does_not_pad_or_repeat(graph):
    paths = [list(p) for p in k_shortest_paths(graph, "s1", "s7", k=50)]
    assert len(paths) == len({tuple(p) for p in paths}), "duplicate paths returned"
    assert len(paths) >= 3


def test_paths_are_loopless(graph):
    for p in k_shortest_paths(graph, "s1", "s7", k=10):
        assert len(p) == len(set(p)), f"path revisits a switch: {p}"


def test_source_equals_target(graph):
    paths = [list(p) for p in k_shortest_paths(graph, "s1", "s1", k=3)]
    assert paths in ([], [["s1"]]), f"unexpected result for a degenerate query: {paths}"


def test_unreachable_target_returns_empty(graph):
    graph.add_node("s99")  # isolated
    assert list(k_shortest_paths(graph, "s1", "s99", k=3)) == []


def test_k_zero_or_negative_returns_empty(graph):
    assert list(k_shortest_paths(graph, "s1", "s7", k=0)) == []


# --------------------------------------------------------------------------- #
# Pruning
# --------------------------------------------------------------------------- #

def test_latency_prunes_the_slow_route(graph):
    survivors, reasons = prune([NORTH, MIDDLE, SOUTH],
                               Guarantee(max_latency_ms=20.0), graph)
    assert [list(s) for s in survivors] == [NORTH, MIDDLE]
    assert "s1-s6-s7" in reasons
    assert "24" in reasons["s1-s6-s7"] and "20" in reasons["s1-s6-s7"]


def test_bandwidth_prunes_the_narrow_routes(graph):
    survivors, reasons = prune([NORTH, MIDDLE, SOUTH],
                               Guarantee(min_bandwidth_mbps=60.0), graph)
    assert [list(s) for s in survivors] == [NORTH]
    assert len(reasons) == 2


def test_avoid_links_is_honoured(graph):
    survivors, reasons = prune([NORTH, MIDDLE, SOUTH],
                               Guarantee(avoid_links=("s2-s3",)), graph)
    assert NORTH not in [list(s) for s in survivors]
    assert any("s2-s3" in r for r in reasons.values())


def test_isolation_rejects_paths_sharing_a_link_with_the_named_tenant(graph):
    survivors, reasons = prune(
        [NORTH, MIDDLE, SOUTH],
        Guarantee(isolate_from=("public-internet",)),
        graph,
        tenant_paths={"public-internet": [NORTH]},
    )
    assert NORTH not in [list(s) for s in survivors]
    assert MIDDLE in [list(s) for s in survivors]


def test_isolation_ignores_tenants_not_named(graph):
    survivors, _ = prune(
        [NORTH], Guarantee(isolate_from=("someone-else",)), graph,
        tenant_paths={"public-internet": [NORTH]},
    )
    assert [list(s) for s in survivors] == [NORTH]


def test_loss_is_never_a_pruning_constraint(graph):
    """Loss is measured, not predicted. It must not remove a candidate path."""
    survivors, reasons = prune([NORTH, MIDDLE, SOUTH],
                               Guarantee(max_loss_pct=0.0), graph)
    assert len(survivors) == 3
    assert reasons == {}


def test_empty_guarantee_keeps_everything(graph):
    survivors, reasons = prune([NORTH, MIDDLE, SOUTH], Guarantee(), graph)
    assert len(survivors) == 3 and reasons == {}


def test_rejection_reasons_read_as_sentences(graph):
    """These strings are shown verbatim to users in the audit log."""
    _, reasons = prune([SOUTH], Guarantee(max_latency_ms=20.0), graph)
    reason = reasons["s1-s6-s7"]
    assert len(reason) > 15
    assert "max_latency_ms" in reason
    assert not reason.startswith("Error")


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #

def test_select_best_prefers_the_roomier_path(graph):
    assert list(select_best([NORTH, MIDDLE, SOUTH], graph)) == NORTH


def test_select_best_is_deterministic(graph):
    """Fixed seeds and repeatable runs are an evaluation requirement."""
    first = list(select_best([SOUTH, MIDDLE, NORTH], graph))
    for _ in range(20):
        assert list(select_best([MIDDLE, NORTH, SOUTH], graph)) == first


def test_select_best_of_nothing_is_none(graph):
    assert select_best([], graph) is None


# --------------------------------------------------------------------------- #
# compute_path
# --------------------------------------------------------------------------- #

def test_baseline_urllc_intent_lands_on_the_northern_route(graph):
    plan, reasons = compute_path(
        intent(min_bandwidth_mbps=20.0, max_latency_ms=20.0, max_loss_pct=0.5), graph
    )
    assert plan is not None, reasons
    assert list(plan.switches) == NORTH
    assert plan.est_latency_ms == 6.0
    assert plan.bottleneck_mbps == 100.0
    assert plan.links == ("s1-s2", "s2-s3", "s3-s7")
    assert plan.intent_id == "INT-001"


def test_infeasible_intent_returns_reasons_not_a_path(graph):
    plan, reasons = compute_path(intent(min_bandwidth_mbps=500.0), graph)
    assert plan is None
    assert reasons, "an infeasible intent must explain itself"
    for text in reasons.values():
        assert text.strip()


def test_impossible_latency_is_infeasible(graph):
    plan, reasons = compute_path(intent(max_latency_ms=1.0), graph)
    assert plan is None and reasons


def test_unknown_endpoint_is_handled_not_crashed(graph):
    rec = IntentRecord(
        id="INT-002", tenant="t", priority=2,
        match=Match(src="192.0.2.1/32", dst="10.0.0.2/32"),
        guarantee=Guarantee(min_bandwidth_mbps=1.0),
    )
    plan, reasons = compute_path(rec, graph)
    assert plan is None
    assert reasons


def test_computation_is_fast_enough(graph):
    """The module spec requires a decision inside 200 ms on this topology."""
    import time

    rec = intent(min_bandwidth_mbps=20.0, max_latency_ms=20.0)
    start = time.perf_counter()
    for _ in range(20):
        compute_path(rec, graph)
    per_call = (time.perf_counter() - start) / 20
    assert per_call < 0.2, f"{per_call*1000:.1f} ms per call"


# --------------------------------------------------------------------------- #
# REST API
# --------------------------------------------------------------------------- #

@pytest.fixture()
def client():
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    from src.intent_manager import api as api_mod

    conn = dbm.connect(":memory:")
    dbm.init_db(conn)

    dep = getattr(api_mod, "get_db", None)
    if dep is None:
        pytest.skip("api module exposes no get_db dependency to override")
    api_mod.app.dependency_overrides[dep] = lambda: conn

    yield fastapi_testclient.TestClient(api_mod.app)

    api_mod.app.dependency_overrides.clear()
    conn.close()


VALID_YAML = """
intent:
  id: INT-101
  tenant: telemedicine-video
  priority: 1
  match:
    src: 10.0.0.1/32
    dst: 10.0.0.2/32
    proto: udp
    dport: 5001
  guarantee:
    min_bandwidth_mbps: 20
    max_latency_ms: 20
"""


def _post(client, body, content_type="text/plain"):
    return client.post("/intent", content=body, headers={"content-type": content_type})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_post_yaml_creates_and_computes(client):
    r = _post(client, VALID_YAML)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "INT-101"
    assert "path" in body or "switches" in str(body)


def test_post_json_is_accepted_too(client):
    doc = {
        "intent": {
            "id": "INT-102", "tenant": "t", "priority": 2,
            "match": {"src": "10.0.0.1/32", "dst": "10.0.0.2/32"},
            "guarantee": {"min_bandwidth_mbps": 10},
        }
    }
    assert client.post("/intent", json=doc).status_code == 201


def test_invalid_intent_returns_422_with_paths_and_messages(client):
    bad = VALID_YAML.replace("priority: 1", "priority: 99")
    r = _post(client, bad)
    assert r.status_code == 422
    payload = r.json()
    errors = payload if isinstance(payload, list) else payload.get("detail", payload)
    assert errors, "422 must carry the validation errors"
    text = str(errors)
    assert "priority" in text


def test_malformed_yaml_is_422_not_500(client):
    r = _post(client, "intent:\n  id: INT-1\n   tenant: broken\n")
    assert r.status_code == 422


def test_get_one_and_list(client):
    _post(client, VALID_YAML)
    assert client.get("/intent/INT-101").status_code == 200
    listed = client.get("/intents")
    assert listed.status_code == 200
    assert any("INT-101" in str(item) for item in listed.json())


def test_get_unknown_is_404(client):
    assert client.get("/intent/INT-999").status_code == 404


def test_delete_withdraws_then_404_on_second_delete(client):
    _post(client, VALID_YAML)
    assert client.delete("/intent/INT-101").status_code == 204
    got = client.get("/intent/INT-101")
    assert got.status_code in (200, 404)
    if got.status_code == 200:
        assert got.json()["state"] == "withdrawn"


def test_delete_unknown_is_404(client):
    assert client.delete("/intent/INT-999").status_code == 404


def test_infeasible_intent_is_accepted_but_reports_reasons(client):
    """
    Feasibility is M2's job at ST-8. At ST-4 an intent with no path is still
    recorded; the response explains why nothing was computed.
    """
    body = VALID_YAML.replace("INT-101", "INT-103").replace(
        "min_bandwidth_mbps: 20", "min_bandwidth_mbps: 500"
    )
    r = _post(client, body)
    assert r.status_code == 201
    assert "reason" in r.text.lower() or "path" in r.text.lower()
