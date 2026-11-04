"""Ensure evaluation accounting cannot silently truncate the causal history."""

from experiments.e6_accounting import counts_for_run
from src.common import db
from src.common.events import Event, EventType


def test_run_accounting_counts_beyond_dashboard_history_page():
    """Truncating the audit view would falsely report missing violation events."""
    conn = db.connect(":memory:")
    db.init_db(conn)
    for cycle in range(90):
        for offset, kind in enumerate((EventType.SLA_VIOLATED, EventType.PATH_INSTALLED,
                                       EventType.PATH_INSTALLED, EventType.SLA_RESTORED)):
            db.save_event(conn, Event(type=kind, intent_id="INT-006", message="accounting fixture",
                                      at=cycle * 4 + offset))
    assert sum(e.type is EventType.SLA_VIOLATED for e in db.events_for(conn, "INT-006")) == 50
    assert counts_for_run(conn, "INT-006", 0)["sla.violated"] == 90
    conn.close()


def test_run_accounting_filters_intent_and_start_without_losing_boundary():
    """Cross-run or cross-intent leakage would invalidate the experiment's totals."""
    conn = db.connect(":memory:")
    db.init_db(conn)
    for intent, at in (("INT-006", 9), ("INT-006", 10), ("INT-007", 11)):
        db.save_event(conn, Event(type=EventType.SLA_VIOLATED, intent_id=intent,
                                  message="boundary fixture", at=at))
    assert counts_for_run(conn, "INT-006", 10) == {"sla.violated": 1}
    conn.close()
