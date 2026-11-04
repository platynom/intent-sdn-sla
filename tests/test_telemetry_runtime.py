"""Regression coverage for persistence at the live telemetry boundary."""

from src.common import db
from src.common.events import EventType, sla_violated
from src.common.models import Guarantee, IntentRecord, Match, Measurement
from src.telemetry.detector import ViolationDetector
from src.telemetry.runtime import (
    persist_confirmed_event,
    reload_persisted_replan_state,
)


def test_confirmed_violation_is_persisted_for_st7():
    """An in-process detector event must survive for ST-7 subscribers and audit."""
    conn = db.connect(":memory:")
    db.init_db(conn)
    event = sla_violated("INT-001", "delay_ms", 31.2, 20.0)

    persist_confirmed_event(conn, event)

    stored = db.events_for(conn, "INT-001")
    assert len(stored) == 1
    assert stored[0].id == event.id
    assert stored[0].type is event.type
    assert stored[0].payload == event.payload
    conn.close()


def test_no_event_does_not_write_an_event_row():
    """Healthy samples must not create fabricated event history."""
    conn = db.connect(":memory:")
    db.init_db(conn)

    persist_confirmed_event(conn, None)

    assert db.events_for(conn) == []
    conn.close()


def test_runtime_reloads_controller_replan_time_before_dwell_check(tmp_path):
    """A separate telemetry process must honor the controller's persisted dwell."""
    path = tmp_path / "state.db"
    runtime_conn = db.connect(path)
    controller_conn = db.connect(path)
    db.init_db(runtime_conn)
    intent = IntentRecord(
        id="INT-700",
        tenant="telemedicine-video",
        priority=1,
        match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", 5001),
        guarantee=Guarantee(max_latency_ms=20),
        dwell_seconds=10,
    )
    db.save_intent(runtime_conn, intent)
    detector = ViolationDetector(
        db.load_intent(runtime_conn, intent.id),
        ewma_alpha=1,
        hysteresis_pct=0,
        consecutive_required=1,
    )

    updated = db.load_intent(controller_conn, intent.id)
    updated.last_replan_at = 100
    db.save_intent(controller_conn, updated)

    assert detector.intent.last_replan_at is None
    assert reload_persisted_replan_state(runtime_conn, detector)
    event = detector.observe(
        Measurement(intent.id, 105, delay_ms=30),
        now=105,
    )
    assert event is not None
    assert event.type is EventType.VIOLATION_SUPPRESSED
    assert event.payload["seconds_remaining"] == 5
    runtime_conn.close()
    controller_conn.close()
