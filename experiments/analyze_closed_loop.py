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
from typing import Dict, Iterable, List, Optional

REQUIRED = {"run_id", "timestamp", "metric", "value", "unit"}
T95 = (
    0.0, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306,
    2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110,
    2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056,
    2.052, 2.048, 2.045, 2.042,
)
COMPARABLE = {
    "detection_latency": "ms",
    "recovery_latency": "ms",
    "reroute_count": "count",
}


def _reg_inc_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta function I_x(a, b) via Lentz's method."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _reg_inc_beta(1.0 - x, b, a)
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - lbeta) / a
    f = 1.0
    c = 1.0
    d = 0.0
    for i in range(200):
        m = i // 2
        if i == 0:
            num = 1.0
        elif i % 2 == 0:
            num = (m * (b - m) * x) / ((a + 2.0 * m - 1.0) * (a + 2.0 * m))
        else:
            num = -((a + m) * (a + b + m) * x) / ((a + 2.0 * m) * (a + 2.0 * m + 1.0))
        d = 1.0 + num * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + num / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = c * d
        f *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return front * (f - 1.0)


def welch_t_test(xs: List[float], ys: List[float]) -> Optional[dict]:
    """Two-sided Welch two-sample t-test with Satterthwaite degrees of freedom."""
    n1, n2 = len(xs), len(ys)
    if n1 < 2 or n2 < 2:
        return None
    m1, m2 = statistics.mean(xs), statistics.mean(ys)
    v1, v2 = statistics.variance(xs), statistics.variance(ys)
    se2 = (v1 / n1) + (v2 / n2)
    if se2 <= 0.0:
        return {
            "t_statistic": 0.0,
            "degrees_of_freedom": float(n1 + n2 - 2),
            "p_value_two_sided": 1.0,
            "mean_diff": m1 - m2,
        }
    t_stat = (m1 - m2) / math.sqrt(se2)
    denom = ((v1 / n1) ** 2) / (n1 - 1) + ((v2 / n2) ** 2) / (n2 - 1)
    df = (se2 ** 2) / denom if denom > 0 else float(n1 + n2 - 2)
    x = df / (df + t_stat * t_stat)
    p_val = _reg_inc_beta(x, 0.5 * df, 0.5)
    return {
        "t_statistic": t_stat,
        "degrees_of_freedom": df,
        "p_value_two_sided": p_val,
        "mean_diff": m1 - m2,
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


def _classify_baseline(filename: str) -> Optional[str]:
    if filename.startswith("b2_matched_detector_"):
        return "B2_matched_detector"
    if filename.startswith("b2_"):
        return "B2"
    if filename.startswith("b3_"):
        return "B3"
    return None


def analyze(paths: Iterable[Path]) -> dict:
    """Return run-level observations, Student-t CIs, and Welch t-tests by metric."""
    observations = defaultdict(list)
    exclusions = []
    run_records = []
    for path in sorted(paths):
        baseline = _classify_baseline(path.name)
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
                exclusions.append({
                    "file": path.name,
                    "metric": metric,
                    "reason": "metric is outside the predefined B2/B3 comparison",
                })
                continue
            if units[metric] != COMPARABLE[metric]:
                exclusions.append({
                    "file": path.name,
                    "metric": metric,
                    "reason": f"expected unit {COMPARABLE[metric]}, got {units[metric]}",
                })
                continue
            observations[(baseline, metric, units[metric])].append(
                {"file": path.name, "value": value}
            )
            recognized[metric] = value
        run_records.append({
            "baseline": baseline,
            "file": path.name,
            "run_id": metadata["run_id"],
            "values": recognized,
        })

    summaries = []
    values_by_key: Dict[tuple, List[float]] = {}
    for (baseline, metric, unit), runs in sorted(observations.items()):
        values = [run["value"] for run in runs]
        values_by_key[(baseline, metric)] = values
        n = len(values)
        mean = statistics.mean(values)
        sd = statistics.stdev(values) if n > 1 else None
        if sd is None:
            low = high = None
        else:
            critical = T95[n - 1] if n <= 31 else 1.96
            margin = critical * sd / math.sqrt(n)
            low, high = mean - margin, mean + margin
        summaries.append({
            "baseline": baseline,
            "metric": metric,
            "unit": unit,
            "n_independent_runs": n,
            "individual_runs": runs,
            "mean": mean,
            "sample_stddev": sd,
            "ci95_t_low": low,
            "ci95_t_high": high,
            "ci_method": "two-sided Student t" if n > 1 else None,
        })

    welch_tests = []
    for metric in ("detection_latency", "recovery_latency"):
        for left, right in (("B2", "B3"), ("B2_matched_detector", "B3"), ("B2", "B2_matched_detector")):
            xs = values_by_key.get((left, metric), [])
            ys = values_by_key.get((right, metric), [])
            res = welch_t_test(xs, ys)
            if res is not None:
                welch_tests.append({
                    "metric": metric,
                    "group_a": left,
                    "group_b": right,
                    "n_a": len(xs),
                    "n_b": len(ys),
                    **res,
                })

    return {
        "comparability": (
            "B2, B2_matched_detector, and B3 have latency-only intents and use the same "
            "controlled primary-link 40 ms delay. B2 uses relaxed updates with alpha=1, "
            "hysteresis=0, consecutive=1; B2_matched_detector uses relaxed updates with "
            "B3's default detector (alpha=0.3, hysteresis=0.1, consecutive=3); B3 uses "
            "strict two-phase updates with default detector."
        ),
        "summaries": summaries,
        "welch_tests": welch_tests,
        "runs": run_records,
        "exclusions": exclusions,
    }


def write_csv_summary(result: dict, csv_path: Path) -> None:
    """Write a tabular CSV summary of all closed-loop baselines."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    descriptions = {
        "B2": "Controlled 40 ms primary-link delay; relaxed update; alpha=1; no hysteresis; one-sample confirmation",
        "B2_matched_detector": "Controlled 40 ms primary-link delay; relaxed update; default detector (alpha=0.3, hysteresis=0.1, 3-sample confirmation)",
        "B3": "Controlled 40 ms primary-link delay; strict versioned two-phase update; default detector (alpha=0.3, hysteresis=0.1, 3-sample confirmation)",
    }
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "baseline", "metric", "n", "mean", "stdev",
            "ci95_t_low", "ci95_t_high", "min", "max", "unit", "interpretation",
        ])
        for row in result["summaries"]:
            vals = [item["value"] for item in row["individual_runs"]]
            sd_str = f"{row['sample_stddev']:.3f}" if row["sample_stddev"] is not None else ""
            lo_str = f"{row['ci95_t_low']:.3f}" if row["ci95_t_low"] is not None else ""
            hi_str = f"{row['ci95_t_high']:.3f}" if row["ci95_t_high"] is not None else ""
            writer.writerow([
                row["baseline"],
                row["metric"],
                row["n_independent_runs"],
                f"{row['mean']:.3f}",
                sd_str,
                lo_str,
                hi_str,
                f"{min(vals):.3f}",
                f"{max(vals):.3f}",
                row["unit"],
                descriptions.get(row["baseline"], ""),
            ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("experiments/results/raw"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/results/summary/b2_b3_comparison.json"),
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=Path("experiments/results/summary/b2_b3_closed_loop_20261025.csv"),
    )
    args = parser.parse_args()
    files = list(args.raw_dir.glob("b[23]_closed_loop_*.csv")) + list(
        args.raw_dir.glob("b2_matched_detector_*.csv")
    )
    result = analyze(files)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_csv_summary(result, args.csv_output)
    print(
        f"Wrote {len(result['summaries'])} metric summaries to {args.output} and {args.csv_output}; "
        f"valid runs={len(result['runs'])}, exclusions={len(result['exclusions'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
