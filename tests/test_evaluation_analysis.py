"""Validation and deterministic trace tests for evaluation additions."""

import csv

import pytest

from experiments.analyze_closed_loop import analyze, read_run
from experiments.scenarios.alternating_trace import replay_trace


def write_run(path, metrics):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["run_id", "timestamp", "metric", "value", "unit"])
        for metric, value, unit in metrics:
            writer.writerow([1, 1000, metric, value, unit])


def test_analysis_aggregates_independent_run_files_with_student_t_ci(tmp_path):
    metrics = [("detection_latency", 100, "ms"),
               ("recovery_latency", 300, "ms"), ("reroute_count", 1, "count")]
    write_run(tmp_path / "b2_closed_loop_1.csv", metrics)
    write_run(tmp_path / "b2_closed_loop_2.csv", [(m, v + (10 if m != "reroute_count" else 0), u)
                                                   for m, v, u in metrics])
    result = analyze(tmp_path.glob("*.csv"))
    detection = next(row for row in result["summaries"]
                     if row["metric"] == "detection_latency")
    assert detection["n_independent_runs"] == 2
    assert detection["individual_runs"] == [
        {"file": "b2_closed_loop_1.csv", "value": 100.0},
        {"file": "b2_closed_loop_2.csv", "value": 110.0},
    ]
    assert detection["mean"] == 105
    assert detection["ci95_t_low"] < detection["mean"] < detection["ci95_t_high"]


def test_analysis_excludes_duplicate_metric_file(tmp_path):
    path = tmp_path / "b3_closed_loop_duplicate.csv"
    write_run(path, [("detection_latency", 100, "ms"),
                     ("detection_latency", 110, "ms")])
    result = analyze([path])
    assert result["runs"] == []
    assert "duplicate metric" in result["exclusions"][0]["reason"]


def test_read_run_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("metric,value\ndetection_latency,5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required CSV columns"):
        read_run(path)


def test_alternating_trace_records_violation_recovery_and_dwell():
    rows = replay_trace()
    events = [row["event"] for row in rows]
    assert events.count("sla.violated") == 3
    assert events.count("sla.restored") == 4
    assert events.count("violation.suppressed") == 2
    assert rows[0]["event_time_s"] == 0.0
    assert rows[2]["dwell_seconds_remaining"] == 8.0
    assert rows[-1]["reroute_decision_count"] == 3
