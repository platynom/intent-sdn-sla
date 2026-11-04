#!/usr/bin/env python3
"""Replay alternating SLA breach/recovery phases through the real detector.

This deterministic software-only trace measures detector and dwell transitions.
It does not instantiate Mininet, invoke the control loop, or claim live reroutes.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from src.common.events import EventType
from src.common.models import Guarantee, IntentRecord, Match, Measurement
from src.telemetry.detector import ViolationDetector


def replay_trace(run_id: str = "alternating-dwell-v1", dwell_seconds: int = 10) -> list[dict]:
    """Replay high/low delay phases and return one observation per sample."""
    intent = IntentRecord(
        id="TRACE-001", tenant="trace", priority=1,
        match=Match(src="10.0.0.1", dst="10.0.0.2"),
        guarantee=Guarantee(max_latency_ms=20.0), dwell_seconds=dwell_seconds,
    )
    detector = ViolationDetector(
        intent, ewma_alpha=1.0, hysteresis_pct=0.1, consecutive_required=1,
    )
    # Each phase has one sample, alternating above and below the latency SLA.
    phases = ["violation", "recovery", "violation", "recovery",
              "violation", "recovery", "violation", "recovery", "violation"]
    delays = {"violation": 30.0, "recovery": 10.0}
    rows = []
    sample_times = [0, 1, 2, 3, 10, 11, 12, 13, 20]
    for at, phase in zip(sample_times, phases):
        delay = delays[phase]
        sample = Measurement("TRACE-001", at, delay_ms=delay)
        event = detector.observe(sample, now=float(at))
        if event is not None and event.type is EventType.SLA_VIOLATED:
            # Model one successful replan timestamp so later detector events
            # exercise the same IntentRecord dwell gate. No network install occurs.
            intent.last_replan_at = event.at
        payload = event.payload if event else {}
        rows.append({
            "run_id": run_id, "sample_time_s": at, "phase": phase,
            "delay_ms": delay, "sla_limit_ms": 20.0,
            "detector_status": detector.status.value,
            "event": event.type.value if event else "none",
            "event_time_s": event.at if event else "",
            "dwell_seconds_remaining": payload.get("seconds_remaining", ""),
            "reroute_decision_count": sum(
                row["event"] == EventType.SLA_VIOLATED.value for row in rows
            ) + int(event is not None and event.type is EventType.SLA_VIOLATED),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="alternating-dwell-v1")
    parser.add_argument("--dwell-seconds", type=int, default=10)
    parser.add_argument("--output", type=Path,
                        default=Path("experiments/results/raw/alternating_trace.csv"))
    args = parser.parse_args()
    if args.dwell_seconds < 0:
        parser.error("--dwell-seconds must be non-negative")
    rows = replay_trace(args.run_id, args.dwell_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} deterministic samples to {args.output}; "
          f"reroute decisions={sum(row['event'] == EventType.SLA_VIOLATED.value for row in rows)}, "
          f"dwell suppressions={sum(row['event'] == EventType.VIOLATION_SUPPRESSED.value for row in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
