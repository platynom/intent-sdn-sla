#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"

echo "=== CHECK E4_PACKET_LOSS.SH ON 75f2d2e (LINES 79-83 AND 112-182) ==="
git show 75f2d2e:experiments/scenarios/e4_packet_loss.sh | nl -ba | sed -n '78,84p;112,182p'

echo "=== INDEPENDENT VERIFICATION OF E9-E16 SUMMARIES ==="
docker compose exec -T sdn python3.9 - <<'PY'
import csv
import math
import re
from pathlib import Path
from experiments.summarize_metrics import compute_ci

root = Path("experiments/results/redfill_2026-11")

def cls_e9(p):
    if p.name.startswith("redfill_e9_b2_"): return "B2"
    if p.name.startswith("redfill_e9_b2matched_"): return "B2_matched_detector"
    if p.name.startswith("redfill_e9_b3_"): return "B3"
    if p.name.startswith("redfill_e9_o3_unbound_"): return "O3_unbound"
    return "O3_bound"

def cls_e10(p):
    m = re.match(r"^redfill_e10_k(\d+)_dt([0-9p]+)_", p.name)
    dt = m.group(2).replace("p", ".")
    return f"k={m.group(1)}_dt={dt}"

def cls_e11(p):
    m = re.match(r"^redfill_e11_d(\d+)_", p.name)
    return f"dwell={m.group(1)}s"

def cls_e12(p):
    m = re.match(r"^redfill_e12_([ABC])_r(\d+)_(b2|b3)_", p.name)
    return f"pair{m.group(1)}_r{m.group(2)}_{m.group(3)}"

def cls_e13(p):
    m = re.match(r"^redfill_e13_(naive|k1|k2|k3)_", p.name)
    return m.group(1)

def cls_e14(p):
    m = re.match(r"^redfill_e14_(old|new)_N(\d+)_", p.name)
    return f"{m.group(1)}_N={int(m.group(2)):02d}"

def cls_e15(p):
    m = re.match(r"^redfill_e15_(north|middle|south)_(healthy|fault)_", p.name)
    return f"{m.group(1)}_{m.group(2)}"

def cls_e16(p):
    m = re.match(r"^redfill_e16_(team16_7sw|geant2012)_k(\d+)_", p.name)
    return f"{m.group(1)}_k={int(m.group(2)):02d}"

classifiers = {
    "E9": cls_e9, "E10": cls_e10, "E11": cls_e11, "E12": cls_e12,
    "E13": cls_e13, "E14": cls_e14, "E15": cls_e15, "E16": cls_e16,
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
        assert math.isclose(float(r["stdev"]), round(st["sample_stddev"], 3), abs_tol=1e-6), (exp, r, st["sample_stddev"])
        assert math.isclose(float(r["ci95_t_low"]), round(st["ci95_t_low"], 3), abs_tol=1e-6), (exp, r)
        assert math.isclose(float(r["ci95_t_high"]), round(st["ci95_t_high"], 3), abs_tol=1e-6), (exp, r)
        checked += 1

print(f"INDEPENDENT_VERIFICATION_OK: checked {checked} summary rows across E9..E16")
PY
