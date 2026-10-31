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
    welch_tests: List[dict],
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
        "welch_tests": welch_tests,
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


def main() -> int:
    raw_dir = Path("experiments/results/raw")
    summary_dir = Path("experiments/results/summary")
    e4 = summarize_e4(raw_dir, summary_dir)
    if e4 is not None:
        print(f"E4 summary written ({len(e4['runs'])} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
