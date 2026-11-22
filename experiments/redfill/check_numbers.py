import csv
from pathlib import Path

root = Path("experiments/results/redfill_2026-11")

print("=== ALL SUBDIRS & COUNTS ===")
for p in sorted(root.iterdir()):
    if p.is_dir():
        print(f"{p.name}: {[c.name for c in sorted(p.iterdir())]}")

print("\n=== E9 percentages vs drafts ===")
print("Draft Table I: B2 det=99.5, rec=279.4; B2matched det=2116.8, rec=467.7; B3 det=2115.9, rec=537.9")
with (root / "E9/summary.csv").open() as f:
    for r in csv.DictReader(f):
        print(r)

print("\n=== E11 d20 filenames ===")
for f in sorted((root / "E11/raw").glob("redfill_e11_d20_*.csv")):
    print(f.name)

print("\n=== E12 percentage errors ===")
with (root / "E12/model_comparison.csv").open() as f:
    for r in csv.DictReader(f):
        if r["mode"] == "b2":
            meas, pred = float(r["lost_mean"]), float(r["pred_lost_ach"])
            err = (meas - pred) / pred * 100
            tgap_err = (float(r["tgap_meas_ms"]) - 41.0) / 41.0 * 100
            print(f"{r['pair']} r{r['target_rate_pps']} b2 lost: meas={meas:.3f} pred={pred:.3f} err={err:+.2f}% Tgap={r['tgap_meas_ms']} ({tgap_err:+.2f}%)")
        else:
            meas, pred = float(r["reord_mean"]), float(r["pred_reord_ach"])
            err = (meas - pred) / pred * 100
            dd_nom = float(r["delta_d_nominal_ms"])
            dd_err = (float(r["delta_d_meas_ms"]) - dd_nom) / dd_nom * 100
            print(f"{r['pair']} r{r['target_rate_pps']} b3 reord: meas={meas:.3f} pred={pred:.3f} err={err:+.2f}% dD={r['delta_d_meas_ms']}/{dd_nom} ({dd_err:+.2f}%)")

print("\n=== E13 summary & calibration & percentage errors ===")
cal_dir = root / "E13/calibration"
print("Calibration files:", [p.name for p in sorted(cal_dir.glob("*"))])
cal_csv = next(iter(sorted(cal_dir.glob("*.csv"))), None)
if cal_csv:
    print("Calibration CSV content:")
    print(cal_csv.read_text())
with (root / "E13/model_comparison.csv").open() as f:
    for r in csv.DictReader(f):
        meas = float(r["rate_mean"])
        pred = float(r["predicted_rate"])
        pct = f"{(meas - pred)/pred*100:+.2f}%" if pred > 0 else "N/A"
        print(f"{r['config']}: rate={meas:.6f} pred={pred:.6f} err={pct} qa={r['q_alpha_mean']} q1={r['q1_raw_mean']}")

print("\n=== E15 percentage errors ===")
with (root / "E15/model_comparison.csv").open() as f:
    for r in csv.DictReader(f):
        owd = float(r["fwd_owd_mean_ms"])
        pl = float(r["planned_owd_ms"])
        half = float(r["rtt_half_ms"])
        pct_pl = (owd - pl) / pl * 100
        pct_half = (half - owd) / owd * 100
        print(f"{r['route']} {r['condition']}: owd={owd:.3f} planned={pl:.1f} ({pct_pl:+.2f}%) rtt/2={half:.3f} vs_owd={pct_half:+.2f}%")
