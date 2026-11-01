#!/usr/bin/env python3
"""Independently recompute raw-run statistics and verify published summaries.

This module intentionally imports no project summarizer or analysis helper.  It
reads only immutable raw CSVs, recomputes statistics, and compares the result to
every registered CSV/JSON summary plus the numeric claims published in the
README and experimental-results report.
"""

from __future__ import annotations

import csv
import itertools
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "experiments" / "results" / "raw"
SUMMARY_DIR = ROOT / "experiments" / "results" / "summary"

T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262,
    10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
    20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
    25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045,
    30: 2.042,
}


def _stats(values: Sequence[float]) -> dict:
    n = len(values)
    if not values:
        raise ValueError("cannot summarize an empty series")
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if n > 1 else None
    if sd is None:
        low = high = None
    else:
        critical = T95.get(n - 1, 1.96)
        half = critical * sd / math.sqrt(n)
        low, high = mean - half, mean + half
    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "low": low,
        "high": high,
        "min": min(values),
        "max": max(values),
    }


def _read_rows(path: Path) -> List[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    required = {"run_id", "timestamp", "metric", "value", "unit"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"{path}: invalid raw CSV schema")
    return rows


def _single_run_dataset(
    patterns: Iterable[str],
    classify: Callable[[str], Optional[str]],
) -> dict:
    observations: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    units: Dict[Tuple[str, str], str] = {}
    seen = set()
    for pattern in patterns:
        for path in sorted(RAW_DIR.glob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            group = classify(path.name)
            if group is None:
                continue
            rows = _read_rows(path)
            run_ids = {row["run_id"] for row in rows}
            if len(run_ids) != 1:
                raise ValueError(f"{path}: expected one run_id")
            metrics = set()
            for row in rows:
                metric = row["metric"]
                if metric in metrics:
                    raise ValueError(f"{path}: duplicate metric {metric}")
                metrics.add(metric)
                value = float(row["value"])
                if not math.isfinite(value):
                    raise ValueError(f"{path}: non-finite {metric}")
                key = (group, metric)
                observations[key].append(value)
                units[key] = row["unit"]
    return {
        "series": observations,
        "units": units,
        "files": sorted(path.name for path in seen),
    }


def _multi_run_dataset(path: Path, group: str) -> dict:
    per_run: Dict[Tuple[str, str], float] = {}
    units: Dict[Tuple[str, str], str] = {}
    for row in _read_rows(path):
        key = (row["run_id"], row["metric"])
        if key in per_run:
            raise ValueError(f"{path}: duplicate {key}")
        per_run[key] = float(row["value"])
        units[(group, row["metric"])] = row["unit"]
    observations: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for (_, metric), value in per_run.items():
        observations[(group, metric)].append(value)
    return {"series": observations, "units": units, "files": [path.name]}


def _dataset_specs() -> Dict[str, dict]:
    def prefix_classifier(mapping: Mapping[str, str]) -> Callable[[str], Optional[str]]:
        def classify(name: str) -> Optional[str]:
            return next((group for prefix, group in mapping.items() if name.startswith(prefix)), None)
        return classify

    specs = {
        "b0": _multi_run_dataset(RAW_DIR / "b0_baseline_20261025155102.csv", "B0"),
        "b1": _single_run_dataset(
            ["b1_open_loop_20261025*.csv"], lambda _: "B1"
        ),
        "closed_loop": _single_run_dataset(
            ["b2_closed_loop_*.csv", "b2_matched_detector_*.csv", "b3_closed_loop_*.csv"],
            prefix_classifier({
                "b2_matched_detector_": "B2_matched_detector",
                "b2_closed_loop_": "B2",
                "b3_closed_loop_": "B3",
            }),
        ),
        "e1": _single_run_dataset(
            ["e1_violation_duration_*.csv"],
            prefix_classifier({
                "e1_violation_duration_b1_": "B1",
                "e1_violation_duration_b3_": "B3",
            }),
        ),
        "e4": _single_run_dataset(
            ["e4_b[23]_reconfig_*.csv"],
            prefix_classifier({"e4_b2_": "B2", "e4_b3_": "B3"}),
        ),
        "o3": _single_run_dataset(
            ["o3_queue_*.csv"],
            prefix_classifier({"o3_queue_bound_": "bound", "o3_queue_unbound_": "unbound"}),
        ),
        "e5": _single_run_dataset(
            ["e5_*.csv"],
            prefix_classifier({
                "e5_all_relaxed_": "all_relaxed",
                "e5_selective_": "selective",
                "e5_all_strict_": "all_strict",
            }),
        ),
        "e6": _single_run_dataset(
            ["e6_oscillation_*.csv"],
            prefix_classifier({"e6_oscillation_b2_": "B2", "e6_oscillation_b3_": "B3"}),
        ),
        "e7": _single_run_dataset(
            ["e7_admission_k*.csv"],
            lambda name: (f"k={int(name.split('_')[2][1:]):02d}" if name.startswith("e7_admission_k") else None),
        ),
        "e8": _single_run_dataset(
            ["e8_overhead_*.csv"],
            prefix_classifier({"e8_overhead_b1_": "B1", "e8_overhead_b3_": "B3"}),
        ),
        "e8v2": _single_run_dataset(
            ["e8v2_overhead_*.csv"],
            prefix_classifier({"e8v2_overhead_b1_": "B1", "e8v2_overhead_b3_": "B3"}),
        ),
        "b3_current": _single_run_dataset(
            ["b3_current_closed_loop_*.csv"], lambda _: "B3-current"
        ),
        "e4_current": _single_run_dataset(
            ["e4current_b[23]_reconfig_*.csv"],
            prefix_classifier({"e4current_b2_": "B2", "e4current_b3_": "B3"}),
        ),
        "o3_current": _single_run_dataset(
            ["o3current_queue_*.csv"],
            prefix_classifier({
                "o3current_queue_bound_": "bound",
                "o3current_queue_unbound_": "unbound",
            }),
        ),
    }
    return specs


SUMMARY_FILES = {
    "b0_baseline_summary_20261025.csv": "b0",
    "evaluation_20261025161834.csv": "b0",
    "b1_open_loop_20261025.csv": "b1",
    "b2_b3_closed_loop_20261025.csv": "closed_loop",
    "b2_b3_comparison.json": "closed_loop",
    "e1_violation_duration_summary.csv": "e1",
    "e1_violation_duration_summary.json": "e1",
    "e4_packet_loss_summary.csv": "e4",
    "e4_packet_loss_summary.json": "e4",
    "o3_queue_binding_summary.csv": "o3",
    "o3_queue_binding_summary.json": "o3",
    "e5_flow_table_summary.csv": "e5",
    "e5_flow_table_summary.json": "e5",
    "e6_oscillation_summary.csv": "e6",
    "e6_oscillation_summary.json": "e6",
    "e7_admission_scaling_summary.csv": "e7",
    "e7_admission_scaling_summary.json": "e7",
    "e8_control_overhead_summary.csv": "e8",
    "e8_control_overhead_summary.json": "e8",
    "e8v2_control_overhead_summary.csv": "e8v2",
    "e8v2_control_overhead_summary.json": "e8v2",
    "b3_current_closed_loop_summary.csv": "b3_current",
    "b3_current_closed_loop_summary.json": "b3_current",
    "e4_current_packet_loss_summary.csv": "e4_current",
    "e4_current_packet_loss_summary.json": "e4_current",
    "o3_current_queue_binding_summary.csv": "o3_current",
    "o3_current_queue_binding_summary.json": "o3_current",
}


def _numeric_close(actual_s: str, expected: Optional[float]) -> bool:
    if expected is None:
        return actual_s.strip() == ""
    actual = float(actual_s)
    decimals = len(actual_s.split(".", 1)[1]) if "." in actual_s else 0
    tolerance = 0.5 * (10 ** (-decimals)) + 1e-12
    return abs(actual - expected) <= tolerance


def _compare_summary_csv(path: Path, dataset: dict, errors: List[str]) -> None:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        group = row.get("group") or row.get("baseline") or "B1"
        metric = row["metric"]
        key = (group, metric)
        values = dataset["series"].get(key)
        if not values:
            errors.append(f"{path.name}: no raw series for {key}")
            continue
        expected = _stats(values)
        fields = {
            "n": (row.get("n") or row.get("runs"), float(expected["n"])),
            "mean": (row.get("mean"), expected["mean"]),
            "sd": (row.get("stdev") or row.get("sample_stddev"), expected["sd"]),
            "low": (row.get("ci95_t_low") or row.get("ci95_low"), expected["low"]),
            "high": (row.get("ci95_t_high") or row.get("ci95_high"), expected["high"]),
        }
        for label, (actual_s, expected_value) in fields.items():
            if actual_s is None or not _numeric_close(actual_s, expected_value):
                errors.append(
                    f"{path.name} {key} {label}: got {actual_s!r}, expected {expected_value}"
                )


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d, h = 1.0, 1.0 - qab * x / qap, 1.0
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        if abs(d) < 1e-300:
            d = 1e-300
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        c = 1.0 + aa / c
        if abs(d) < 1e-300:
            d = 1e-300
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-14:
            break
    return h


def _regularized_beta(x: float, a: float, b: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _beta_continued_fraction(a, b, x) / a
    return 1.0 - bt * _beta_continued_fraction(b, a, 1.0 - x) / b


def _independent_test(xs: Sequence[float], ys: Sequence[float]) -> dict:
    n1, n2 = len(xs), len(ys)
    m1, m2 = statistics.mean(xs), statistics.mean(ys)
    v1, v2 = statistics.variance(xs), statistics.variance(ys)
    if v1 == 0.0 or v2 == 0.0:
        pooled = tuple(xs) + tuple(ys)
        observed = abs(m1 - m2)
        total_sum = sum(pooled)
        extreme = 0
        for selected in itertools.combinations(range(n1 + n2), n1):
            selected_sum = sum(pooled[index] for index in selected)
            diff = abs(selected_sum / n1 - (total_sum - selected_sum) / n2)
            if diff + 1e-12 >= observed:
                extreme += 1
        total = math.comb(n1 + n2, n1)
        return {
            "test_method": "exact two-sided permutation",
            "mean_diff": m1 - m2,
            "p_value_two_sided": extreme / total,
            "permutation_extreme": extreme,
            "permutation_total": total,
        }
    se2 = v1 / n1 + v2 / n2
    t_stat = (m1 - m2) / math.sqrt(se2)
    denom = ((v1 / n1) ** 2) / (n1 - 1) + ((v2 / n2) ** 2) / (n2 - 1)
    df = (se2 ** 2) / denom
    x = df / (df + t_stat * t_stat)
    return {
        "test_method": "Welch two-sample t",
        "mean_diff": m1 - m2,
        "t_statistic": t_stat,
        "degrees_of_freedom": df,
        "p_value_two_sided": _regularized_beta(x, 0.5 * df, 0.5),
    }


def _compare_summary_json(path: Path, dataset: dict, errors: List[str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for row in payload.get("summaries", []):
        group = row.get("group") or row.get("baseline")
        key = (group, row["metric"])
        values = dataset["series"].get(key)
        if not values:
            errors.append(f"{path.name}: no raw series for {key}")
            continue
        expected = _stats(values)
        mapping = {
            "n_independent_runs": "n",
            "mean": "mean",
            "sample_stddev": "sd",
            "ci95_t_low": "low",
            "ci95_t_high": "high",
            "min": "min",
            "max": "max",
        }
        for actual_field, expected_field in mapping.items():
            if actual_field not in row:
                continue
            actual = row.get(actual_field)
            wanted = expected[expected_field]
            if actual is None and wanted is None:
                continue
            if actual is None or wanted is None or not math.isclose(float(actual), float(wanted), rel_tol=1e-9, abs_tol=1e-9):
                errors.append(
                    f"{path.name} {key} {actual_field}: got {actual!r}, expected {wanted!r}"
                )
    tests = payload.get("statistical_tests", [])
    if "welch_tests" in payload:
        errors.append(f"{path.name}: stale misleading 'welch_tests' key")
    for row in tests:
        metric = row["metric"]
        xs = dataset["series"].get((row["group_a"], metric), [])
        ys = dataset["series"].get((row["group_b"], metric), [])
        if len(xs) < 2 or len(ys) < 2:
            errors.append(f"{path.name}: missing raw groups for statistical test {row}")
            continue
        expected = _independent_test(xs, ys)
        for field in (
            "mean_diff", "p_value_two_sided", "t_statistic",
            "degrees_of_freedom", "permutation_extreme", "permutation_total",
        ):
            if field not in expected:
                continue
            actual = row.get(field)
            wanted = expected[field]
            if actual is None or not math.isclose(float(actual), float(wanted), rel_tol=1e-8, abs_tol=1e-10):
                errors.append(
                    f"{path.name} test {metric} {field}: got {actual!r}, expected {wanted!r}"
                )
        if row.get("test_method") != expected["test_method"]:
            errors.append(
                f"{path.name} test {metric}: got method {row.get('test_method')!r}, "
                f"expected {expected['test_method']!r}"
            )


def _verify_document_claims(datasets: Mapping[str, dict], errors: List[str]) -> None:
    """Check every registered three-decimal result claim in both public docs."""
    results_text = (ROOT / "docs" / "EXPERIMENTAL_RESULTS.md").read_text(encoding="utf-8")
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    claims = {
        "B0 throughput mean": ("b0", "B0", "throughput", "mean"),
        "B0 throughput SD": ("b0", "B0", "throughput", "sd"),
        "B0 throughput CI low": ("b0", "B0", "throughput", "low"),
        "B0 throughput CI high": ("b0", "B0", "throughput", "high"),
    }
    for label, (dataset_name, group, metric, field) in claims.items():
        value = _stats(datasets[dataset_name]["series"][(group, metric)])[field]
        token = f"{value:.3f}"
        if token not in results_text:
            errors.append(f"docs/EXPERIMENTAL_RESULTS.md missing {label}={token}")

    # README contains a compact headline subset.  Each listed result must match
    # an independently recomputed raw-data mean rounded to three decimals.
    readme_claims = [
        ("o3", "bound", "intent_throughput_mbps"),
        ("o3", "unbound", "intent_throughput_mbps"),
        ("e1", "B1", "sla_violation_duration_s"),
        ("e1", "B3", "sla_violation_duration_s"),
        ("b3_current", "B3-current", "detection_latency"),
        ("b3_current", "B3-current", "recovery_latency"),
        ("e4_current", "B2", "packets_lost"),
        ("e4_current", "B3", "packets_lost"),
        ("e5", "all_relaxed", "peak_rules_max_switch"),
        ("e5", "selective", "peak_rules_max_switch"),
        ("e5", "all_strict", "peak_rules_max_switch"),
        ("e6", "B2", "reroute_count_10min"),
        ("e6", "B3", "reroute_count_10min"),
        ("e7", "k=01", "admission_decision_latency_ms"),
        ("e7", "k=02", "admission_decision_latency_ms"),
        ("e7", "k=04", "admission_decision_latency_ms"),
        ("e7", "k=08", "admission_decision_latency_ms"),
        ("e7", "k=16", "admission_decision_latency_ms"),
    ]
    for dataset_name, group, metric in readme_claims:
        series = datasets[dataset_name]["series"].get((group, metric))
        if not series:
            errors.append(f"README claim has no raw series: {(dataset_name, group, metric)}")
            continue
        token = f"{statistics.mean(series):.3f}"
        if token not in readme_text:
            errors.append(f"README.md missing raw-derived mean {dataset_name}/{group}/{metric}={token}")


def verify() -> List[str]:
    datasets = _dataset_specs()
    errors: List[str] = []
    actual_summary_files = {
        path.name for path in SUMMARY_DIR.iterdir()
        if path.suffix in {".csv", ".json"}
    }
    registered_existing = {name for name in SUMMARY_FILES if (SUMMARY_DIR / name).exists()}
    for name in sorted(actual_summary_files - registered_existing):
        errors.append(f"unregistered summary file: {name}")
    for name in sorted(registered_existing):
        path = SUMMARY_DIR / name
        dataset = datasets[SUMMARY_FILES[name]]
        if path.suffix == ".csv":
            _compare_summary_csv(path, dataset, errors)
        else:
            _compare_summary_json(path, dataset, errors)
    _verify_document_claims(datasets, errors)
    return errors


def main() -> int:
    errors = verify()
    if errors:
        print("summary verification FAILED", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("summary verification passed: raw CSVs, summaries, and public result claims agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
