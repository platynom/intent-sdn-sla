"""E14b live finding: simultaneous violations must not over-commit links.

The Ryu controller dispatches simultaneous SLA violations on parallel green
threads, and a reroute's path is persisted only after its install completes.
In the live E14b run three 20 Mbit/s intents on the faulted north path all
planned onto the 40 Mbit/s south path (60 Mbit/s reserved) and raced each
other creating the same port's OVS QoS record.  These tests interleave the
reroutes the way green threads do: while one plan is installing, the next
violation is planned.
"""
import threading
import time
from types import SimpleNamespace

from src.admission.residual import residual_graph
from src.common import db
from src.common.audit import AuditLog
from src.common.events import Event, EventBus, sla_violated
from src.common.models import Guarantee, IntentRecord, IntentState, Match, OnViolation, PathPlan
from src.enforcement import queues
from src.telemetry.loop import ControlLoop
from topology.topology_spec import build_graph

NORTH = ("s1", "s2", "s3", "s7")
MIDDLE = ("s1", "s4", "s5", "s7")


class InterleavingController:
    """Install plans, starting the next queued violation mid-install."""

    def __init__(self, fail_ids=()):
        self.loop = None
        self.queued = []
        self.installed = []
        self.fail_ids = set(fail_ids)

    def install_plan(self, plan, intent, bus):
        if self.queued:
            self.loop.on_violation(self.queued.pop(0))
        if intent.id in self.fail_ids:
            raise RuntimeError("injected install failure")
        self.installed.append((intent.id, tuple(plan.switches)))
        return 2 * len(plan.switches)


def _intent(iid, tenant, mbps=20):
    return IntentRecord(
        id=iid, tenant=tenant, priority=2,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5100 + int(iid[-1])),
        guarantee=Guarantee(min_bandwidth_mbps=mbps, max_latency_ms=35),
        on_violation=OnViolation.REROUTE, dwell_seconds=0, state=IntentState.ACTIVE,
    )


def _violation(iid, at=20.0):
    ev = sla_violated(iid, "delay_ms", 50.0, 35.0)
    return Event(ev.type, ev.message, ev.intent_id, ev.severity, ev.payload, at, ev.id)


def _e14b_state(fail_ids=()):
    """Three 20 Mbit/s intents on north, one on middle: the live E14b layout."""
    conn = db.connect(":memory:")
    db.init_db(conn)
    for iid, path in (("INT-101", NORTH), ("INT-102", NORTH), ("INT-103", NORTH), ("INT-104", MIDDLE)):
        db.save_intent(conn, _intent(iid, f"t{iid[-1]}"))
        db.save_path(conn, PathPlan(iid, path, PathPlan.links_for(list(path)), 6.0, 100.0))
    controller = InterleavingController(fail_ids)
    loop = ControlLoop(conn, build_graph(), controller, EventBus(), AuditLog(conn))
    controller.loop = loop
    return SimpleNamespace(conn=conn, loop=loop, controller=controller)


def _overcommitted(conn):
    rg = residual_graph(conn, build_graph())
    return {
        f"{u}-{v}": d["reserved_mbps"]
        for u, v, d in rg.edges(data=True)
        if d["reserved_mbps"] > d["capacity_mbps"] + 1e-9
    }


def test_interleaved_reroutes_never_overcommit_a_link():
    st = _e14b_state()
    st.controller.queued = [_violation("INT-102"), _violation("INT-103")]
    st.loop.on_violation(_violation("INT-101"))
    assert len(st.controller.installed) == 3
    assert _overcommitted(st.conn) == {}
    south = [p for _, p in st.controller.installed if p == ("s1", "s6", "s7")]
    assert len(south) <= 2  # 40 Mbit/s south link fits at most two 20 Mbit/s intents


def test_failed_install_releases_its_in_flight_reservation():
    st = _e14b_state(fail_ids={"INT-101"})
    st.controller.queued = [_violation("INT-102")]
    st.loop.on_violation(_violation("INT-101"))
    assert st.loop._in_flight == {}
    assert _overcommitted(st.conn) == {}
    # INT-101 kept its old path because its install failed.
    assert tuple(db.current_path(st.conn, "INT-101").switches) == NORTH


def test_in_flight_plan_counts_for_tenant_isolation():
    st = _e14b_state()
    st.loop._in_flight["INT-101"] = (
        PathPlan("INT-101", ("s1", "s6", "s7"), PathPlan.links_for(["s1", "s6", "s7"]), 24.0, 40.0),
        db.load_intent(st.conn, "INT-101"),
        20.0,
    )
    from src.admission.residual import tenant_paths

    t_paths = tenant_paths(st.conn, exclude_intent_ids={"INT-105"})
    rg = residual_graph(st.conn, build_graph(), exclude_intent_ids={"INT-105"})
    st.loop._apply_in_flight(rg, t_paths, "INT-105")
    assert ["s1", "s6", "s7"] in t_paths["t1"]
    assert rg["s1"]["s6"]["residual_mbps"] == 20.0


def test_concurrent_queue_setup_on_one_port_creates_a_single_qos(monkeypatch):
    """Two reroutes onto one port must not both create a QoS record."""
    state = {"qos": None, "creates": 0}
    lock = threading.Lock()

    def fake_run(argv, **kwargs):
        if argv[0] == "tc":
            return SimpleNamespace(stdout="")
        if "get" in argv:
            with lock:
                current = state["qos"]
            time.sleep(0.05)  # widen the get -> create window
            return SimpleNamespace(stdout='"qos-1"\n' if current else "[]\n")
        if "qos=@newqos" in argv:
            with lock:
                state["creates"] += 1
                state["qos"] = "qos-1"
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(queues.subprocess, "run", fake_run)
    threads = [
        threading.Thread(target=queues.ensure_queue, args=("s1", "s1-eth4", 20),
                         kwargs={"egress_peer": "s6", "queue_id": q})
        for q in (1, 2, 3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["creates"] == 1
