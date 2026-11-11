"""Regression tests for the 2026-11 controller audit findings (D1-D6, P1-P8, M1-M3)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.admission.feasibility import assess
from src.admission.residual import residual_graph
from src.common import db as dbm
from src.common.audit import AuditLog
from src.common.events import EventBus, EventType, sla_violated
from src.common.models import (
    Guarantee,
    IntentRecord,
    IntentState,
    Match,
    OnViolation,
    PathPlan,
    Verdict,
)
from src.enforcement import flowmod, two_phase
from src.intent_manager import api as api_mod
from src.telemetry.loop import ControlLoop
from topology.topology_spec import build_graph


@pytest.fixture()
def conn():
    c = dbm.connect(":memory:")
    dbm.init_db(c)
    yield c
    c.close()


@pytest.fixture()
def client(conn):
    api_mod.app.dependency_overrides[api_mod.get_db] = lambda: conn
    with TestClient(api_mod.app) as test_client:
        yield test_client
    api_mod.app.dependency_overrides.clear()


class _FakeController:
    def __init__(self):
        self.calls = []

    def install_plan(self, plan, intent, bus):
        self.calls.append((plan, intent))
        return 2 * len(plan.switches)


# --------------------------------------------------------------------------- #
# STEP 1: D1 - D6
# --------------------------------------------------------------------------- #


def test_d1_reverse_rules_disambiguate_same_host_pair_by_sport():
    """D1: Two intents between the same hosts on different dports must not collide on reverse rules."""
    ports = {
        ("s1", "h1"): 1,
        ("s1", "s2"): 2,
        ("s2", "s1"): 1,
        ("s2", "s3"): 2,
        ("s3", "s2"): 1,
        ("s3", "s7"): 2,
        ("s7", "s3"): 1,
        ("s7", "h2"): 3,
        ("s1", "s6"): 4,
        ("s6", "s1"): 1,
        ("s6", "s7"): 2,
        ("s7", "s6"): 2,
    }
    i1 = IntentRecord(
        id="INT-601",
        tenant="alpha",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(min_bandwidth_mbps=10),
    )
    i2 = IntentRecord(
        id="INT-602",
        tenant="beta",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5002),
        guarantee=Guarantee(min_bandwidth_mbps=10),
    )
    p1 = PathPlan("INT-601", ("s1", "s2", "s3", "s7"), ("s1-s2", "s2-s3", "s3-s7"), 6.0, 100.0)
    p2 = PathPlan("INT-602", ("s1", "s6", "s7"), ("s1-s6", "s6-s7"), 24.0, 40.0)

    r1 = flowmod.rules_for_path(p1, i1, ports)
    r2 = flowmod.rules_for_path(p2, i2, ports)

    rev1 = [r for r in r1 if r["direction"] == "reverse"]
    rev2 = [r for r in r2 if r["direction"] == "reverse"]
    assert all(r["match"].get("sport") == 5001 for r in rev1)
    assert all(r["match"].get("sport") == 5002 for r in rev2)

    seen = set()
    for rule in rev1 + rev2:
        key = (rule["switch"], rule["priority"], tuple(sorted(rule["match"].items())))
        assert key not in seen, f"reverse rule collision on {key}"
        seen.add(key)

    v1 = two_phase.versioned_rules(two_phase.with_version(p1, 1), i1, ports)
    v2 = two_phase.versioned_rules(two_phase.with_version(p2, 1), i2, ports)
    v_rev = [r for r in v1 + v2 if r["direction"] == "reverse" and r["priority"] == 200]
    seen_v = set()
    for rule in v_rev:
        key = (rule["switch"], rule["priority"], tuple(sorted(rule["match"].items())))
        assert key not in seen_v, f"versioned reverse classifier collision on {key}"
        seen_v.add(key)


def test_d2_reroute_uses_residual_capacity_and_never_oversubscribes(conn):
    """D2: ControlLoop.on_violation must plan on residual_graph and retain path when no alternative fits."""
    graph = build_graph()
    intents = [
        IntentRecord(
            id="INT-101",
            tenant="alpha",
            priority=1,
            match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
            guarantee=Guarantee(min_bandwidth_mbps=30, max_latency_ms=30),
            dwell_seconds=0,
        ),
        IntentRecord(
            id="INT-102",
            tenant="beta",
            priority=1,
            match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5002),
            guarantee=Guarantee(min_bandwidth_mbps=45, max_latency_ms=30, avoid_links=("s1-s2",)),
            dwell_seconds=0,
        ),
        IntentRecord(
            id="INT-103",
            tenant="gamma",
            priority=1,
            match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5003),
            guarantee=Guarantee(min_bandwidth_mbps=35, max_latency_ms=30, avoid_links=("s1-s2", "s1-s4")),
            dwell_seconds=0,
        ),
    ]
    for rec in intents:
        decision, plan = assess(conn, rec, graph)
        assert decision.admitted and plan is not None
        rec.state = IntentState.ACTIVE
        dbm.save_intent(conn, rec)
        dbm.save_path(conn, plan)

    bus = EventBus()
    audit = AuditLog(conn, bus)
    ctrl = _FakeController()
    loop = ControlLoop(conn, build_graph(), ctrl, bus, audit)

    loop.on_violation(sla_violated("INT-101", "delay_ms", 35.0, 30.0))

    # Neither middle (5 Mbps left) nor south (5 Mbps left) can fit 30 Mbps.
    assert dbm.current_path(conn, "INT-101").switches == ("s1", "s2", "s3", "s7")
    assert ctrl.calls == []
    assert any(e.type is EventType.PATH_INFEASIBLE for e in dbm.events_for(conn, "INT-101"))

    rg = residual_graph(conn, build_graph())
    for u, v, data in rg.edges(data=True):
        assert data["reserved_mbps"] <= data["capacity_mbps"], f"edge {u}-{v} oversubscribed"


def test_d3_reroute_enforces_tenant_isolation(conn):
    """D3: ControlLoop.on_violation must pass tenant_paths so reroutes honour isolate_from."""
    graph = build_graph()
    beta = IntentRecord(
        id="INT-501",
        tenant="beta",
        priority=2,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(min_bandwidth_mbps=10, max_latency_ms=30, avoid_links=("s1-s2",)),
        state=IntentState.ACTIVE,
        dwell_seconds=0,
    )
    _, beta_plan = assess(conn, beta, graph)
    dbm.save_intent(conn, beta)
    dbm.save_path(conn, beta_plan)
    assert beta_plan.switches == ("s1", "s4", "s5", "s7")

    alpha = IntentRecord(
        id="INT-502",
        tenant="alpha",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5002),
        guarantee=Guarantee(min_bandwidth_mbps=10, max_latency_ms=30, isolate_from=("beta",)),
        state=IntentState.ACTIVE,
        dwell_seconds=0,
    )
    _, alpha_plan = assess(conn, alpha, graph)
    dbm.save_intent(conn, alpha)
    dbm.save_path(conn, alpha_plan)
    assert alpha_plan.switches == ("s1", "s2", "s3", "s7")

    bus = EventBus()
    audit = AuditLog(conn, bus)
    ctrl = _FakeController()
    loop = ControlLoop(conn, build_graph(), ctrl, bus, audit)

    loop.on_violation(sla_violated("INT-502", "delay_ms", 35.0, 30.0))

    new_plan = dbm.current_path(conn, "INT-502")
    assert new_plan.switches == ("s1", "s6", "s7")
    assert new_plan.is_disjoint_from(beta_plan)


def test_d4_isolation_is_bidirectional_in_admission_and_reroute(conn):
    """D4: An incoming or rerouted intent must not share links with an active intent that isolates from it."""
    graph = build_graph()
    alpha = IntentRecord(
        id="INT-201",
        tenant="alpha",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(min_bandwidth_mbps=10, max_latency_ms=25, isolate_from=("beta",)),
        state=IntentState.ACTIVE,
    )
    decision_a, plan_a = assess(conn, alpha, graph)
    assert decision_a.admitted and plan_a.switches == ("s1", "s2", "s3", "s7")
    dbm.save_intent(conn, alpha)
    dbm.save_path(conn, plan_a)

    # beta does NOT list alpha in isolate_from, but alpha isolates from beta.
    beta = IntentRecord(
        id="INT-202",
        tenant="beta",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5002),
        guarantee=Guarantee(min_bandwidth_mbps=10, max_latency_ms=25),
        state=IntentState.ACTIVE,
    )
    decision_b, plan_b = assess(conn, beta, graph)
    assert decision_b.admitted and plan_b is not None
    assert plan_b.switches == ("s1", "s4", "s5", "s7")
    assert plan_b.is_disjoint_from(plan_a)

    # If beta requires latency <= 10 ms (only north satisfies 6 ms, and alpha is on north),
    # beta must be rejected with a reason naming protected tenant 'alpha'.
    beta_strict = IntentRecord(
        id="INT-203",
        tenant="beta",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5003),
        guarantee=Guarantee(min_bandwidth_mbps=10, max_latency_ms=10),
    )
    decision_strict, plan_strict = assess(conn, beta_strict, graph)
    assert decision_strict.verdict is Verdict.REJECT
    assert plan_strict is None
    assert "alpha" in decision_strict.reason


def test_d5_overlapping_or_identical_match_returns_409(client):
    """D5: POST /intent with identical or overlapping forward/reverse match returns HTTP 409 naming the existing intent."""
    doc1 = {
        "intent": {
            "id": "INT-301",
            "tenant": "alpha",
            "priority": 2,
            "match": {"src": "10.0.0.1/32", "dst": "10.0.0.2/32", "proto": "udp", "dport": 5001},
            "guarantee": {"min_bandwidth_mbps": 10},
        }
    }
    doc2_identical = {
        "intent": {
            "id": "INT-302",
            "tenant": "beta",
            "priority": 2,
            "match": {"src": "10.0.0.1/32", "dst": "10.0.0.2/32", "proto": "udp", "dport": 5001},
            "guarantee": {"min_bandwidth_mbps": 10},
        }
    }
    r1 = client.post("/intent", json=doc1)
    assert r1.status_code == 201

    r2 = client.post("/intent", json=doc2_identical)
    assert r2.status_code == 409
    assert "INT-301" in r2.text

    # Wildcard port overlap (no dport overlaps dport 5001)
    doc3_wildcard = {
        "intent": {
            "id": "INT-303",
            "tenant": "gamma",
            "priority": 2,
            "match": {"src": "10.0.0.1/32", "dst": "10.0.0.2/32", "proto": "udp"},
            "guarantee": {"min_bandwidth_mbps": 10},
        }
    }
    r3 = client.post("/intent", json=doc3_wildcard)
    assert r3.status_code == 409
    assert "INT-301" in r3.text


def test_d6_intent_id_overwrite_returns_409_unless_withdrawn_or_rejected(client):
    """D6: POST /intent with existing live ID returns 409; withdrawn/rejected may be replaced without self-conflict."""
    doc1 = {
        "intent": {
            "id": "INT-401",
            "tenant": "victim",
            "priority": 1,
            "match": {"src": "10.0.0.1/32", "dst": "10.0.0.2/32", "proto": "udp", "dport": 5001},
            "guarantee": {"min_bandwidth_mbps": 60},
        }
    }
    doc_overwrite = {
        "intent": {
            "id": "INT-401",
            "tenant": "attacker",
            "priority": 5,
            "match": {"src": "10.0.0.1/32", "dst": "10.0.0.2/32", "proto": "udp", "dport": 5002},
            "guarantee": {"min_bandwidth_mbps": 1},
        }
    }
    assert client.post("/intent", json=doc1).status_code == 201

    r_dup = client.post("/intent", json=doc_overwrite)
    assert r_dup.status_code == 409
    assert "updating a live intent is not supported" in r_dup.text.lower()

    stored = client.get("/intent/INT-401").json()
    assert stored["tenant"] == "victim"
    assert stored["priority"] == 1

    # Withdraw INT-401, then re-create with 60 Mbps (which would fail on north if old 60 Mbps reservation remained)
    assert client.delete("/intent/INT-401").status_code == 204
    r_recreate = client.post(
        "/intent",
        json={
            "intent": {
                "id": "INT-401",
                "tenant": "victim",
                "priority": 1,
                "match": {"src": "10.0.0.1/32", "dst": "10.0.0.2/32", "proto": "udp", "dport": 5001},
                "guarantee": {"min_bandwidth_mbps": 60, "max_latency_ms": 10},
            }
        },
    )
    assert r_recreate.status_code == 201
    assert r_recreate.json()["state"] == "admitted"
    assert r_recreate.json()["switches"] == ["s1", "s2", "s3", "s7"]
