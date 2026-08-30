"""
ST-3 gate tests: the shared interfaces behave as every module assumes.

These are the contract three people build against in parallel. A change that
breaks one of these breaks somebody else's module, which is exactly the late
integration failure the ST-3 gate exists to prevent.
"""

from __future__ import annotations

import time

import pytest

from src.common import db as dbm
from src.common.audit import AuditLog
from src.common.events import (
    Event,
    EventBus,
    EventType,
    Severity,
    path_installed,
    sla_restored,
    sla_violated,
    violation_suppressed,
)
from src.common.models import (
    AdmissionDecision,
    Consistency,
    Guarantee,
    IntentRecord,
    IntentState,
    LinkState,
    Match,
    Measurement,
    OnViolation,
    PathPlan,
    Verdict,
)
from src.intent_manager.validator import validate_file

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def conn():
    c = dbm.connect(":memory:")
    dbm.init_db(c)
    yield c
    c.close()


def sample_intent(intent_id="INT-001", priority=1, dwell=10, **g):
    return IntentRecord(
        id=intent_id,
        tenant="telemedicine-video",
        priority=priority,
        match=Match(src="10.0.0.1/32", dst="10.0.0.2/32", proto="udp", dport=5001),
        guarantee=Guarantee(**(g or {"min_bandwidth_mbps": 20.0, "max_latency_ms": 20.0})),
        dwell_seconds=dwell,
    )


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

def test_every_shipped_intent_converts_to_a_record():
    """M1's validator output must feed straight into the shared model."""
    for path in sorted((REPO / "intents").glob("s*.yaml")):
        result = validate_file(path)
        assert result.ok, path.name
        rec = IntentRecord.from_document({"intent": result.intent})
        assert rec.id == result.intent["id"]
        assert 1 <= rec.priority <= 5


def test_defaults_match_the_schema():
    """Fields omitted from YAML must default the same way the schema documents."""
    rec = IntentRecord.from_document(
        {
            "intent": {
                "id": "INT-050",
                "tenant": "t",
                "priority": 2,
                "match": {"src": "10.0.0.1/32", "dst": "10.0.0.2/32"},
                "guarantee": {"min_bandwidth_mbps": 5},
            }
        }
    )
    assert rec.consistency is Consistency.STRICT
    assert rec.on_violation is OnViolation.REROUTE
    assert rec.dwell_seconds == 10
    assert rec.state is IntentState.PENDING


def test_dwell_timer_blocks_then_allows():
    """The anti-oscillation rule lives in exactly one place. This is it."""
    rec = sample_intent(dwell=10)
    assert rec.may_replan_at() is True, "never replanned yet, must be allowed"

    now = time.time()
    rec.last_replan_at = now
    assert rec.may_replan_at(now + 1) is False
    assert rec.may_replan_at(now + 9.99) is False
    assert rec.may_replan_at(now + 10) is True


def test_dwell_zero_never_blocks():
    """Scenario S6 runs with dwell 0 to show the loop flapping."""
    rec = sample_intent(dwell=0)
    rec.last_replan_at = time.time()
    assert rec.may_replan_at() is True


def test_path_links_are_canonical():
    links = PathPlan.links_for(["s1", "s2", "s3", "s7"])
    assert links == ("s1-s2", "s2-s3", "s3-s7")


def test_path_link_naming_is_direction_independent():
    fwd = set(PathPlan.links_for(["s1", "s6", "s7"]))
    rev = set(PathPlan.links_for(["s7", "s6", "s1"]))
    assert fwd == rev == {"s1-s6", "s6-s7"}


def test_disjointness():
    north = PathPlan("INT-001", ("s1", "s2", "s3", "s7"),
                     PathPlan.links_for(["s1", "s2", "s3", "s7"]), 6.0, 100.0)
    south = PathPlan("INT-001", ("s1", "s6", "s7"),
                     PathPlan.links_for(["s1", "s6", "s7"]), 24.0, 40.0)
    assert north.is_disjoint_from(south)
    assert not north.is_disjoint_from(north)


def test_link_state_reservation_and_release():
    link = LinkState("s1-s2", capacity_mbps=100.0, base_delay_ms=2.0)
    assert link.residual_mbps == 100.0
    link.reserve(30.0)
    assert link.residual_mbps == 70.0
    with pytest.raises(ValueError):
        link.reserve(80.0)
    link.release(30.0)
    assert link.residual_mbps == 100.0


def test_link_release_cannot_go_negative():
    link = LinkState("s1-s2", 100.0, 2.0, reserved_mbps=10.0)
    link.release(50.0)
    assert link.reserved_mbps == 0.0


def test_down_link_admits_nothing():
    link = LinkState("s1-s2", 100.0, 2.0, up=False)
    assert link.can_admit(1.0) is False


def test_measurement_violation_predicate():
    g = Guarantee(min_bandwidth_mbps=20.0, max_latency_ms=20.0, max_loss_pct=0.5)
    ok = Measurement("INT-001", time.time(), delay_ms=10, loss_pct=0.1, throughput_mbps=25)
    assert not ok.violates(g)
    assert Measurement("INT-001", 0, delay_ms=21).violates(g)
    assert Measurement("INT-001", 0, loss_pct=0.6).violates(g)
    assert Measurement("INT-001", 0, throughput_mbps=19).violates(g)


def test_missing_fields_never_count_as_violations():
    """A metric we did not measure must not be reported as breached."""
    g = Guarantee(max_latency_ms=20.0, max_loss_pct=0.5)
    assert not Measurement("INT-001", 0).violates(g)


def test_decision_requires_a_reason():
    with pytest.raises(ValueError):
        AdmissionDecision("INT-001", Verdict.REJECT, "")
    with pytest.raises(ValueError):
        AdmissionDecision("INT-001", Verdict.REJECT, "   ")


def test_preempt_and_degrade_carry_their_extra_field():
    with pytest.raises(ValueError):
        AdmissionDecision("INT-001", Verdict.PREEMPT, "no room")
    with pytest.raises(ValueError):
        AdmissionDecision("INT-001", Verdict.DEGRADE, "reduced")
    ok = AdmissionDecision("INT-001", Verdict.PREEMPT, "no room",
                           preempted_intent_id="INT-009")
    assert ok.admitted


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #

def test_event_requires_a_message():
    with pytest.raises(ValueError):
        Event(type=EventType.SLA_VIOLATED, message="")


def test_event_json_round_trip():
    ev = sla_violated("INT-001", "delay_ms", 31.2, 20.0)
    back = Event.from_json(ev.to_json())
    assert back.id == ev.id
    assert back.type is ev.type
    assert back.payload == ev.payload


def test_constructors_produce_readable_messages():
    assert "31.2" in sla_violated("INT-001", "delay_ms", 31.2, 20.0).message
    assert "back within" in sla_restored("INT-001", "delay_ms", 12.0).message
    assert "not acted on" in violation_suppressed("INT-001", "dwell timer", 4.0).message
    assert "s1 -> s2" in path_installed("INT-001", ["s1", "s2"], "strict", 6).message


def test_bus_delivers_to_typed_and_wildcard_subscribers():
    bus = EventBus()
    typed, everything = [], []
    bus.subscribe(typed.append, EventType.SLA_VIOLATED)
    bus.subscribe(everything.append)
    bus.publish(sla_violated("INT-001", "delay_ms", 30, 20))
    bus.publish(sla_restored("INT-001", "delay_ms", 10))
    assert len(typed) == 1
    assert len(everything) == 2


def test_a_broken_subscriber_does_not_stop_the_loop():
    """One failing dashboard must not take the control loop down with it."""
    bus = EventBus()
    delivered = []

    def broken(_ev):
        raise RuntimeError("dashboard is down")

    bus.subscribe(broken)
    bus.subscribe(delivered.append)
    bus.publish(sla_violated("INT-001", "delay_ms", 30, 20))

    assert len(delivered) == 1
    assert len(bus.errors) == 1


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #

def test_schema_initialises_and_reports_its_version(conn):
    assert dbm.schema_version(conn) == dbm.SCHEMA_VERSION


def test_intent_round_trip(conn):
    rec = sample_intent()
    dbm.save_intent(conn, rec)
    back = dbm.load_intent(conn, rec.id)
    assert back is not None
    assert back.id == rec.id
    assert back.guarantee == rec.guarantee
    assert back.match == rec.match
    assert back.consistency is rec.consistency


def test_saving_twice_updates_rather_than_duplicates(conn):
    rec = sample_intent()
    dbm.save_intent(conn, rec)
    rec.state = IntentState.ACTIVE
    dbm.save_intent(conn, rec)
    assert dbm.load_intent(conn, rec.id).state is IntentState.ACTIVE
    n = conn.execute("SELECT COUNT(*) AS n FROM intents").fetchone()["n"]
    assert n == 1


def test_active_intents_ordered_for_preemption(conn):
    """Lowest priority first: that is the order M2 evicts in."""
    for i, pri in enumerate([1, 5, 3], start=1):
        r = sample_intent(f"INT-00{i}", priority=pri)
        r.state = IntentState.ACTIVE
        dbm.save_intent(conn, r)
    rejected = sample_intent("INT-009", priority=2)
    rejected.state = IntentState.REJECTED
    dbm.save_intent(conn, rejected)

    active = dbm.active_intents(conn)
    assert [a.priority for a in active] == [1, 3, 5]
    assert "INT-009" not in [a.id for a in active]


def test_saving_a_path_supersedes_the_previous_one(conn):
    dbm.save_intent(conn, sample_intent())
    first = PathPlan("INT-001", ("s1", "s2", "s3", "s7"),
                     PathPlan.links_for(["s1", "s2", "s3", "s7"]), 6.0, 100.0)
    dbm.save_path(conn, first)
    second = PathPlan("INT-001", ("s1", "s6", "s7"),
                      PathPlan.links_for(["s1", "s6", "s7"]), 24.0, 40.0)
    dbm.save_path(conn, second)

    current = dbm.current_path(conn, "INT-001")
    assert current.switches == ("s1", "s6", "s7")

    live = conn.execute(
        "SELECT COUNT(*) AS n FROM paths WHERE intent_id='INT-001' "
        "AND superseded_at IS NULL"
    ).fetchone()["n"]
    assert live == 1, "an intent must never appear to have two current paths"


def test_reroute_count_excludes_the_first_install(conn):
    dbm.save_intent(conn, sample_intent())
    assert dbm.reroute_count(conn, "INT-001") == 0
    for switches in (["s1", "s2", "s3", "s7"], ["s1", "s6", "s7"], ["s1", "s4", "s5", "s7"]):
        dbm.save_path(conn, PathPlan("INT-001", tuple(switches),
                                     PathPlan.links_for(switches), 1.0, 1.0))
    assert dbm.reroute_count(conn, "INT-001") == 2


def test_measurements_persist(conn):
    dbm.save_intent(conn, sample_intent())
    now = time.time()
    dbm.save_measurement(conn, "INT-001", now, delay_ms=12.5, loss_pct=0.1)
    rows = list(dbm.measurements_for(conn, "INT-001"))
    assert len(rows) == 1
    assert rows[0]["delay_ms"] == 12.5


def test_events_persist_and_are_deduplicated(conn):
    ev = sla_violated("INT-001", "delay_ms", 30, 20)
    dbm.save_event(conn, ev)
    dbm.save_event(conn, ev)
    assert len(dbm.events_for(conn)) == 1


def test_deleting_an_intent_cascades(conn):
    dbm.save_intent(conn, sample_intent())
    dbm.save_path(conn, PathPlan("INT-001", ("s1", "s2"),
                                 PathPlan.links_for(["s1", "s2"]), 2.0, 100.0))
    dbm.save_measurement(conn, "INT-001", time.time(), delay_ms=1.0)
    conn.execute("DELETE FROM intents WHERE id='INT-001'")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) AS n FROM paths").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM measurements").fetchone()["n"] == 0


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #

def test_audit_records_the_full_causal_chain(conn):
    audit = AuditLog(conn)
    chain = audit.chain(
        intent_id="INT-001",
        measurement="delay 31.2 ms over 5 samples",
        threshold="max_latency_ms 20",
        decision="violation confirmed after hysteresis and dwell",
        action="rerouted s1-s2-s3-s7 to s1-s4-s5-s7",
    )
    rendered = chain.render()
    for part in ("measured", "promised", "decided", "did"):
        assert part in rendered
    assert "31.2" in rendered and "20" in rendered

    stored = dbm.events_for(conn, "INT-001")
    assert len(stored) == 1
    for key in ("measurement", "threshold", "decision", "action"):
        assert key in stored[0].payload


def test_audit_attached_to_a_bus_fills_itself(conn):
    bus = EventBus()
    audit = AuditLog(conn, bus)
    bus.subscribe(audit.record)
    bus.publish(sla_violated("INT-001", "delay_ms", 30, 20))
    bus.publish(sla_restored("INT-001", "delay_ms", 10))
    assert len(dbm.events_for(conn, "INT-001")) == 2
    assert bus.errors == []


def test_explain_is_readable_by_someone_who_has_not_seen_the_code(conn):
    audit = AuditLog(conn)
    audit.emit(sla_violated("INT-001", "delay_ms", 31.2, 20.0))
    audit.emit(sla_restored("INT-001", "delay_ms", 11.0))
    text = audit.explain("INT-001")
    assert "INT-001" in text
    assert text.index("31.2") < text.index("11"), "oldest first"


def test_explain_handles_an_unknown_intent(conn):
    assert "no recorded events" in AuditLog(conn).explain("INT-999")
