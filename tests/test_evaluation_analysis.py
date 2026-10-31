"""Validation and deterministic trace tests for evaluation additions."""

import csv

import pytest

from experiments.analyze_closed_loop import analyze, read_run
from experiments.scenarios.alternating_trace import replay_trace
from experiments.scenarios.udp_seq_probe import analyze_window


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


def test_udp_seq_probe_analyze_window_counts_lost_duplicated_and_reordered(tmp_path):
    tx_log = tmp_path / "tx.csv"
    rx_log = tmp_path / "rx.csv"
    tx_log.write_text(
        "seq,tx_time\n"
        "1,9.0\n"
        "2,10.0\n"
        "3,10.1\n"
        "4,10.2\n"
        "5,10.3\n"
        "6,15.0\n",
        encoding="utf-8",
    )
    rx_log.write_text(
        "seq,tx_time,rx_time\n"
        "1,9.0,9.01\n"
        "2,10.0,10.01\n"
        "5,10.3,10.31\n"
        "4,10.2,10.35\n"
        "4,10.2,10.36\n"
        "6,15.0,15.01\n",
        encoding="utf-8",
    )
    stats = analyze_window(tx_log, rx_log, 10.0, 14.0)
    assert stats == {
        "packets_sent": 4,
        "packets_received": 3,
        "packets_lost": 1,
        "packets_duplicated": 1,
        "packets_reordered": 1,
    }
