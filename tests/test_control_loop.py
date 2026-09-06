"""ST-7 closed-loop tests with in-memory state and a fake controller."""

from types import SimpleNamespace

from src.common import db
from src.common.audit import AuditLog
from src.common.events import Event, EventBus, EventType, sla_restored, sla_violated
from src.common.models import (
    Guarantee, IntentRecord, IntentState, Match, OnViolation, PathPlan,
)
from src.telemetry.loop import ControlLoop
from topology.topology_spec import build_graph


NORTH = ("s1", "s2", "s3", "s7")


class FakeController:
    """Record enforcement without requiring Ryu or switches."""

    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def install_plan(self, plan, intent, bus):
        """Return the production rule count or raise an injected failure."""
        self.calls.append((plan, intent, bus))
        if self.error:
            raise self.error
        return 2 * len(plan.switches)


def environment(action=OnViolation.REROUTE, dwell=0, last=None):
    """Create persisted active state for one deterministic loop test."""
    conn = db.connect(":memory:")
    db.init_db(conn)
    intent = IntentRecord(
        id="INT-700", tenant="loop-test", priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(min_bandwidth_mbps=20, max_latency_ms=20),
        on_violation=action, dwell_seconds=dwell, state=IntentState.ACTIVE,
        last_replan_at=last,
    )
    path = PathPlan("INT-700", NORTH, PathPlan.links_for(NORTH), 6, 100)
    db.save_intent(conn, intent)
    db.save_path(conn, path)
    bus = EventBus()
    audit = AuditLog(conn)
    controller = FakeController()
    loop = ControlLoop(conn, build_graph(), controller, bus, audit)
    return SimpleNamespace(conn=conn, intent=intent, path=path, bus=bus,
                           audit=audit, controller=controller, loop=loop)


def violation(at=20):
    """Create a complete latency violation with a stable injected timestamp."""
    event = sla_violated("INT-700", "delay_ms", 30, 20)
    return Event(event.type, event.message, event.intent_id, event.severity,
                 event.payload, at, event.id)


def test_construction_subscribes_only_to_violations():
    """A missing or broad subscription would disable control or react to noise."""
    env = environment()
    assert env.loop.on_violation in env.bus._subs[EventType.SLA_VIOLATED]
    assert env.loop.on_violation not in env.bus._subs.get(None, [])


def test_other_event_type_does_nothing():
    """Recovery notifications must not accidentally trigger another reroute."""
    env = environment()
    env.bus.publish(sla_restored("INT-700", "delay_ms", 5))
    assert env.controller.calls == []


def test_unknown_intent_is_safe():
    """Stale telemetry must not crash the bus or alter unrelated switches."""
    env = environment()
    env.bus.publish(sla_violated("UNKNOWN", "delay_ms", 30, 20))
    assert env.controller.calls == [] and env.bus.errors == []


def test_alert_only_audits_without_state_change():
    """Alert-only customer policy must never mutate the live network."""
    env = environment(OnViolation.ALERT_ONLY)
    env.loop.on_violation(violation())
    assert not env.controller.calls
    assert db.load_intent(env.conn, "INT-700").state is IntentState.ACTIVE
    assert env.audit.history("INT-700")


def test_degrade_persists_without_reroute():
    """Degrade policy must be observable without silently moving traffic."""
    env = environment(OnViolation.DEGRADE)
    env.loop.on_violation(violation())
    assert db.load_intent(env.conn, "INT-700").state is IntentState.DEGRADED
    assert not env.controller.calls


def test_dwell_uses_model_method(monkeypatch):
    """Duplicated dwell arithmetic would drift from the frozen shared model."""
    env = environment()
    called = []
    monkeypatch.setattr(IntentRecord, "may_replan_at", lambda self, now: called.append(now) or False)
    env.loop.on_violation(violation(), now=77)
    assert called == [77]


def test_active_dwell_suppresses_installation():
    """Rapid repeated changes would make the network oscillate."""
    env = environment(dwell=10, last=15)
    env.loop.on_violation(violation(at=20))
    assert env.controller.calls == []


def test_dwell_retains_path_and_timestamp():
    """Suppression must not corrupt the last known working route or timer."""
    env = environment(dwell=10, last=15)
    env.loop.on_violation(violation(at=20))
    assert db.current_path(env.conn, "INT-700").switches == NORTH
    assert db.load_intent(env.conn, "INT-700").last_replan_at == 15


def test_expired_dwell_allows_installation():
    """Dwell must delay recovery rather than disable it forever."""
    env = environment(dwell=10, last=5)
    env.loop.on_violation(violation(at=20))
    assert len(env.controller.calls) == 1


def test_candidate_graph_excludes_current_links(monkeypatch):
    """Keeping failed links lets deterministic selection falsely choose the same path."""
    env = environment()
    seen = []
    from src.telemetry import loop as module
    monkeypatch.setattr(module, "compute_path", lambda intent, graph: seen.append(graph.copy()) or (None, {"x": "none"}))
    env.loop.on_violation(violation())
    assert all(not seen[0].has_edge(a, b) for a, b in zip(NORTH, NORTH[1:]))


def test_original_graph_is_unchanged():
    """Mutating shared topology would poison every later path computation."""
    env = environment()
    edges = set(env.loop.graph.edges())
    env.loop.on_violation(violation())
    assert set(env.loop.graph.edges()) == edges


def test_reroute_cannot_select_failing_path():
    """A reported reroute must actually leave the path that violated."""
    env = environment()
    env.loop.on_violation(violation())
    assert db.current_path(env.conn, "INT-700").switches != NORTH


def test_no_alternative_retains_current_path():
    """Infeasibility must not remove the only installed working route."""
    env = environment()
    env.loop.graph.remove_edges_from([e for e in env.loop.graph.edges() if e not in list(zip(NORTH, NORTH[1:]))])
    env.loop.on_violation(violation())
    assert db.current_path(env.conn, "INT-700").switches == NORTH


def test_no_alternative_preserves_replan_time():
    """A failed attempt must not start a dwell period as though it succeeded."""
    env = environment(last=3)
    env.loop.graph.clear_edges()
    env.loop.on_violation(violation())
    assert db.load_intent(env.conn, "INT-700").last_replan_at == 3


def test_no_alternative_has_readable_audit():
    """Operators need a plain reason when automatic recovery is impossible."""
    env = environment()
    env.loop.graph.clear_edges()
    env.loop.on_violation(violation())
    assert "no feasible alternative" in env.audit.history("INT-700")[0].message


def test_success_saves_and_supersedes_path():
    """Successful enforcement must atomically make exactly one new route current."""
    env = environment()
    env.loop.on_violation(violation())
    assert db.reroute_count(env.conn, "INT-700") == 1
    assert db.current_path(env.conn, "INT-700").switches != NORTH


def test_success_stores_injected_time():
    """Using wall time would make replay and dwell behavior irreproducible."""
    env = environment()
    env.loop.on_violation(violation(), now=123)
    assert db.load_intent(env.conn, "INT-700").last_replan_at == 123


def test_success_audit_contains_all_causal_parts():
    """An unexplained network change is operationally unauditable."""
    env = environment()
    env.loop.on_violation(violation())
    payload = env.audit.history("INT-700")[0].payload
    assert set(payload) >= {"measurement", "threshold", "decision", "action"}


def test_controller_exception_is_caught():
    """One failed switch operation must not break event delivery."""
    env = environment()
    env.controller.error = RuntimeError("datapath failed")
    env.bus.publish(violation())
    assert env.bus.errors == []


def test_controller_exception_preserves_state():
    """Failed installation must leave the old path and dwell timestamp untouched."""
    env = environment(last=4)
    env.controller.error = RuntimeError("datapath failed")
    env.loop.on_violation(violation())
    assert db.current_path(env.conn, "INT-700").switches == NORTH
    assert db.load_intent(env.conn, "INT-700").last_replan_at == 4


def test_duplicate_event_is_idempotent():
    """Retrying delivery must not create fictitious reroute history."""
    env = environment()
    event = violation()
    env.loop.on_violation(event)
    env.loop.on_violation(event)
    assert db.reroute_count(env.conn, "INT-700") == 1


def test_event_time_is_used_when_now_omitted():
    """Event replay must preserve the original control decision timeline."""
    env = environment()
    env.loop.on_violation(violation(at=88))
    assert db.load_intent(env.conn, "INT-700").last_replan_at == 88


def test_invalid_payload_is_audited_without_installation():
    """Malformed monitoring data must fail safe instead of moving traffic."""
    env = environment()
    event = Event(EventType.SLA_VIOLATED, "bad", "INT-700", payload={})
    env.loop.on_violation(event)
    assert not env.controller.calls and env.audit.history("INT-700")


def test_loop_operates_without_ryu_or_mininet():
    """Software verification must remain possible on ordinary developer machines."""
    env = environment()
    env.loop.on_violation(violation())
    assert env.controller.calls


def test_dwell_reduces_oscillation():
    """The closed loop must damp repeated breaches instead of route-flapping."""
    def run(dwell):
        env = environment(dwell=dwell)
        for at in range(1, 10):
            env.loop.on_violation(violation(at=at), now=at)
        return db.reroute_count(env.conn, "INT-700")

    undamped = run(0)
    damped = run(10)
    assert undamped > damped
    assert damped <= 2
