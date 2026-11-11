"""Regression tests for the 2026-11 controller audit findings (D1-D6, P1-P8, M1-M3)."""

from __future__ import annotations

import asyncio
import json as _json
from types import SimpleNamespace

import pytest

from src.admission.feasibility import assess
from src.admission.residual import residual_graph
from src.common import db as dbm
from src.common.audit import AuditLog
from src.common.events import EventBus, EventType, sla_violated
from src.common.models import (
    Consistency,
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


class _AsgiResponse:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self.content = body
        self.text = body.decode("utf-8", errors="replace")

    def json(self):
        return _json.loads(self.text)


class _AsgiClient:
    def __init__(self, app):
        self.app = app

    def _request(self, method: str, path: str, *, json=None, content=None, headers=None) -> _AsgiResponse:
        raw_headers = []
        hdr_dict = {k.lower(): v for k, v in (headers or {}).items()}
        if json is not None:
            body = _json.dumps(json).encode("utf-8")
            hdr_dict.setdefault("content-type", "application/json")
        elif isinstance(content, bytes):
            body = content
        elif isinstance(content, str):
            body = content.encode("utf-8")
        else:
            body = b""
        for k, v in hdr_dict.items():
            raw_headers.append((k.encode("latin-1"), str(v).encode("latin-1")))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": raw_headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        sent = False
        status_code = 500
        chunks: list[bytes] = []

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        asyncio.run(self.app(scope, receive, send))
        return _AsgiResponse(status_code, b"".join(chunks))

    def post(self, path: str, **kwargs) -> _AsgiResponse:
        return self._request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs) -> _AsgiResponse:
        return self._request("DELETE", path, **kwargs)

    def get(self, path: str, **kwargs) -> _AsgiResponse:
        return self._request("GET", path, **kwargs)


@pytest.fixture()
def conn():
    c = dbm.connect(":memory:")
    dbm.init_db(c)
    yield c
    c.close()


@pytest.fixture()
def client(conn):
    api_mod.app.dependency_overrides[api_mod.get_db] = lambda: conn
    try:
        from fastapi.testclient import TestClient

        with TestClient(api_mod.app) as test_client:
            yield test_client
    except Exception:
        yield _AsgiClient(api_mod.app)
    finally:
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


# --------------------------------------------------------------------------- #
# STEP 2: P1 - P8
# --------------------------------------------------------------------------- #


def test_p1_per_intent_queues_allocated_persisted_and_cleaned_up(conn, monkeypatch):
    """P1: Deterministic collision-checked queue ID per intent per egress port stored in SQLite and cleaned up."""
    from src.enforcement import queues

    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if "get" in argv and argv[-1] == "qos":
            return SimpleNamespace(stdout='"qos-root"\n')
        if "get" in argv and argv[-1] == "queues":
            return SimpleNamespace(stdout="{10=q-uuid-10, 20=q-uuid-20}\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(queues.subprocess, "run", fake_run)

    q1 = queues.ensure_queue("s1", "s1-eth2", 20, egress_peer="s2", intent_id="INT-Q1", conn=conn)
    q2 = queues.ensure_queue("s1", "s1-eth2", 30, egress_peer="s2", intent_id="INT-Q2", conn=conn)
    assert q1 != q2
    assert q1 >= 1 and q2 >= 1

    # Persisted across restarts: asking again for INT-Q1 on s1-eth2 returns the same queue_id
    assert queues.ensure_queue("s1", "s1-eth2", 20, egress_peer="s2", intent_id="INT-Q1", conn=conn) == q1

    # Root QoS max-rate stays at link capacity (100 Mbps = 100000000 bps on s1-s2)
    qos_sets = [c for c in calls if "set" in c and "qos" in c]
    assert any("other-config:max-rate=100000000" in c for c in qos_sets)
    assert any(f"queues:{q1}=@q" in c for c in qos_sets)
    assert any(f"queues:{q2}=@q" in c for c in qos_sets)

    # rules_for_path and two_phase.versioned_rules bind SET_QUEUE to per-hop queue_ids
    ports = {("s1", "h1"): 1, ("s1", "s2"): 2, ("s2", "s1"): 1, ("s2", "h2"): 2}
    intent = IntentRecord(
        id="INT-Q1",
        tenant="alpha",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(min_bandwidth_mbps=20),
    )
    plan = PathPlan("INT-Q1", ("s1", "s2"), ("s1-s2",), 2.0, 100.0, version=0)
    direct_rules = flowmod.rules_for_path(plan, intent, ports, queue_ids={"s1": q1})
    s1_fwd = next(r for r in direct_rules if r["switch"] == "s1" and r["direction"] == "forward")
    assert {"type": "SET_QUEUE", "queue_id": q1, "port": 2} in s1_fwd["actions"]

    ver_rules = two_phase.versioned_rules(plan, intent, ports, queue_ids={"s1": q1})
    s1_ver = next(r for r in ver_rules if r["switch"] == "s1" and r["direction"] == "forward")
    assert {"type": "SET_QUEUE", "queue_id": q1, "port": 2} in s1_ver["actions"]

    # Removing INT-Q1's queues deletes its DB record and leaves INT-Q2 intact
    queues.remove_intent_queues(conn, "INT-Q1")
    assert dbm.intent_queues_for(conn, "INT-Q1") == []
    assert len(dbm.intent_queues_for(conn, "INT-Q2")) == 1


def test_p2_queue_failure_raises_audits_path_install_failed_and_does_not_activate(tmp_path, monkeypatch):
    """P2: A failed ovs-vsctl call raises, audits PATH_INSTALL_FAILED, and leaves intent not ACTIVE."""
    import subprocess as sp
    from src.enforcement import controller as controller_mod, queues

    def failing_run(argv, **kwargs):
        raise sp.CalledProcessError(1, argv, stderr="ovs-vsctl: database connection failed")

    monkeypatch.setattr(queues.subprocess, "run", failing_run)

    with pytest.raises(RuntimeError):
        queues.ensure_queue("s1", "s1-eth2", 20, egress_peer="s2")

    db_path = tmp_path / "p2.db"
    real_connect = dbm.connect
    c = real_connect(db_path)
    dbm.init_db(c)
    intent = IntentRecord(
        id="INT-P2",
        tenant="alpha",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(min_bandwidth_mbps=20),
        state=IntentState.ADMITTED,
    )
    plan = PathPlan("INT-P2", ("s1", "s2", "s3", "s7"), ("s1-s2", "s2-s3", "s3-s7"), 6.0, 100.0, version=0)
    dbm.save_intent(c, intent)
    dbm.save_path(c, plan)
    c.close()

    ctrl = object.__new__(controller_mod.Team16Controller)
    ctrl.datapaths = {sw: object() for sw in plan.switches}
    ctrl.port_map = {}
    ctrl._installed_plans = {}
    ctrl._installed_plan_records = {}
    ctrl.event_bus = EventBus()
    ctrl.logger = SimpleNamespace(info=lambda *a: None, error=lambda *a: None, exception=lambda *a: None)
    monkeypatch.setattr(controller_mod.dbm, "connect", lambda: real_connect(db_path))

    ctrl._sync_intents_from_db()

    check = real_connect(db_path)
    stored = dbm.load_intent(check, "INT-P2")
    assert stored.state is not IntentState.ACTIVE
    events = dbm.events_for(check, "INT-P2")
    assert any(e.type is EventType.PATH_INSTALL_FAILED for e in events)
    assert dbm.intent_queues_for(check, "INT-P2") == []
    check.close()


def test_p3_two_phase_waits_for_barrier_reply_and_rolls_back_on_timeout(monkeypatch):
    """P3: Two-phase update waits for OFPBarrierReply with timeout and fails closed on timeout."""
    from src.enforcement import controller as controller_mod

    ctrl = object.__new__(controller_mod.Team16Controller)
    ctrl.logger = SimpleNamespace(info=lambda *a: None, error=lambda *a: None, warning=lambda *a: None)
    ctrl._init_default_port_map = lambda: None
    ctrl.port_map = {
        ("s1", "h1"): 1, ("s1", "s2"): 2, ("s2", "s1"): 1, ("s2", "s7"): 2, ("s7", "s2"): 1, ("s7", "h2"): 2,
        ("s1", "s4"): 3, ("s4", "s1"): 1, ("s4", "s7"): 2, ("s7", "s4"): 3,
    }
    ctrl.require_barrier_reply = True
    ctrl.barrier_timeout = 0.05

    class _BarrierDatapath:
        def __init__(self, dpid, auto_reply=True):
            self.id = dpid
            self.auto_reply = auto_reply
            self.sent = []
            self.ofproto = SimpleNamespace(
                OFPFC_ADD=0, OFPFC_DELETE=3, OFPIT_APPLY_ACTIONS=4,
                OFPVID_PRESENT=0x1000, OFPVID_NONE=0, OFPP_ANY=0xFFFFFFFF, OFPG_ANY=0xFFFFFFFF,
            )
            self.ofproto_parser = SimpleNamespace(
                OFPBarrierRequest=lambda dp: SimpleNamespace(datapath=dp, xid=None),
                OFPMatch=lambda **kw: kw,
                OFPFlowMod=lambda **kw: kw,
                OFPActionOutput=lambda port, max_len=None: ("out", port),
                OFPActionSetQueue=lambda qid: ("queue", qid),
                OFPActionPushVlan=lambda eth: ("push_vlan", eth),
                OFPActionSetField=lambda **kw: ("set_field", kw),
                OFPActionPopVlan=lambda: ("pop_vlan",),
                OFPInstructionActions=lambda t, a: (t, a),
            )

        def send_msg(self, msg):
            self.sent.append(msg)
            if hasattr(msg, "xid") and self.auto_reply:
                ctrl.barrier_reply_handler(SimpleNamespace(msg=SimpleNamespace(datapath=self, xid=msg.xid)))

    dp1 = _BarrierDatapath(1, auto_reply=True)
    dp2 = _BarrierDatapath(2, auto_reply=True)
    dp4 = _BarrierDatapath(4, auto_reply=False)  # s4 will time out on barrier!
    dp7 = _BarrierDatapath(7, auto_reply=True)
    ctrl.datapaths = {"s1": dp1, "s2": dp2, "s4": dp4, "s7": dp7}

    intent = IntentRecord(
        id="INT-P3",
        tenant="alpha",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(max_latency_ms=20),
    )
    old_plan = PathPlan("INT-P3", ("s1", "s2", "s7"), ("s1-s2", "s2-s7"), 4.0, 100.0, version=0)
    new_plan = PathPlan("INT-P3", ("s1", "s4", "s7"), ("s1-s4", "s4-s7"), 8.0, 50.0, version=1)

    # Initial install on s1-s2-s7 (all auto_reply=True) succeeds
    assert two_phase.install(ctrl, old_plan, intent, None) == 6

    # Reroute onto s1-s4-s7 where s4 times out on barrier must raise TimeoutError and roll back
    with pytest.raises(TimeoutError):
        two_phase.install(ctrl, new_plan, intent, old_plan)


def test_p4_openflow_error_msg_counts_as_failed_install_and_audits(tmp_path, monkeypatch):
    """P4: EventOFPErrorMsg during install marks rule failed and audits PATH_INSTALL_FAILED."""
    from src.enforcement import controller as controller_mod

    db_path = tmp_path / "p4.db"
    real_connect = dbm.connect
    conn = real_connect(db_path)
    dbm.init_db(conn)
    monkeypatch.setattr(controller_mod.dbm, "connect", lambda: real_connect(db_path))

    ctrl = object.__new__(controller_mod.Team16Controller)
    ctrl.logger = SimpleNamespace(info=lambda *a: None, error=lambda *a: None, warning=lambda *a: None)
    ctrl.port_map = {}
    ctrl._installed_plans = {}
    ctrl._installed_plan_records = {}
    ctrl.event_bus = EventBus()

    intent = IntentRecord(
        id="INT-P4",
        tenant="alpha",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(max_latency_ms=20),
        consistency=Consistency.RELAXED,
    )
    plan = PathPlan("INT-P4", ("s1", "s2", "s3", "s7"), ("s1-s2", "s2-s3", "s3-s7"), 6.0, 100.0)
    dbm.save_intent(conn, intent)
    dbm.save_path(conn, plan)

    def install_with_ofp_error(_ctrl, rules):
        # Simulate switch s2 returning an OpenFlow error message for one rule
        dp = SimpleNamespace(id=2)
        err_ev = SimpleNamespace(msg=SimpleNamespace(datapath=dp, xid=42, type=5, code=1))
        ctrl.error_msg_handler(err_ev)
        return len(rules)

    monkeypatch.setattr(controller_mod, "install", install_with_ofp_error)
    ctrl.datapaths = {sw: SimpleNamespace(id=int(sw[1:])) for sw in plan.switches}

    with pytest.raises(RuntimeError, match="OpenFlow error"):
        ctrl.install_plan(plan, intent, ctrl.event_bus)

    events = dbm.events_for(conn, "INT-P4")
    assert any(e.type is EventType.PATH_INSTALL_FAILED for e in events)
    conn.close()


def test_p5_topology_port_status_and_disconnect_update_graph_and_replan(conn):
    """P5: Port-down and datapath disconnect mark links down, block new paths on down links, and replan active intents."""
    from src.enforcement import controller as controller_mod

    bus = EventBus()
    audit = AuditLog(conn, bus)
    ctrl = object.__new__(controller_mod.Team16Controller)
    ctrl.logger = SimpleNamespace(info=lambda *a: None, error=lambda *a: None, warning=lambda *a: None)
    ctrl.datapaths = {f"s{i}": SimpleNamespace(id=i) for i in range(1, 8)}
    ctrl.dpid_to_name = {i: f"s{i}" for i in range(1, 8)}
    ctrl.name_to_dpid = {f"s{i}": i for i in range(1, 8)}
    ctrl.port_map = {}
    ctrl._init_default_port_map()
    ctrl.event_bus = bus
    ctrl._event_conn = conn
    ctrl._audit_log = audit
    ctrl._installed_plans = {}
    ctrl._installed_plan_records = {}
    ctrl.install_plan = lambda plan, intent, event_bus=None: 2 * len(plan.switches)
    ctrl._control_loop = ControlLoop(conn, build_graph(), ctrl, bus, audit)

    intent = IntentRecord(
        id="INT-P5",
        tenant="alpha",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(min_bandwidth_mbps=10, max_latency_ms=30),
        state=IntentState.ACTIVE,
        dwell_seconds=0,
    )
    north = PathPlan("INT-P5", ("s1", "s2", "s3", "s7"), ("s1-s2", "s2-s3", "s3-s7"), 6.0, 100.0)
    dbm.save_intent(conn, intent)
    dbm.save_path(conn, north)

    # Simulate port-status DOWN on s1's port toward s2
    s1_s2_port = ctrl.port_map[("s1", "s2")]
    port_down_ev = SimpleNamespace(
        msg=SimpleNamespace(
            datapath=SimpleNamespace(id=1, ofproto=SimpleNamespace(OFPPR_DELETE=1, OFPPC_PORT_DOWN=1, OFPPS_LINK_DOWN=1)),
            reason=2,
            desc=SimpleNamespace(port_no=s1_s2_port, config=1, state=1),
        )
    )
    ctrl.port_status_handler(port_down_ev)

    # Active intent on s1-s2 must be replanned onto middle path s1-s4-s5-s7
    assert dbm.current_path(conn, "INT-P5").switches == ("s1", "s4", "s5", "s7")
    assert not ctrl._control_loop.graph.has_edge("s1", "s2")

    # A new admission request while s1-s2 is down must never choose s1-s2
    new_req = IntentRecord(
        id="INT-P5-NEW",
        tenant="beta",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5002),
        guarantee=Guarantee(min_bandwidth_mbps=10, max_latency_ms=30),
    )
    dec, plan_new = assess(conn, new_req, build_graph())
    assert dec.admitted and "s1-s2" not in plan_new.links

    # Simulate port-status UP on s1-s2
    port_up_ev = SimpleNamespace(
        msg=SimpleNamespace(
            datapath=SimpleNamespace(id=1, ofproto=SimpleNamespace(OFPPR_DELETE=1, OFPPC_PORT_DOWN=1, OFPPS_LINK_DOWN=1)),
            reason=2,
            desc=SimpleNamespace(port_no=s1_s2_port, config=0, state=0),
        )
    )
    ctrl.port_status_handler(port_up_ev)
    assert ctrl._control_loop.graph.has_edge("s1", "s2")

    # Simulate datapath s4 disconnecting (DEAD_DISPATCHER)
    intent_fresh = dbm.load_intent(conn, "INT-P5")
    intent_fresh.last_replan_at = None
    dbm.save_intent(conn, intent_fresh)
    dead_ev = SimpleNamespace(datapath=SimpleNamespace(id=4), state="DEAD_DISPATCHER")
    ctrl.state_change_handler(dead_ev)
    assert "s4" not in ctrl.datapaths
    assert dbm.current_path(conn, "INT-P5").switches in (("s1", "s2", "s3", "s7"), ("s1", "s6", "s7"))


def test_p6_violation_dispatcher_tracks_rowid_and_retention_prunes_when_configured(conn, monkeypatch):
    """P6: Violation dispatcher tracks last processed rowid; retention prunes when env var is set."""
    from src.enforcement.controller import Team16Controller

    ctrl = object.__new__(Team16Controller)
    ctrl.event_bus = EventBus()
    ctrl._seen_violation_ids = set()
    delivered = []
    ctrl.event_bus.subscribe(delivered.append, EventType.SLA_VIOLATED)

    v1 = sla_violated("INT-P6-1", "delay_ms", 30.0, 20.0)
    dbm.save_event(conn, v1)
    ctrl._dispatch_persisted_violations(conn)
    assert len(delivered) == 1
    first_rowid = ctrl._last_dispatched_rowid
    assert first_rowid >= 1

    # Second call with new event scans only rowid > first_rowid
    v2 = sla_violated("INT-P6-2", "delay_ms", 35.0, 20.0)
    dbm.save_event(conn, v2)
    ctrl._dispatch_persisted_violations(conn)
    assert len(delivered) == 2
    assert ctrl._last_dispatched_rowid > first_rowid

    # Retention pruning when TEAM16_RETENTION_MAX_ROWS is explicitly set
    intent = IntentRecord(
        id="INT-P6-RET",
        tenant="alpha",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(max_latency_ms=20),
    )
    dbm.save_intent(conn, intent)
    monkeypatch.setenv("TEAM16_RETENTION_MAX_ROWS", "5")
    for idx in range(10):
        dbm.save_measurement(conn, "INT-P6-RET", float(idx + 1), delay_ms=5.0)
    remaining = list(dbm.measurements_for(conn, "INT-P6-RET"))
    assert len(remaining) == 5
    assert [r["at"] for r in remaining] == [6.0, 7.0, 8.0, 9.0, 10.0]


def test_p7_table_miss_rate_limits_or_drops_packet_in():
    """P7: switch_features_handler installs a packet-in rate-limit meter or drop rule to prevent floods."""
    from src.enforcement import controller as controller_mod

    ctrl = object.__new__(controller_mod.Team16Controller)
    ctrl.datapaths = {}
    ctrl.dpid_to_name = {}
    ctrl.name_to_dpid = {}
    ctrl.logger = SimpleNamespace(info=lambda *a: None)
    ctrl._discover_ports = lambda dp: None

    sent = []

    class _MeterParser:
        def OFPMatch(self, **kw):
            return kw

        def OFPActionOutput(self, port, max_len=None):
            return {"port": port, "max_len": max_len}

        def OFPInstructionActions(self, t, actions):
            return {"type": t, "actions": actions}

        def OFPInstructionMeter(self, meter_id, inst_type=1):
            return {"type": "METER", "meter_id": meter_id}

        def OFPMeterBandDrop(self, rate, burst_size=0):
            return {"type": "DROP", "rate": rate, "burst_size": burst_size}

        def OFPMeterMod(self, **kw):
            return {"msg": "OFPMeterMod", **kw}

        def OFPFlowMod(self, **kw):
            return {"msg": "OFPFlowMod", **kw}

    dp = SimpleNamespace(
        id=1,
        ofproto_parser=_MeterParser(),
        ofproto=SimpleNamespace(
            OFPP_CONTROLLER=0xFFFFFFFD,
            OFPCML_NO_BUFFER=0xFFFF,
            OFPIT_APPLY_ACTIONS=4,
            OFPIT_METER=1,
            OFPMC_ADD=0,
            OFPMF_PKTPS=1,
        ),
        send_msg=sent.append,
    )
    ctrl.switch_features_handler(SimpleNamespace(msg=SimpleNamespace(datapath=dp)))
    assert any(m.get("msg") == "OFPMeterMod" for m in sent)
    flow = next(m for m in sent if m.get("msg") == "OFPFlowMod" and m.get("priority") == 0)
    assert any(inst.get("type") == "METER" for inst in flow["instructions"])


def test_p8_post_intent_body_over_64kib_returns_413(client):
    """P8: POST /intent with body larger than 64 KiB returns HTTP 413."""
    oversized = "intent:\n  id: INT-BIG\n# " + ("x" * 66000)
    resp = client.post("/intent", content=oversized, headers={"content-type": "text/plain"})
    assert resp.status_code == 413


# --------------------------------------------------------------------------- #
# STEP 3: M1 - M3
# --------------------------------------------------------------------------- #


def test_m1_degrade_lowers_queue_rate_releases_residual_and_restores_on_sla_restored(conn, monkeypatch):
    """M1: on_violation=degrade lowers queue min-rate by factor, frees residual capacity, and restores on SLA_RESTORED."""
    from src.common.events import sla_restored
    from src.enforcement import queues

    q_calls = []
    monkeypatch.setattr(
        queues.subprocess,
        "run",
        lambda argv, **kw: q_calls.append(argv) or SimpleNamespace(stdout='"qos-1"\n' if "get" in argv else ""),
    )

    intent = IntentRecord(
        id="INT-M1",
        tenant="alpha",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(min_bandwidth_mbps=40, max_latency_ms=30),
        on_violation=OnViolation.DEGRADE,
        state=IntentState.ACTIVE,
        dwell_seconds=0,
    )
    south = PathPlan("INT-M1", ("s1", "s6", "s7"), ("s1-s6", "s6-s7"), 24.0, 40.0)
    dbm.save_intent(conn, intent)
    dbm.save_path(conn, south)
    queues.ensure_queue("s1", "s1-eth4", 40, egress_peer="s6", intent_id="INT-M1", conn=conn)
    queues.ensure_queue("s6", "s6-eth3", 40, egress_peer="s7", intent_id="INT-M1", conn=conn)

    bus = EventBus()
    audit = AuditLog(conn, bus)
    ctrl = _FakeController()
    loop = ControlLoop(conn, build_graph(), ctrl, bus, audit)

    # Before degrade: south link has 40 Mbps reserved, 0 Mbps residual
    rg_before = residual_graph(conn, build_graph())
    assert rg_before["s1"]["s6"]["reserved_mbps"] == 40.0
    assert rg_before["s1"]["s6"]["residual_mbps"] == 0.0

    # Trigger violation -> degrade to 50% (20 Mbps)
    loop.on_violation(sla_violated("INT-M1", "delay_ms", 35.0, 30.0))
    assert dbm.load_intent(conn, "INT-M1").state is IntentState.DEGRADED

    rg_degraded = residual_graph(conn, build_graph())
    assert rg_degraded["s1"]["s6"]["reserved_mbps"] == 20.0
    assert rg_degraded["s1"]["s6"]["residual_mbps"] == 20.0

    # Audit log mentions old and new rates (40 and 20)
    history = audit.history("INT-M1")
    assert any("40" in h.message and "20" in h.message for h in history)

    # Trigger SLA_RESTORED -> restores full 40 Mbps rate and ACTIVE state
    bus.publish(sla_restored("INT-M1", "delay_ms", 18.0))
    assert dbm.load_intent(conn, "INT-M1").state is IntentState.ACTIVE
    rg_restored = residual_graph(conn, build_graph())
    assert rg_restored["s1"]["s6"]["reserved_mbps"] == 40.0
    assert rg_restored["s1"]["s6"]["residual_mbps"] == 0.0


def test_m2_readmission_of_preempted_intents_in_priority_order(client, conn):
    """M2: Withdrawing or rerouting an intent re-runs admission for preempted intents in priority order."""
    # Seed active high-priority intent taking 80 Mbps on north, and two preempted intents (prio 3 and prio 5)
    for iid, prio, dport, bw in (
        ("INT-HIGH", 1, 5001, 80.0),
        ("INT-PRE-P5", 5, 5002, 70.0),
        ("INT-PRE-P3", 3, 5003, 70.0),
    ):
        rec = IntentRecord(
            id=iid,
            tenant=f"t-{iid}",
            priority=prio,
            match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", dport),
            guarantee=Guarantee(min_bandwidth_mbps=bw),
            state=IntentState.ACTIVE if iid == "INT-HIGH" else IntentState.PREEMPTED,
        )
        dbm.save_intent(conn, rec)
        if iid == "INT-HIGH":
            dbm.save_path(conn, PathPlan(iid, ("s1", "s2", "s3", "s7"), ("s1-s2", "s2-s3", "s3-s7"), 6.0, 100.0))

    # Withdraw INT-HIGH -> frees 80 Mbps on north -> INT-PRE-P3 (higher priority than P5) gets re-admitted first!
    assert client.delete("/intent/INT-HIGH").status_code == 204

    p3 = dbm.load_intent(conn, "INT-PRE-P3")
    p5 = dbm.load_intent(conn, "INT-PRE-P5")
    assert p3.state is IntentState.ADMITTED
    assert dbm.current_path(conn, "INT-PRE-P3") is not None
    # P5 also needed 70 Mbps (only 30 Mbps left on north, 50 on middle, 40 on south), so P5 stays preempted and is audited
    assert p5.state is IntentState.PREEMPTED
    assert len(dbm.events_for(conn, "INT-PRE-P3")) >= 1
    assert len(dbm.events_for(conn, "INT-PRE-P5")) >= 1


def test_m3_bearer_token_access_control_enforces_tenant_ownership(client, monkeypatch):
    """M3: When TEAM16_API_TOKENS is set, POST and DELETE require Bearer token and enforce tenant ownership."""
    monkeypatch.setenv("TEAM16_API_TOKENS", "alice=secret-alice,bob=secret-bob")

    alice_doc = {
        "intent": {
            "id": "INT-777",
            "tenant": "alice",
            "priority": 2,
            "match": {"src": "10.0.0.1/32", "dst": "10.0.0.2/32", "proto": "udp", "dport": 5001},
            "guarantee": {"min_bandwidth_mbps": 10},
        }
    }

    # Missing Authorization -> 401
    assert client.post("/intent", json=alice_doc).status_code == 401
    # Wrong token -> 401
    assert client.post("/intent", json=alice_doc, headers={"Authorization": "Bearer wrong"}).status_code == 401
    # Bob's token trying to create Alice's intent -> 403
    assert client.post("/intent", json=alice_doc, headers={"Authorization": "Bearer secret-bob"}).status_code == 403
    # Alice's token creating Alice's intent -> 201
    assert client.post("/intent", json=alice_doc, headers={"Authorization": "Bearer secret-alice"}).status_code == 201

    # Bob trying to delete Alice's intent -> 403
    assert client.delete("/intent/INT-777", headers={"Authorization": "Bearer secret-bob"}).status_code == 403
    # Missing token on delete -> 401
    assert client.delete("/intent/INT-777").status_code == 401
    # Alice deleting Alice's intent -> 204
    assert client.delete("/intent/INT-777", headers={"Authorization": "Bearer secret-alice"}).status_code == 204

