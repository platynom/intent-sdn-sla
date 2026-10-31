#!/usr/bin/env python3
"""Validate and compare independent B2/B3 closed-loop run CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable

REQUIRED = {"run_id", "timestamp", "metric", "value", "unit"}
T95 = (0.0, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306,
       2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110,
       2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056,
       2.052, 2.048, 2.045, 2.042)
COMPARABLE = {
    "detection_latency": "ms",
    "recovery_latency": "ms",
    "reroute_count": "count",
}


def read_run(path: Path) -> Dict[str, float]:
    """Read a single-run file; reject duplicate/malformed metrics explicitly."""
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
            raise ValueError(f"{path}: missing required CSV columns")
        values: Dict[str, float] = {}
        units: Dict[str, str] = {}
        run_ids = set()
        for row in reader:
            metric = row["metric"]
            if metric in values:
                raise ValueError(f"{path}: duplicate metric {metric}")
            try:
                value = float(row["value"])
                run_ids.add(int(row["run_id"]))
                float(row["timestamp"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}: invalid numeric row {row}") from exc
            if not math.isfinite(value):
                raise ValueError(f"{path}: non-finite {metric} value")
            values[metric] = value
            units[metric] = row["unit"]
    if not values:
        raise ValueError(f"{path}: no measurement rows")
    if len(run_ids) != 1:
        raise ValueError(f"{path}: expected one run_id, found {sorted(run_ids)}")
    if getattr(read_run, "_units", None) is None:
        read_run._units = {}  # type: ignore[attr-defined]
    read_run._units[str(path)] = {"units": units, "run_id": next(iter(run_ids))}  # type: ignore[attr-defined]
    return values


def analyze(paths: Iterable[Path]) -> dict:
    """Return run-level observations and cautious t summaries by metric."""
    observations = defaultdict(list)
    exclusions = []
    run_records = []
    for path in sorted(paths):
        baseline = "B2" if path.name.startswith("b2_") else "B3" if path.name.startswith("b3_") else None
        if baseline is None:
            exclusions.append({"file": path.name, "reason": "filename is not B2/B3"})
            continue
        try:
            values = read_run(path)
        except (OSError, ValueError) as exc:
            exclusions.append({"file": path.name, "reason": str(exc)})
            continue
        metadata = read_run._units[str(path)]  # type: ignore[attr-defined]
        units = metadata["units"]
        recognized = {}
        for metric, value in values.items():
            if metric not in COMPARABLE:
                exclusions.append({"file": path.name, "metric": metric,
                                   "reason": "metric is outside the predefined B2/B3 comparison"})
                continue
            if units[metric] != COMPARABLE[metric]:
                exclusions.append({"file": path.name, "metric": metric,
                                   "reason": f"expected unit {COMPARABLE[metric]}, got {units[metric]}"})
                continue
            observations[(baseline, metric, units[metric])].append(
                {"file": path.name, "value": value}
            )
            recognized[metric] = value
        run_records.append({"baseline": baseline, "file": path.name,
                            "run_id": metadata["run_id"],
                            "values": recognized})

    summaries = []
    for (baseline, metric, unit), runs in sorted(observations.items()):
        values = [run["value"] for run in runs]
        n = len(values)
        mean = statistics.mean(values)
        sd = statistics.stdev(values) if n > 1 else None
        if sd is None:
            low = high = None
        else:
            critical = T95[n - 1] if n <= 31 else 1.96
            margin = critical * sd / math.sqrt(n)
            low, high = mean - margin, mean + margin
        summaries.append({"baseline": baseline, "metric": metric, "unit": unit,
                          "n_independent_runs": n, "individual_runs": runs,
                          "mean": mean, "sample_stddev": sd,
                          "ci95_t_low": low, "ci95_t_high": high,
                          "ci_method": "two-sided Student t" if n > 1 else None})
    return {"comparability": "provisional; B2 and B3 have latency-only intents and use the same controlled primary-link delay; detector and update policies differ by definition. B3 currently has one run.",
            "summaries": summaries, "runs": run_records, "exclusions": exclusions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("experiments/results/raw"))
    parser.add_argument("--output", type=Path,
                        default=Path("experiments/results/summary/b2_b3_comparison.json"))
    args = parser.parse_args()
    result = analyze(args.raw_dir.glob("b[23]_closed_loop_*.csv"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(result['summaries'])} metric summaries to {args.output}; "
          f"valid runs={len(result['runs'])}, exclusions={len(result['exclusions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
