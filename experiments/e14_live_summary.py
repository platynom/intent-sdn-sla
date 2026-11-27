"""Summarise E14b live contention runs (experiments/scenarios/e14_live_check.sh).

Reads every raw CSV under experiments/results/redfill_2026-11/E14_LIVE/raw/ for the
given tag and writes summary.csv (mean and 95% t interval per metric) next to it.

    python3.9 experiments/e14_live_summary.py --tag new
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "results" / "redfill_2026-11" / "E14_LIVE"
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
       9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="new")
    args = ap.parse_args()

    files = sorted((ROOT / "raw").glob(f"redfill_e14_live_{args.tag}_*.csv"))
    if not files:
        raise SystemExit(f"no raw runs for tag {args.tag!r} in {ROOT / 'raw'}")
    values: dict[str, list[float]] = defaultdict(list)
    units: dict[str, str] = {}
    for f in files:
        with f.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                values[row["metric"]].append(float(row["value"]))
                units[row["metric"]] = row["unit"]

    out = ROOT / f"summary_{args.tag}.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "n", "mean", "ci95_low", "ci95_high", "min", "max", "unit"])
        for metric in sorted(values):
            v = values[metric]
            n = len(v)
            mean = statistics.fmean(v)
            half = T95.get(n - 1, 1.96) * statistics.stdev(v) / math.sqrt(n) if n > 1 else 0.0
            w.writerow([metric, n, f"{mean:.4f}", f"{mean - half:.4f}", f"{mean + half:.4f}",
                        f"{min(v):.4f}", f"{max(v):.4f}", units[metric]])
            print(f"{metric:28s} n={n:2d} mean={mean:9.3f} [{mean - half:.3f}, {mean + half:.3f}] {units[metric]}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
