"""Keep simulated samples out of charts after a live measurement event arrives."""
import json

import yaml

from scripts import seed_demo_intents
from src.common import db
from src.common.events import Event, EventType
from src.common.models import IntentRecord, IntentState
from src.dashboard import app as dashboard_app
from src.pathing.compute import compute_path
from topology.topology_spec import build_graph


def test_live_measurement_event_does_not_hide_the_simulation_marker(tmp_path, monkeypatch):
    """A newer live event must not relabel old simulated samples as measured data."""
    database = tmp_path / "provenance.db"
    real_connect = db.connect
    conn = real_connect(database)
    db.init_db(conn)
    document = yaml.safe_load(seed_demo_intents.SEED_FILES[0].read_text(encoding="utf-8"))
    record = IntentRecord.from_document(document)
    record.state = IntentState.ADMITTED
    plan, _ = compute_path(record, build_graph())
    db.save_intent(conn, record)
    db.save_path(conn, plan)
    monkeypatch.setattr(db, "connect", lambda path=None: real_connect(path or database))
    assert seed_demo_intents.seed_demo_measurements(record.id, sample_count=2)
    payload = json.loads(conn.execute(
        "SELECT payload_json FROM events WHERE intent_id = ? AND type = ?",
        (record.id, EventType.MEASUREMENT_TAKEN.value),
    ).fetchone()[0])
    at = payload["sample_end_at"] + 1
    db.save_measurement(conn, record.id, at, delay_ms=4, loss_pct=0, throughput_mbps=8)
    db.save_event(conn, Event(type=EventType.MEASUREMENT_TAKEN, intent_id=record.id,
                              message="Actual collector reading", payload={"source": "live"}, at=at))
    snapshot = dashboard_app._snapshot(conn, record.id)
    assert snapshot["telemetry_source"] == "live"
    assert len(snapshot["measurements"]) == 1
    assert snapshot["measurements"][0]["at"] == at
    conn.close()
