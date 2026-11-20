#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"

echo "=== GIT LOG ==="
git log --oneline -8

echo "=== GIT DIFF TRACKED FILES ==="
git diff --name-only

echo "=== PYTEST IN CONTAINER ==="
docker compose exec -T sdn pytest tests -q

echo "=== VERIFY SUMMARIES ==="
docker compose exec -T sdn python3.9 experiments/verify_summaries.py

echo "=== ARTIFACT MANIFEST VERIFY ==="
docker compose exec -T sdn python3.9 experiments/artifact_manifest.py verify

echo "=== SMOKE & FIGURE INVENTORY ==="
find experiments/results/redfill_2026-11 -maxdepth 3 \( -name "fig_*" -o -name "*smoke*" -o -path "*/excluded/*" \) | sort
for d in E9 E10 E11 E12 E13 E14 E15 E16; do
    cnt=$(find "experiments/results/redfill_2026-11/${d}/raw" -maxdepth 1 -name "redfill_*.csv" | wc -l)
    echo "${d}/raw count: ${cnt}"
done

echo "=== GIT LOG cf25af2..75f2d2e ==="
git log --oneline cf25af2..75f2d2e

echo "=== CHECK E4_PACKET_LOSS.SH ON 75f2d2e (LINES 75-185) ==="
git show 75f2d2e:experiments/scenarios/e4_packet_loss.sh | nl -ba | sed -n '75,185p'

echo "=== CHECK CURRENT E4_PACKET_LOSS.SH LINES 70-264 ==="
nl -ba experiments/scenarios/e4_packet_loss.sh | sed -n '70,210p'

echo "=== RECOMPUTE ALL REDFILL SUMMARIES ==="
for exp_id in E9 E10 E11 E12 E13 E14 E15 E16; do
    sed 's/\r$//' "experiments/redfill/redfill_analysis.py" \
        | docker compose exec -T sdn python3.9 - --exp "${exp_id}"
done

echo "=== INDEPENDENT VERIFICATION OF E9-E16 SUMMARIES ==="
docker compose exec -T sdn python3.9 - <<'PY'
import csv
import math
import re
from pathlib import Path
from experiments.summarize_metrics import compute_ci

root = Path("experiments/results/redfill_2026-11")

classifiers = {
    "E9": lambda p: (
        "B2" if p.name.startswith("redfill_e9_b2_")
        else "B2_matched_detector" if p.name.startswith("redfill_e9_b2matched_")
        else "B3" if p.name.startswith("redfill_e9_b3_")
        else "O3_unbound" if p.name.startswith("redfill_e9_o3_unbound_")
        else "O3_bound"
    ),
    "E10": lambda p: f"k={re.match(r'^redfill_e10_k(\d+)_dt([0-9p]+)_', p.name).group(1)}_dt={re.match(r'^redfill_e10_k(\d+)_dt([0-9p]+)_', p.name).group(2).replace('p','.')}",
    "E11": lambda p: f"dwell={re.match(r'^redfill_e11_d(\d+)_', p.name).group(1)}s",
    "E12": lambda p: f"pair{re.match(r'^redfill_e12_([ABC])_r(\d+)_(b2|b3)_', p.name).group(1)}_r{re.match(r'^redfill_e12_([ABC])_r(\d+)_(b2|b3)_', p.name).group(2)}_{re.match(r'^redfill_e12_([ABC])_r(\d+)_(b2|b3)_', p.name).group(3)}",
    "E13": lambda p: re.match(r'^redfill_e13_(naive|k1|k2|k3)_', p.name).group(1),
    "E14": lambda p: f"{re.match(r'^redfill_e14_(old|new)_N(\d+)_', p.name).group(1)}_N={int(re.match(r'^redfill_e14_(old|new)_N(\d+)_', p.name).group(2)):02d}",
    "E15": lambda p: f"{re.match(r'^redfill_e15_(north|middle|south)_(healthy|fault)_', p.name).group(1)}_{re.match(r'^redfill_e15_(north|middle|south)_(healthy|fault)_', p.name).group(2)}",
    "E16": lambda p: f"{re.match(r'^redfill_e16_(team16_7sw|geant2012)_k(\d+)_', p.name).group(1)}_k={int(re.match(r'^redfill_e16_(team16_7sw|geant2012)_k(\d+)_', p.name).group(2)):02d}",
}

checked = 0
for exp, cls in classifiers.items():
    raw_dir = root / exp / "raw"
    by_gm = {}
    for f in sorted(raw_dir.glob("redfill_*.csv")):
        g = cls(f)
        with f.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                by_gm.setdefault((g, row["metric"]), []).append(float(row["value"]))
    if exp == "E15":
        for (g, m), vals in by_gm.items():
            if m == "rtt_ms" and max(vals) > 1000.0:
                raise AssertionError(f"E15 {g} has rtt_ms > 1000")
    with (root / exp / "summary.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(by_gm), f"{exp} row count mismatch"
    for r in rows:
        vals = by_gm[(r["group"], r["metric"])]
        st = compute_ci(vals)
        assert int(r["n"]) == st["n_independent_runs"], (exp, r)
        assert math.isclose(float(r["mean"]), round(st["mean"], 3), abs_tol=1e-6), (exp, r, st["mean"])
        assert math.isclose(float(r["stdev"]), round(st["stdev"], 3), abs_tol=1e-6), (exp, r, st["stdev"])
        assert math.isclose(float(r["ci95_t_low"]), round(st["ci95_t_low"], 3), abs_tol=1e-6), (exp, r)
        assert math.isclose(float(r["ci95_t_high"]), round(st["ci95_t_high"], 3), abs_tol=1e-6), (exp, r)
        checked += 1

print(f"INDEPENDENT_VERIFICATION_OK: checked {checked} summary rows across E9..E16")
PY
