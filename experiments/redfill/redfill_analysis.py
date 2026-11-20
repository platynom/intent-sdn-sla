#!/usr/bin/env python3
"""Summarize and plot red-items experiments (E9-E16) using repo statistical primitives."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path.cwd() if (Path.cwd() / "experiments").exists() else Path("/app")
sys.path.insert(0, str(REPO))

from experiments.analyze_closed_loop import read_run, welch_t_test
from experiments.summarize_metrics import compute_ci, summarize_group, write_summary_files


REDF_ROOT = REPO / "experiments" / "results" / "redfill_2026-11"


def summarize_e9() -> None:
    exp_dir = REDF_ROOT / "E9"
    raw_dir = exp_dir / "raw"
    files = sorted(raw_dir.glob("redfill_e9_*.csv"))

    def classify(p: Path) -> Optional[str]:
        n = p.name
        if n.startswith("redfill_e9_b2matched_"):
            return "B2_matched_detector"
        if n.startswith("redfill_e9_b2_"):
            return "B2"
        if n.startswith("redfill_e9_b3_"):
            return "B3"
        if n.startswith("redfill_e9_o3_unbound_"):
            return "O3_unbound"
        if n.startswith("redfill_e9_o3_bound_"):
            return "O3_bound"
        return None

    res = summarize_group(files, classify)
    tests = []
    for metric in ("detection_latency", "recovery_latency"):
        for g1, g2 in (("B2", "B3"), ("B2_matched_detector", "B3"), ("B2", "B2_matched_detector")):
            xs = res["values_by_key"].get((g1, metric), [])
            ys = res["values_by_key"].get((g2, metric), [])
            wt = welch_t_test(xs, ys)
            if wt is not None:
                tests.append({"metric": metric, "group_a": g1, "group_b": g2, "n_a": len(xs), "n_b": len(ys), **wt})
    for metric in ("intent_throughput_mbps", "intent_loss_pct", "cross_traffic_throughput_mbps", "cross_traffic_loss_pct"):
        xs = res["values_by_key"].get(("O3_bound", metric), [])
        ys = res["values_by_key"].get(("O3_unbound", metric), [])
        wt = welch_t_test(xs, ys)
        if wt is not None:
            tests.append({"metric": metric, "group_a": "O3_bound", "group_b": "O3_unbound", "n_a": len(xs), "n_b": len(ys), **wt})

    write_summary_files(
        res["summaries"],
        tests,
        res["runs"],
        exp_dir / "summary.json",
        exp_dir / "summary.csv",
        description="E9: Same-build rerun of Table I (B2, B2-matched, B3) and O3 (unbound, bound) on commit 75f2d2e",
    )
    if tests:
        with (exp_dir / "welch_tests.csv").open("w", newline="", encoding="utf-8") as f:
            keys = ["metric", "group_a", "group_b", "n_a", "n_b", "test_method", "mean_diff", "t_statistic", "degrees_of_freedom", "p_value_two_sided"]
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for t in tests:
                w.writerow({k: t.get(k, "") for k in keys})
    print(f"E9 summarized {len(files)} raw files -> {exp_dir / 'summary.csv'}")


def summarize_e10() -> None:
    import re
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    exp_dir = REDF_ROOT / "E10"
    raw_dir = exp_dir / "raw"
    files = sorted(raw_dir.glob("redfill_e10_*.csv"))
    pat = re.compile(r"^redfill_e10_k(\d+)_dt([0-9p]+)_")

    def classify(p: Path) -> Optional[str]:
        m = pat.match(p.name)
        if not m:
            return None
        return f"k={m.group(1)}_dt={m.group(2).replace('p', '.')}"

    res = summarize_group(files, classify)
    write_summary_files(
        res["summaries"],
        [],
        res["runs"],
        exp_dir / "summary.json",
        exp_dir / "summary.csv",
        description="E10: Detection delay sweep K in {1..5}, dt in {0.25, 0.5, 1.0} s",
    )

    # Fit t0 by least squares across all individual runs: t0 = mean(Tdet_i - (k_i - 1)*dt_i)
    residuals_ms = []
    all_points = []
    extra_rows = []
    per_cell: Dict[Tuple[int, float], List[float]] = defaultdict(list)
    for r in res["runs"]:
        m = pat.match(r["file"])
        if not m:
            continue
        k = int(m.group(1))
        dt = float(m.group(2).replace("p", "."))
        det_ms = r["values"]["detection_latency"]
        per_cell[(k, dt)].append(det_ms)
        t0_i = det_ms - (k - 1) * dt * 1000.0
        residuals_ms.append(t0_i)
        all_points.append(((k - 1) * dt * 1000.0, det_ms))

    t0_hat_ms = statistics.mean(residuals_ms)
    t0_sd_ms = statistics.stdev(residuals_ms)
    t0_se_ms = t0_sd_ms / math.sqrt(len(residuals_ms))
    # Compute R^2 for model Tdet = (k-1)*dt + t0_hat (and with fixed t0=100ms)
    y_mean = statistics.mean(y for _, y in all_points)
    ss_tot = sum((y - y_mean) ** 2 for _, y in all_points)
    ss_res_fit = sum((y - (x + t0_hat_ms)) ** 2 for x, y in all_points)
    ss_res_100 = sum((y - (x + 100.0)) ** 2 for x, y in all_points)
    r2_fit = 1.0 - ss_res_fit / ss_tot if ss_tot > 0 else 1.0
    r2_100 = 1.0 - ss_res_100 / ss_tot if ss_tot > 0 else 1.0

    for (k, dt), vals in sorted(per_cell.items(), key=lambda x: (x[0][1], x[0][0])):
        st = compute_ci(vals)
        pred_ms = ((k - 1) * dt + 0.1) * 1000.0
        pred_fit_ms = (k - 1) * dt * 1000.0 + t0_hat_ms
        err_ms = st["mean"] - pred_ms
        pct_err = 100.0 * err_ms / pred_ms
        extra_rows.append({
            "k": k,
            "dt_s": dt,
            "n": st["n_independent_runs"],
            "mean_ms": f"{st['mean']:.3f}",
            "sd_ms": f"{st['sample_stddev']:.3f}",
            "ci95_low_ms": f"{st['ci95_t_low']:.3f}",
            "ci95_high_ms": f"{st['ci95_t_high']:.3f}",
            "pred_t0_100ms": f"{pred_ms:.3f}",
            "abs_err_ms": f"{err_ms:+.3f}",
            "pct_err": f"{pct_err:+.2f}",
            "pred_fit_ms": f"{pred_fit_ms:.3f}",
        })

    with (exp_dir / "model_comparison.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(extra_rows[0].keys()))
        w.writeheader()
        w.writerows(extra_rows)

    fit_info = {
        "n_total_runs": len(residuals_ms),
        "t0_hat_ms": t0_hat_ms,
        "t0_hat_s": t0_hat_ms / 1000.0,
        "t0_sd_ms": t0_sd_ms,
        "t0_se_ms": t0_se_ms,
        "r2_fitted_t0": r2_fit,
        "r2_fixed_100ms": r2_100,
    }
    (exp_dir / "t0_fit.json").write_text(json.dumps(fit_info, indent=2) + "\n", encoding="utf-8")

    # Plot measured vs predicted
    fig, ax = plt.subplots(figsize=(7.0, 4.4), constrained_layout=True)
    palette = {0.25: "#147d79", 0.5: "#3b7ea1", 1.0: "#c56a27"}
    ks = [1, 2, 3, 4, 5]
    for dt in (0.25, 0.5, 1.0):
        c = palette[dt]
        preds = [((k - 1) * dt + 0.1) for k in ks]
        means = [statistics.mean(per_cell[(k, dt)]) / 1000.0 for k in ks]
        lo = [means[i] - compute_ci(per_cell[(ks[i], dt)])["ci95_t_low"] / 1000.0 for i in range(len(ks))]
        hi = [compute_ci(per_cell[(ks[i], dt)])["ci95_t_high"] / 1000.0 - means[i] for i in range(len(ks))]
        ax.plot(ks, preds, "--", color=c, linewidth=1.4, label=f"Predicted (dt={dt:g} s, t0=0.1 s)")
        ax.errorbar(ks, means, yerr=[lo, hi], fmt="o", color=c, ecolor="#243746", capsize=4, markersize=5.5,
                    label=f"Measured (dt={dt:g} s)")
    ax.set_xticks(ks, [str(k) for k in ks])
    ax.set_xlabel("Confirmation count k")
    ax.set_ylabel("Detection delay T_det (s)")
    ax.set_title(f"E10: Detection Delay Sweep vs. Eq. (9) (n=10/cell, t0_fit={t0_hat_ms/1000:.3f} s)")
    ax.legend(frameon=False, fontsize=8.5, ncol=2, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    for ext in ("png", "pdf"):
        fig.savefig(exp_dir / f"fig_e10_detection_sweep.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"E10 summarized {len(files)} raw files; t0_hat={t0_hat_ms:.2f} ms")


def summarize_e11() -> None:
    import re
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    exp_dir = REDF_ROOT / "E11"
    raw_dir = exp_dir / "raw"
    files = sorted(raw_dir.glob("redfill_e11_*.csv"))
    pat = re.compile(r"^redfill_e11_d(\d+)_")

    def classify(p: Path) -> Optional[str]:
        m = pat.match(p.name)
        return f"dwell={m.group(1)}s" if m else None

    res = summarize_group(files, classify)
    write_summary_files(
        res["summaries"],
        [],
        res["runs"],
        exp_dir / "summary.json",
        exp_dir / "summary.csv",
        description="E11: Dwell sweep delta in {0, 5, 10, 20, 30} s over 600 s alternating fault",
    )

    preds_raw = {0: 600.0 / 2.1, 5: 600.0 / 7.1, 10: 600.0 / 12.1, 20: 600.0 / 22.1, 30: 600.0 / 32.1}
    strict_bounds_nf90 = {0: 90, 5: 90, 10: 61, 20: 31, 30: 21}
    strict_bounds_nf60 = {0: 60, 5: 60, 10: 60, 20: 31, 30: 21}

    comp = []
    dwells = [0, 5, 10, 20, 30]
    means, err_lo, err_hi = [], [], []
    for d in dwells:
        grp = f"dwell={d}s"
        rvals = res["values_by_key"][(grp, "reroute_count_10min")]
        svals = res["values_by_key"][(grp, "dwell_suppressions")]
        vvals = res["values_by_key"][(grp, "violations_emitted")]
        rst = compute_ci(rvals)
        sst = compute_ci(svals)
        vst = compute_ci(vvals)
        pred_90 = min(90.0, preds_raw[d])
        pred_60 = min(60.0, preds_raw[d])
        pct_90 = 100.0 * (rst["mean"] - pred_90) / pred_90
        pct_60 = 100.0 * (rst["mean"] - pred_60) / pred_60
        sb_unbounded = (600 // d + 1) if d > 0 else 90
        sb_90 = strict_bounds_nf90[d]
        sb_60 = strict_bounds_nf60[d]
        held_90 = all(v <= sb_90 + 1e-9 for v in rvals)
        held_60 = all(v <= sb_60 + 1e-9 for v in rvals)
        comp.append({
            "dwell_s": d,
            "n": rst["n_independent_runs"],
            "reroutes_mean": f"{rst['mean']:.3f}",
            "reroutes_sd": f"{rst['sample_stddev']:.3f}",
            "reroutes_ci95_low": f"{rst['ci95_t_low']:.3f}",
            "reroutes_ci95_high": f"{rst['ci95_t_high']:.3f}",
            "reroutes_max": f"{rst['max']:.3f}",
            "violations_mean": f"{vst['mean']:.3f}",
            "suppressions_mean": f"{sst['mean']:.3f}",
            "eq10_pred_nf90": f"{pred_90:.3f}",
            "pct_error_nf90": f"{pct_90:+.2f}",
            "eq10_pred_nf60": f"{pred_60:.3f}",
            "pct_error_nf60": f"{pct_60:+.2f}",
            "strict_bound_unbounded": sb_unbounded,
            "strict_bound_nf90": sb_90,
            "strict_bound_held_nf90": str(held_90),
            "strict_bound_nf60": sb_60,
            "strict_bound_held_nf60": str(held_60),
        })
        means.append(rst["mean"])
        err_lo.append(rst["mean"] - rst["ci95_t_low"])
        err_hi.append(rst["ci95_t_high"] - rst["mean"])

    with (exp_dir / "model_comparison.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(comp[0].keys()))
        w.writeheader()
        w.writerows(comp)

    fig, ax = plt.subplots(figsize=(7.0, 4.4), constrained_layout=True)
    xs_grid = [0, 5, 10, 15, 20, 25, 30]
    eq10_90 = [min(90.0, 600.0 / (d + 2.1)) for d in xs_grid]
    eq10_60 = [min(60.0, 600.0 / (d + 2.1)) for d in xs_grid]
    sb_curve = [min(90, (600 // d + 1) if d > 0 else 90) for d in xs_grid]
    ax.plot(xs_grid, eq10_90, ":", color="#3b7ea1", linewidth=1.6, label="Eq. (10) Nf=90 (paper)")
    ax.plot(xs_grid, eq10_60, "-", color="#147d79", linewidth=1.9, label="Eq. (10) Nf=60 (effective B3)")
    ax.plot(xs_grid, sb_curve, "--", color="#c56a27", linewidth=1.4, label="Strict bound: min{90, floor(T/delta)+1}")
    ax.errorbar(dwells, means, yerr=[err_lo, err_hi], fmt="o", color="#243746", ecolor="#243746",
                capsize=5, markersize=6, label="Measured B3 (n=10, 95% CI)")
    ax.set_xlabel("Dwell time delta (s)")
    ax.set_ylabel("Reroutes per 10 min")
    ax.set_title("E11: Dwell Time Sweep vs. Eq. (10) (S6 alternating fault, T=600 s)")
    ax.set_ylim(0, 102)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    for ext in ("png", "pdf"):
        fig.savefig(exp_dir / f"fig_e11_dwell_sweep.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"E11 summarized {len(files)} raw files")


def summarize_e12() -> None:
    import re
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    exp_dir = REDF_ROOT / "E12"
    raw_dir = exp_dir / "raw"
    files = sorted(raw_dir.glob("redfill_e12_*.csv"))
    pat = re.compile(r"^redfill_e12_([ABC])_r(\d+)_(b[23])_reconfig_")

    def classify(p: Path) -> Optional[str]:
        m = pat.match(p.name)
        return f"pair{m.group(1)}_r{m.group(2)}_{m.group(3)}" if m else None

    res = summarize_group(files, classify)
    write_summary_files(
        res["summaries"],
        [],
        res["runs"],
        exp_dir / "summary.json",
        exp_dir / "summary.csv",
        description="E12: Rate (250, 1000, 4000 pkt/s) x path-pair (A, B, C) x mode (b2, b3) sweep",
    )

    delta_d_map = {"A": 29.0, "B": 20.0, "C": 26.0}
    comp = []
    cells = defaultdict(list)
    for r in res["runs"]:
        m = pat.match(r["file"])
        if not m:
            continue
        pair, rate_target, mode = m.group(1), int(m.group(2)), m.group(3)
        v = r["values"]
        ach_rate = v["packets_sent"] / v["window_duration_s"]
        cells[(pair, rate_target, mode)].append({
            "ach_rate": ach_rate,
            "lost": v["packets_lost"],
            "reord": v["packets_reordered"],
            "tgap_ms": (v["packets_lost"] / ach_rate) * 1000.0 if ach_rate > 0 else 0.0,
            "dd_ms": (v["packets_reordered"] / ach_rate) * 1000.0 if ach_rate > 0 else 0.0,
        })

    for (pair, rate_target, mode), items in sorted(cells.items()):
        ach_st = compute_ci([x["ach_rate"] for x in items])
        lost_st = compute_ci([x["lost"] for x in items])
        reord_st = compute_ci([x["reord"] for x in items])
        tgap_st = compute_ci([x["tgap_ms"] for x in items])
        dd_st = compute_ci([x["dd_ms"] for x in items])
        ach_mean = ach_st["mean"]
        below_90 = ach_mean < 0.90 * rate_target
        pred_lost = ach_mean * 0.041 if mode == "b2" else 0.0
        pred_reord = 0.0 if mode == "b2" else ach_mean * (delta_d_map[pair] / 1000.0)
        comp.append({
            "pair": pair,
            "target_rate_pps": rate_target,
            "mode": mode,
            "n": lost_st["n_independent_runs"],
            "ach_rate_mean_pps": f"{ach_mean:.2f}",
            "ach_ratio_pct": f"{100.0 * ach_mean / rate_target:.2f}",
            "below_90pct_target": str(below_90),
            "lost_mean": f"{lost_st['mean']:.3f}",
            "lost_ci95": f"[{lost_st['ci95_t_low']:.3f}, {lost_st['ci95_t_high']:.3f}]",
            "pred_lost_ach": f"{pred_lost:.3f}",
            "tgap_meas_ms": f"{tgap_st['mean']:.3f}",
            "reord_mean": f"{reord_st['mean']:.3f}",
            "reord_ci95": f"[{reord_st['ci95_t_low']:.3f}, {reord_st['ci95_t_high']:.3f}]",
            "pred_reord_ach": f"{pred_reord:.3f}",
            "delta_d_meas_ms": f"{dd_st['mean']:.3f}",
            "delta_d_nominal_ms": f"{delta_d_map[pair]:.1f}",
        })

    with (exp_dir / "model_comparison.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(comp[0].keys()))
        w.writeheader()
        w.writerows(comp)

    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.2), constrained_layout=True)
    pair_titles = {
        "A": "Pair A: North -> Middle (dD=29 ms)",
        "B": "Pair B: North -> South (dD=20 ms)",
        "C": "Pair C: Middle -> South (dD=26 ms)",
    }
    for ax, pair in zip(axes, ("A", "B", "C")):
        # Achieved rate points
        b2_x = [compute_ci([x["ach_rate"] for x in cells[(pair, r, "b2")]])["mean"] for r in (250, 1000, 4000)]
        b2_y = [compute_ci([x["lost"] for x in cells[(pair, r, "b2")]])["mean"] for r in (250, 1000, 4000)]
        b3_x = [compute_ci([x["ach_rate"] for x in cells[(pair, r, "b3")]])["mean"] for r in (250, 1000, 4000)]
        b3_l = [compute_ci([x["lost"] for x in cells[(pair, r, "b3")]])["mean"] for r in (250, 1000, 4000)]
        b3_r = [compute_ci([x["reord"] for x in cells[(pair, r, "b3")]])["mean"] for r in (250, 1000, 4000)]

        max_x = max(b2_x + b3_x + [1000]) * 1.05
        xs_line = [0.0, max_x]
        ax.plot(xs_line, [x * 0.041 for x in xs_line], "--", color="#c56a27", label="Model loss: 0.041*lambda")
        ax.plot(xs_line, [x * delta_d_map[pair] / 1000.0 for x in xs_line], "-", color="#147d79",
                label=f"Model reord: {delta_d_map[pair]/1000:.3f}*lambda")
        ax.scatter(b2_x, b2_y, color="#c56a27", marker="s", s=45, label="Relaxed loss (B2)", zorder=4)
        ax.scatter(b3_x, b3_r, color="#147d79", marker="o", s=45, label="Strict reordered (B3)", zorder=4)
        ax.scatter(b3_x, b3_l, color="#243746", marker="^", s=40, label="Strict loss (B3)", zorder=4)
        ax.set_title(pair_titles[pair], fontsize=10)
        ax.set_xlabel("Achieved rate lambda (pkt/s)")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Packets per transition")
    axes[0].legend(frameon=False, fontsize=7.5, loc="upper left")
    fig.suptitle("E12: Transition Loss and Reordering vs. Achieved Packet Rate (n=10/cell)", fontsize=11.5)
    for ext in ("png", "pdf"):
        fig.savefig(exp_dir / f"fig_e12_rate_pair_sweep.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"E12 summarized {len(files)} raw files")


def summarize_e13() -> None:
    import re
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    exp_dir = REDF_ROOT / "E13"
    raw_dir = exp_dir / "raw"
    files = sorted(raw_dir.glob("redfill_e13_*.csv"))
    pat = re.compile(r"^redfill_e13_(naive|k1|k2|k3)_j(\d+)_")

    def classify(p: Path) -> Optional[str]:
        m = pat.match(p.name)
        return m.group(1) if m else None

    res = summarize_group(files, classify)
    write_summary_files(
        res["summaries"],
        [],
        res["runs"],
        exp_dir / "summary.json",
        exp_dir / "summary.csv",
        description="E13: False confirmations per window under normal netem jitter",
    )

    comp = []
    for cfg, k in (("naive", 1), ("k1", 1), ("k2", 2), ("k3", 3)):
        rates = res["values_by_key"].get((cfg, "empirical_rate"), [])
        confs = res["values_by_key"].get((cfg, "false_confirmations"), [])
        wins = res["values_by_key"].get((cfg, "windows"), [])
        q1_metric = "q1_raw_gt20" if cfg == "naive" else "q1_raw_gt22"
        q1s = res["values_by_key"].get((cfg, q1_metric), [])
        qas = res["values_by_key"].get((cfg, "q_alpha_gt22"), [])
        if not rates:
            continue
        r_st = compute_ci(rates)
        c_st = compute_ci(confs)
        qa_mean = statistics.mean(qas)
        q1_mean = statistics.mean(q1s)
        total_conf = int(round(sum(confs)))
        total_win = int(round(sum(wins)))
        if cfg == "naive":
            pred = q1_mean * (1.0 - q1_mean)
        elif k == 1:
            pred = qa_mean * (1.0 - qa_mean)
        else:
            pred = qa_mean ** k
        upper_bound_95 = (3.0 / total_win) if total_conf == 0 and total_win > 0 else None
        comp.append({
            "config": cfg,
            "k": k,
            "n": r_st["n_independent_runs"],
            "total_confirmations": total_conf,
            "total_windows": total_win,
            "conf_mean": f"{c_st['mean']:.3f}",
            "rate_mean": f"{r_st['mean']:.8f}",
            "rate_ci95": f"[{r_st['ci95_t_low']:.8f}, {r_st['ci95_t_high']:.8f}]",
            "rule_of_3_upper95": f"{upper_bound_95:.8f}" if upper_bound_95 is not None else "",
            "q1_raw_mean": f"{q1_mean:.6f}",
            "q_alpha_mean": f"{qa_mean:.6f}",
            "predicted_rate": f"{pred:.8f}",
        })

    with (exp_dir / "model_comparison.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(comp[0].keys()))
        w.writeheader()
        w.writerows(comp)

    fig, ax = plt.subplots(figsize=(6.8, 4.3), constrained_layout=True)
    damped = [row for row in comp if row["config"] in ("k1", "k2", "k3")]
    ks = [int(r["k"]) for r in damped]
    qa = [float(r["q_alpha_mean"]) for r in damped]
    preds = [max(1e-9, float(r["predicted_rate"])) for r in damped]
    emp = [float(r["rate_mean"]) for r in damped]
    ax.plot(ks, preds, "--o", color="#c56a27", linewidth=1.6, label="Damped model q_alpha(1-q_alpha) / q_alpha^k")
    ax.plot(ks, qa, ":", color="#666666", linewidth=1.4, label="Upper bound q_alpha")
    for k_v, e_v, r_row in zip(ks, emp, damped):
        if e_v > 0:
            ax.scatter([k_v], [e_v], color="#147d79", s=55, zorder=5, label="Damped empirical rate" if k_v == 1 else None)
        else:
            ub = float(r_row["rule_of_3_upper95"])
            ax.errorbar([k_v], [ub], yerr=[[ub * 0.5], [0.0]], uplims=True, fmt="v", color="#147d79",
                        markersize=7, label="0 confirmed (95% upper 3/W)")
    naive_row = next((r for r in comp if r["config"] == "naive"), None)
    if naive_row:
        ax.scatter([1], [float(naive_row["rate_mean"])], color="#243746", marker="s", s=55, zorder=5,
                   label="Naive empirical (alpha=1, h=0, k=1)")
        ax.scatter([1], [float(naive_row["predicted_rate"])], facecolors="none", edgecolors="#243746",
                   marker="D", s=70, zorder=5, label="Naive predicted q1(1-q1), theta=20 ms")
    ax.set_yscale("log")
    ax.set_xticks([1, 2, 3], ["1", "2", "3"])
    ax.set_xlabel("Consecutive confirmation count k")
    ax.set_ylabel("False confirmation rate per window (log scale)")
    ax.set_title("E13: False Confirmations vs. Confirmation Count k (Prop. 4)")
    ax.legend(frameon=False, fontsize=8.5, loc="lower left")
    ax.spines[["top", "right"]].set_visible(False)
    for ext in ("png", "pdf"):
        fig.savefig(exp_dir / f"fig_e13_false_confirmations.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"E13 summarized {len(files)} raw files")


def summarize_e14() -> None:
    import re
    exp_dir = REDF_ROOT / "E14"
    raw_dir = exp_dir / "raw"
    files = sorted(raw_dir.glob("redfill_e14_*.csv"))
    pat = re.compile(r"^redfill_e14_(old|new)_N(\d+)_seed")

    def classify(p: Path) -> Optional[str]:
        m = pat.match(p.name)
        return f"{m.group(1)}_N={int(m.group(2)):02d}" if m else None

    res = summarize_group(files, classify)
    write_summary_files(
        res["summaries"],
        [],
        res["runs"],
        exp_dir / "summary.json",
        exp_dir / "summary.csv",
        description="E14: Contention-safe recovery (cf25af2 old vs. main new with Algorithm 2)",
    )
    print(f"E14 summarized {len(files)} raw files")


def summarize_e15() -> None:
    import re
    exp_dir = REDF_ROOT / "E15"
    raw_dir = exp_dir / "raw"
    files = sorted(raw_dir.glob("redfill_e15_*.csv"))
    for p in files:
        with p.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("metric") == "rtt_ms" and float(row["value"]) > 1000.0:
                    raise ValueError(f"E15 sanity check failed: {p.name} has rtt_ms={row['value']} > 1000 ms")
    pat = re.compile(r"^redfill_e15_(north|middle|south)_(healthy|fault)_")

    def classify(p: Path) -> Optional[str]:
        m = pat.match(p.name)
        return f"{m.group(1)}_{m.group(2)}" if m else None

    res = summarize_group(files, classify)
    write_summary_files(
        res["summaries"],
        [],
        res["runs"],
        exp_dir / "summary.json",
        exp_dir / "summary.csv",
        description="E15: Shared-clock TWAMP-Light-style forward OWD vs. RTT/2 across 3 routes x 2 conditions",
    )
    comp = []
    for route, cond, planned in (
        ("north", "healthy", 6.0),
        ("middle", "healthy", 15.0),
        ("south", "healthy", 24.0),
        ("north", "fault", 44.0),
        ("middle", "fault", 50.0),
        ("south", "fault", 52.0),
    ):
        g = f"{route}_{cond}"
        if (g, "forward_owd_ms") not in res["values_by_key"]:
            continue
        owd = compute_ci(res["values_by_key"][(g, "forward_owd_ms")])
        rtt = compute_ci(res["values_by_key"][(g, "rtt_ms")])
        half = compute_ci(res["values_by_key"][(g, "half_rtt_ms")])
        err = compute_ci(res["values_by_key"][(g, "rtt_half_error_ms")])
        comp_frac = statistics.mean(res["values_by_key"][(g, "owd_compliant_35ms")])
        comp.append({
            "route": route,
            "condition": cond,
            "n": owd["n_independent_runs"],
            "fwd_owd_mean_ms": f"{owd['mean']:.3f}",
            "fwd_owd_ci95": f"[{owd['ci95_t_low']:.3f}, {owd['ci95_t_high']:.3f}]",
            "rtt_mean_ms": f"{rtt['mean']:.3f}",
            "rtt_ci95": f"[{rtt['ci95_t_low']:.3f}, {rtt['ci95_t_high']:.3f}]",
            "rtt_half_ms": f"{half['mean']:.3f}",
            "planned_owd_ms": f"{planned:.1f}",
            "rtt_half_err_vs_owd_ms": f"{err['mean']:+.3f}",
            "owd_vs_planned_ms": f"{owd['mean'] - planned:+.3f}",
            "owd_le_35ms_frac": f"{comp_frac:.2f}",
        })
    if comp:
        with (exp_dir / "model_comparison.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(comp[0].keys()))
            w.writeheader()
            w.writerows(comp)
    print(f"E15 summarized {len(files)} raw files")


def summarize_e16() -> None:
    import re
    exp_dir = REDF_ROOT / "E16"
    raw_dir = exp_dir / "raw"
    files = sorted(raw_dir.glob("redfill_e16_*.csv"))
    pat = re.compile(r"^redfill_e16_(team16_7sw|geant2012)_k(\d+)_seed")

    def classify(p: Path) -> Optional[str]:
        m = pat.match(p.name)
        return f"{m.group(1)}_k={int(m.group(2)):02d}" if m else None

    res = summarize_group(files, classify)
    write_summary_files(
        res["summaries"],
        [],
        res["runs"],
        exp_dir / "summary.json",
        exp_dir / "summary.csv",
        description="E16: Admission latency scaling and software rule-count proxy on 7-switch vs Geant2012",
    )
    comp = []
    for topo in ("team16_7sw", "geant2012"):
        for k in (1, 2, 4, 8, 16, 32, 64):
            g = f"{topo}_k={k:02d}"
            if (g, "admission_latency_ms") not in res["values_by_key"]:
                continue
            lat = compute_ci(res["values_by_key"][(g, "admission_latency_ms")])
            rm = compute_ci(res["values_by_key"][(g, "max_rules_per_switch")])
            rx2 = compute_ci(res["values_by_key"][(g, "max_rules_strict_x2")])
            tot = compute_ci(res["values_by_key"][(g, "total_rules")])
            comp.append({
                "topology": topo,
                "k": k,
                "n": lat["n_independent_runs"],
                "admission_mean_ms": f"{lat['mean']:.3f}",
                "admission_ci95": f"[{lat['ci95_t_low']:.3f}, {lat['ci95_t_high']:.3f}]",
                "max_rules_per_sw_mean": f"{rm['mean']:.2f}",
                "max_rules_per_sw_max": f"{rm['max']:.0f}",
                "max_rules_strict_x2_max": f"{rx2['max']:.0f}",
                "total_rules_mean": f"{tot['mean']:.2f}",
            })
    if comp:
        with (exp_dir / "model_comparison.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(comp[0].keys()))
            w.writeheader()
            w.writerows(comp)
    print(f"E16 summarized {len(files)} raw files")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exp", required=True, choices=["E9", "E10", "E11", "E12", "E13", "E14", "E15", "E16"])
    args = parser.parse_args()
    globals()[f"summarize_{args.exp.lower()}"]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
