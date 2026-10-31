#!/usr/bin/env python3
"""Compute summary statistics (mean, sample SD, 95% Student-t CI, Welch t-tests) for E1-E8 and O3."""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from experiments.analyze_closed_loop import T95, read_run, welch_t_test


def compute_ci(values: List[float]) -> dict:
    """Compute mean, sample SD, and two-sided 95% Student-t CI."""
    n = len(values)
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if n > 1 else None
    if sd is None:
        low = high = None
    else:
        critical = T95[n - 1] if n <= 31 else 1.96
        margin = critical * sd / math.sqrt(n)
        low, high = mean - margin, mean + margin
    return {
        "n_independent_runs": n,
        "mean": mean,
        "sample_stddev": sd,
        "ci95_t_low": low,
        "ci95_t_high": high,
        "min": min(values),
        "max": max(values),
        "ci_method": "two-sided Student t" if n > 1 else None,
    }


def summarize_group(
    paths: Iterable[Path],
    group_fn,
    allowed_metrics: Optional[Dict[str, str]] = None,
) -> dict:
    """Aggregate single-run CSV files grouped by group_fn(path) -> group_name."""
    observations = defaultdict(list)
    run_records = []
    for path in sorted(paths):
        group = group_fn(path)
        if group is None:
            continue
        values = read_run(path)
        metadata = read_run._units[str(path)]  # type: ignore[attr-defined]
        units = metadata["units"]
        rec_vals = {}
        for metric, val in values.items():
            if allowed_metrics is not None and metric not in allowed_metrics:
                continue
            unit = units[metric]
            observations[(group, metric, unit)].append({"file": path.name, "value": val})
            rec_vals[metric] = val
        run_records.append({
            "group": group,
            "file": path.name,
            "run_id": metadata["run_id"],
            "values": rec_vals,
        })

    summaries = []
    values_by_key: Dict[tuple, List[float]] = {}
    for (group, metric, unit), runs in sorted(observations.items()):
        vals = [r["value"] for r in runs]
        values_by_key[(group, metric)] = vals
        stats = compute_ci(vals)
        summaries.append({
            "group": group,
            "metric": metric,
            "unit": unit,
            **stats,
            "individual_runs": runs,
        })

    return {
        "summaries": summaries,
        "values_by_key": values_by_key,
        "runs": run_records,
    }


def write_summary_files(
    summaries: List[dict],
    statistical_tests: List[dict],
    runs: List[dict],
    json_path: Path,
    csv_path: Path,
    description: str = "",
) -> None:
    """Write JSON and CSV summary files."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "description": description,
        "summaries": summaries,
        "statistical_tests": statistical_tests,
        "runs": runs,
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "group", "metric", "n", "mean", "stdev",
            "ci95_t_low", "ci95_t_high", "min", "max", "unit",
        ])
        for row in summaries:
            sd_s = f"{row['sample_stddev']:.3f}" if row["sample_stddev"] is not None else ""
            lo_s = f"{row['ci95_t_low']:.3f}" if row["ci95_t_low"] is not None else ""
            hi_s = f"{row['ci95_t_high']:.3f}" if row["ci95_t_high"] is not None else ""
            writer.writerow([
                row["group"],
                row["metric"],
                row["n_independent_runs"],
                f"{row['mean']:.3f}",
                sd_s,
                lo_s,
                hi_s,
                f"{row['min']:.3f}",
                f"{row['max']:.3f}",
                row["unit"],
            ])


def summarize_e4(raw_dir: Path, summary_dir: Path) -> Optional[dict]:
    files = list(raw_dir.glob("e4_b[23]_reconfig_*.csv"))
    if not files:
        return None

    def classify(p: Path) -> Optional[str]:
        if p.name.startswith("e4_b2_"):
            return "B2"
        if p.name.startswith("e4_b3_"):
            return "B3"
        return None

    res = summarize_group(files, classify)
    welch = []
    for metric in ("packets_lost", "packets_duplicated", "packets_reordered", "packets_sent"):
        xs = res["values_by_key"].get(("B2", metric), [])
        ys = res["values_by_key"].get(("B3", metric), [])
        wt = welch_t_test(xs, ys)
        if wt is not None:
            welch.append({"metric": metric, "group_a": "B2", "group_b": "B3", **wt})
    write_summary_files(
        res["summaries"],
        welch,
        res["runs"],
        summary_dir / "e4_packet_loss_summary.json",
        summary_dir / "e4_packet_loss_summary.csv",
        description="E4 packet loss during reconfiguration (1,000 pkt/s UDP stream across [fault_inject - 2 s, path_installed + 2 s])",
    )
    return res


def summarize_e4_current(raw_dir: Path, summary_dir: Path) -> Optional[dict]:
    files = list(raw_dir.glob("e4current_b[23]_reconfig_*.csv"))
    if not files:
        return None
    def classify(path: Path) -> Optional[str]:
        if path.name.startswith("e4current_b2_"):
            return "B2"
        if path.name.startswith("e4current_b3_"):
            return "B3"
        return None
    res = summarize_group(files, classify)
    tests = []
    for metric in ("packets_lost", "packets_duplicated", "packets_reordered", "packets_sent"):
        result = welch_t_test(
            res["values_by_key"].get(("B2", metric), []),
            res["values_by_key"].get(("B3", metric), []),
        )
        if result is not None:
            tests.append({"metric": metric, "group_a": "B2", "group_b": "B3", **result})
    write_summary_files(
        res["summaries"], tests, res["runs"],
        summary_dir / "e4_current_packet_loss_summary.json",
        summary_dir / "e4_current_packet_loss_summary.csv",
        description="Current-code E4 packet loss and reordering during reconfiguration",
    )
    return res


def summarize_b3_current(raw_dir: Path, summary_dir: Path) -> Optional[dict]:
    files = list(raw_dir.glob("b3_current_closed_loop_*.csv"))
    if not files:
        return None
    res = summarize_group(files, lambda _path: "B3-current")
    write_summary_files(
        res["summaries"], [], res["runs"],
        summary_dir / "b3_current_closed_loop_summary.json",
        summary_dir / "b3_current_closed_loop_summary.csv",
        description="B3 closed-loop results rerun after controller concurrency and persisted-dwell fixes",
    )
    return res


def summarize_o3(raw_dir: Path, summary_dir: Path) -> Optional[dict]:
    files = list(raw_dir.glob("o3_queue_*.csv"))
    if not files:
        return None

    def classify(p: Path) -> Optional[str]:
        if p.name.startswith("o3_queue_bound_"):
            return "bound"
        if p.name.startswith("o3_queue_unbound_"):
            return "unbound"
        return None

    res = summarize_group(files, classify)
    welch = []
    for metric in (
        "intent_throughput_mbps",
        "intent_loss_pct",
        "cross_traffic_throughput_mbps",
        "cross_traffic_loss_pct",
    ):
        xs = res["values_by_key"].get(("bound", metric), [])
        ys = res["values_by_key"].get(("unbound", metric), [])
        wt = welch_t_test(xs, ys)
        if wt is not None:
            welch.append({"metric": metric, "group_a": "bound", "group_b": "unbound", **wt})
    write_summary_files(
        res["summaries"],
        welch,
        res["runs"],
        summary_dir / "o3_queue_binding_summary.json",
        summary_dir / "o3_queue_binding_summary.csv",
        description="Objective O3: 20 Mbit/s SLA intent vs competing 150 Mbit/s iperf3 cross-traffic (SET_QUEUE bound vs unbound control)",
    )
    return res


def summarize_o3_current(raw_dir: Path, summary_dir: Path) -> Optional[dict]:
    files = list(raw_dir.glob("o3current_queue_bound_*.csv"))
    if not files:
        return None
    res = summarize_group(files, lambda _path: "bound")
    write_summary_files(
        res["summaries"], [], res["runs"],
        summary_dir / "o3_current_queue_binding_summary.json",
        summary_dir / "o3_current_queue_binding_summary.csv",
        description="Current-code O3 bound queue using topology-derived egress capacity",
    )
    return res


def summarize_e5(raw_dir: Path, summary_dir: Path) -> Optional[dict]:
    files = list(raw_dir.glob("e5_*.csv"))
    if not files:
        return None

    def classify(p: Path) -> Optional[str]:
        if p.name.startswith("e5_all_strict_"):
            return "all_strict"
        if p.name.startswith("e5_selective_"):
            return "selective"
        if p.name.startswith("e5_all_relaxed_"):
            return "all_relaxed"
        return None

    res = summarize_group(files, classify)
    welch = []
    for metric in ("peak_rules_max_switch", "peak_rules_total", "packets_lost"):
        for g1, g2 in (
            ("all_strict", "all_relaxed"),
            ("all_strict", "selective"),
            ("selective", "all_relaxed"),
        ):
            xs = res["values_by_key"].get((g1, metric), [])
            ys = res["values_by_key"].get((g2, metric), [])
            wt = welch_t_test(xs, ys)
            if wt is not None:
                welch.append({"metric": metric, "group_a": g1, "group_b": g2, **wt})
    write_summary_files(
        res["summaries"],
        welch,
        res["runs"],
        summary_dir / "e5_flow_table_summary.json",
        summary_dir / "e5_flow_table_summary.csv",
        description="E5 flow-table entries and reconfiguration packet loss across all_strict, selective (50/50 strict/relaxed), and all_relaxed modes (citing CCG, Zhou et al., NSDI 2015)",
    )
    return res


def summarize_e6(raw_dir: Path, summary_dir: Path) -> Optional[dict]:
    files = list(raw_dir.glob("e6_oscillation_*.csv"))
    if not files:
        return None

    def classify(p: Path) -> Optional[str]:
        if p.name.startswith("e6_oscillation_b2_"):
            return "B2"
        if p.name.startswith("e6_oscillation_b3_"):
            return "B3"
        return None

    res = summarize_group(files, classify)
    welch = []
    for metric in (
        "reroute_count_10min",
        "raw_reroute_count",
        "violations_emitted",
        "dwell_suppressions",
    ):
        xs = res["values_by_key"].get(("B2", metric), [])
        ys = res["values_by_key"].get(("B3", metric), [])
        wt = welch_t_test(xs, ys)
        if wt is not None:
            welch.append({"metric": metric, "group_a": "B2", "group_b": "B3", **wt})
    write_summary_files(
        res["summaries"],
        welch,
        res["runs"],
        summary_dir / "e6_oscillation_summary.json",
        summary_dir / "e6_oscillation_summary.csv",
        description="E6 route oscillation (reroutes per 10 min) on Scenario S6 (intents/s6_oscillation_trap.yaml), B2 (hysteresis+dwell OFF) vs B3 (hysteresis+dwell ON)",
    )
    return res


def summarize_e1(raw_dir: Path, summary_dir: Path) -> Optional[dict]:
    files = list(raw_dir.glob("e1_violation_duration_*.csv"))
    if not files:
        return None

    def classify(p: Path) -> Optional[str]:
        if p.name.startswith("e1_violation_duration_b1_"):
            return "B1"
        if p.name.startswith("e1_violation_duration_b3_"):
            return "B3"
        return None

    res = summarize_group(files, classify)
    welch = []
    for metric in ("sla_violation_duration_s",):
        xs = res["values_by_key"].get(("B1", metric), [])
        ys = res["values_by_key"].get(("B3", metric), [])
        wt = welch_t_test(xs, ys)
        if wt is not None:
            welch.append({"metric": metric, "group_a": "B1", "group_b": "B3", **wt})
    write_summary_files(
        res["summaries"],
        welch,
        res["runs"],
        summary_dir / "e1_violation_duration_summary.json",
        summary_dir / "e1_violation_duration_summary.csv",
        description="E1 SLA violation duration (s) from first breach sample to first restored-compliance sample (B1 right-censored at 15 s fault window vs B3 closed-loop)",
    )
    return res


def summarize_e7(raw_dir: Path, summary_dir: Path) -> Optional[dict]:
    files = list(raw_dir.glob("e7_admission_k*.csv"))
    if not files:
        return None

    def classify(p: Path) -> Optional[str]:
        for k in (1, 2, 4, 8, 16):
            if p.name.startswith(f"e7_admission_k{k:02d}_"):
                return f"k={k:02d}"
        return None

    res = summarize_group(files, classify)
    write_summary_files(
        res["summaries"],
        [],
        res["runs"],
        summary_dir / "e7_admission_scaling_summary.json",
        summary_dir / "e7_admission_scaling_summary.csv",
        description="E7 admission decision latency (ms) vs number of active intents (1, 2, 4, 8, 16)",
    )
    return res


def summarize_e8(raw_dir: Path, summary_dir: Path) -> Optional[dict]:
    files = list(raw_dir.glob("e8_overhead_*.csv"))
    if not files:
        return None

    def classify(p: Path) -> Optional[str]:
        if p.name.startswith("e8_overhead_b1_"):
            return "B1"
        if p.name.startswith("e8_overhead_b3_"):
            return "B3"
        return None

    res = summarize_group(files, classify)
    welch = []
    for metric in ("openflow_msgs_per_s", "controller_cpu_pct", "openflow_msgs_total"):
        xs = res["values_by_key"].get(("B1", metric), [])
        ys = res["values_by_key"].get(("B3", metric), [])
        wt = welch_t_test(xs, ys)
        if wt is not None:
            welch.append({"metric": metric, "group_a": "B1", "group_b": "B3", **wt})
    write_summary_files(
        res["summaries"],
        welch,
        res["runs"],
        summary_dir / "e8_control_overhead_summary.json",
        summary_dir / "e8_control_overhead_summary.csv",
        description="E8 control-plane overhead: OpenFlow message rate (msgs/s) and controller CPU % over a 60 s window (B1 vs B3; B3 has higher overhead as expected)",
    )
    return res


def summarize_e8_v2(raw_dir: Path, summary_dir: Path) -> Optional[dict]:
    """Summarize superseding E8 runs that cover the complete control stack."""
    files = list(raw_dir.glob("e8v2_overhead_*.csv"))
    if not files:
        return None

    def classify(p: Path) -> Optional[str]:
        if p.name.startswith("e8v2_overhead_b1_"):
            return "B1"
        if p.name.startswith("e8v2_overhead_b3_"):
            return "B3"
        return None

    res = summarize_group(files, classify)
    welch = []
    for metric in (
        "openflow_msgs_per_s",
        "openflow_msgs_total",
        "ryu_cpu_pct",
        "api_cpu_pct",
        "telemetry_cpu_pct",
        "probe_cpu_pct",
        "control_stack_cpu_pct",
    ):
        xs = res["values_by_key"].get(("B1", metric), [])
        ys = res["values_by_key"].get(("B3", metric), [])
        wt = welch_t_test(xs, ys)
        if wt is not None:
            welch.append({"metric": metric, "group_a": "B1", "group_b": "B3", **wt})
    write_summary_files(
        res["summaries"],
        welch,
        res["runs"],
        summary_dir / "e8v2_control_overhead_summary.json",
        summary_dir / "e8v2_control_overhead_summary.csv",
        description=(
            "E8v2 control-plane overhead over a 60 s window: OpenFlow message "
            "rate plus inclusive CPU for Ryu, API, telemetry runtime, active "
            "probe responder, and descendants. Supersedes the Ryu-only v1 CPU metric."
        ),
    )
    return res


def main() -> int:
    raw_dir = Path("experiments/results/raw")
    summary_dir = Path("experiments/results/summary")
    for label, fn in (
        ("E4", summarize_e4),
        ("E4-current", summarize_e4_current),
        ("B3-current", summarize_b3_current),
        ("O3", summarize_o3),
        ("O3-current", summarize_o3_current),
        ("E5", summarize_e5),
        ("E6", summarize_e6),
        ("E1", summarize_e1),
        ("E7", summarize_e7),
        ("E8", summarize_e8),
        ("E8v2", summarize_e8_v2),
    ):
        res = fn(raw_dir, summary_dir)
        if res is not None:
            print(f"{label} summary written ({len(res['runs'])} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
