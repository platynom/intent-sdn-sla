#!/usr/bin/env python3
"""Generate publication-quality evaluation figures (.png and .pdf) with 95% Student-t CIs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _summary_rows(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8") as stream:
        return {row["metric"]: row for row in csv.DictReader(stream)}


def _group_metric_rows(path: Path) -> Dict[Tuple[str, str], dict]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as stream:
        out = {}
        for row in csv.DictReader(stream):
            grp = row.get("group") or row.get("baseline") or ""
            out[(grp, row["metric"])] = row
        return out


def _save_both(fig: plt.Figure, stem_path: Path) -> None:
    stem_path.parent.mkdir(parents=True, exist_ok=True)
    png_path = stem_path.with_suffix(".png")
    pdf_path = stem_path.with_suffix(".pdf")
    fig.savefig(png_path, dpi=200, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    plt.close(fig)


def _extract_ci(row: dict) -> Tuple[float, float, float, int]:
    mean = float(row["mean"])
    low = float(row.get("ci95_t_low") or row.get("ci95_low") or mean)
    high = float(row.get("ci95_t_high") or row.get("ci95_high") or mean)
    n = int(row.get("n") or row.get("runs") or 10)
    return mean, max(0.0, mean - low), max(0.0, high - mean), n


def plot_b0_metric(rows: dict, metric: str, title: str, ylabel: str, output: Path) -> None:
    row = rows.get(metric)
    if row is None:
        return
    mean = float(row["mean"])
    low = float(row["ci95_low"])
    high = float(row["ci95_high"])
    lower_error = max(0.0, mean - low)
    upper_error = max(0.0, high - mean)

    fig, ax = plt.subplots(figsize=(6.4, 4.0), constrained_layout=True)
    ax.bar(["B0"], [mean], color="#147d79", width=0.5)
    ax.errorbar(
        ["B0"],
        [mean],
        yerr=[[lower_error], [upper_error]],
        fmt="none",
        ecolor="#243746",
        capsize=6,
        linewidth=1.4,
    )
    ax.set_title(f"{title} (n={row['runs']}, 95% Student t CI)")
    ax.set_ylabel(ylabel)
    ax.set_ylim(0, max(high * 1.22, 0.1))
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_flow_pilot(path: Path, output: Path) -> None:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or not {"limit", "requested_rules", "installed_rules"}.issubset(rows[0]):
        raise ValueError(f"{path} is not a flow-table pilot CSV")

    labels = [row["limit"] for row in rows]
    installed = [int(row["installed_rules"]) for row in rows]
    requested = max(int(row["requested_rules"]) for row in rows)
    positions = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(7.0, 4.0), constrained_layout=True)
    ax.bar(positions, installed, color="#147d79", label="Rules retained")
    ax.axhline(requested, color="#c56a27", linestyle="--", linewidth=1.4, label="Requested")
    ax.set_xticks(positions, labels)
    ax.set_xlabel("Configured OVS flow limit")
    ax.set_ylabel("Installed dummy rules")
    ax.set_ylim(0, requested * 1.18)
    ax.set_title("OVS 2.17.12 flow-table cap pilot")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_e1(summary_dir: Path, out_dir: Path) -> None:
    rows = _group_metric_rows(summary_dir / "e1_violation_duration_summary.csv")
    if not rows:
        return
    labels = ["B1 (Open-Loop,\nRight-Censored at 15 s)", "B3 (Closed-Loop\nFull System)"]
    keys = [("B1", "sla_violation_duration_s"), ("B3", "sla_violation_duration_s")]
    means, err_lo, err_hi = [], [], []
    for k in keys:
        m, lo, hi, _ = _extract_ci(rows[k])
        means.append(m)
        err_lo.append(lo)
        err_hi.append(hi)
    fig, ax = plt.subplots(figsize=(6.6, 4.2), constrained_layout=True)
    bars = ax.bar(labels, means, color=["#c56a27", "#147d79"], width=0.48)
    ax.errorbar(labels, means, yerr=[err_lo, err_hi], fmt="none", ecolor="#243746", capsize=6, linewidth=1.5)
    ax.axhline(15.0, color="#8c2d19", linestyle="--", linewidth=1.2, label="Fault window cap (15.0 s)")
    for bar, m in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width() / 2, m + 0.4, f"{m:.2f} s", ha="center", va="bottom", fontsize=9.5)
    ax.set_ylabel("SLA Violation Duration (s)")
    ax.set_title("E1: SLA Violation Duration — B1 vs B3 (n=10, 95% Student-t CI)")
    ax.set_ylim(0, max(means) * 1.22)
    ax.legend(frameon=False, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    _save_both(fig, out_dir / "e1_violation_duration")


def plot_e2_e3(summary_dir: Path, out_dir: Path) -> None:
    rows = _group_metric_rows(summary_dir / "b2_b3_closed_loop_20261025.csv")
    if not rows:
        return
    groups = ["B2", "B2_matched_detector", "B3"]
    xlabels = [
        "B2\n(Relaxed, alpha=1,\nno hysteresis, 1-sample)",
        "B2 Matched Detector\n(Relaxed, alpha=0.3,\n10% hyst., 3-sample)",
        "B3 Full System\n(Strict Two-Phase,\n10% hyst., 3-sample)",
    ]
    colors = ["#c56a27", "#3b7ea1", "#147d79"]

    for metric, fname, title, ylabel in (
        ("detection_latency", "e2_detection_latency", "E2: Violation Detection Latency (n=10, 95% Student-t CI)", "Detection Latency (ms)"),
        ("recovery_latency", "e3_recovery_latency", "E3: Path Recovery Time (n=10, 95% Student-t CI)", "Recovery Time (ms)"),
    ):
        means, err_lo, err_hi = [], [], []
        for g in groups:
            m, lo, hi, _ = _extract_ci(rows[(g, metric)])
            means.append(m)
            err_lo.append(lo)
            err_hi.append(hi)
        fig, ax = plt.subplots(figsize=(7.2, 4.3), constrained_layout=True)
        bars = ax.bar(xlabels, means, color=colors, width=0.5)
        ax.errorbar(xlabels, means, yerr=[err_lo, err_hi], fmt="none", ecolor="#243746", capsize=6, linewidth=1.5)
        offset = max(means) * 0.04
        for bar, m in zip(bars, means):
            ax.text(bar.get_x() + bar.get_width() / 2, m + offset, f"{m:.1f} ms", ha="center", va="bottom", fontsize=9.5)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.set_ylim(0, max(m + h for m, h in zip(means, err_hi)) * 1.22)
        ax.spines[["top", "right"]].set_visible(False)
        _save_both(fig, out_dir / fname)


def plot_e4(summary_dir: Path, out_dir: Path) -> None:
    rows = _group_metric_rows(summary_dir / "e4_packet_loss_summary.csv")
    if not rows:
        return
    labels = ["B2 (Naive Direct Update,\nRelaxed Consistency)", "B3 (Versioned Two-Phase Update,\nStrict Consistency)"]
    lost_m, lost_lo, lost_hi = [], [], []
    reord_m, reord_lo, reord_hi = [], [], []
    for g in ("B2", "B3"):
        m, lo, hi, _ = _extract_ci(rows[(g, "packets_lost")])
        lost_m.append(m)
        lost_lo.append(lo)
        lost_hi.append(hi)
        rm, rlo, rhi, _ = _extract_ci(rows[(g, "packets_reordered")])
        reord_m.append(rm)
        reord_lo.append(rlo)
        reord_hi.append(rhi)

    x = [0, 1]
    width = 0.34
    fig, ax = plt.subplots(figsize=(7.2, 4.4), constrained_layout=True)
    b1 = ax.bar([p - width / 2 for p in x], lost_m, width=width, color="#c56a27", label="Packets Lost (Dropped)")
    ax.errorbar([p - width / 2 for p in x], lost_m, yerr=[lost_lo, lost_hi], fmt="none", ecolor="#243746", capsize=5, linewidth=1.4)
    b2 = ax.bar([p + width / 2 for p in x], reord_m, width=width, color="#3b7ea1", label="Packets Reordered (Faster New Path)")
    ax.errorbar([p + width / 2 for p in x], reord_m, yerr=[reord_lo, reord_hi], fmt="none", ecolor="#243746", capsize=5, linewidth=1.4)

    for bar, m in zip(b1, lost_m):
        ax.text(bar.get_x() + bar.get_width() / 2, m + 1.2, f"{m:.1f}", ha="center", va="bottom", fontsize=9.5, fontweight="bold")
    for bar, m in zip(b2, reord_m):
        ax.text(bar.get_x() + bar.get_width() / 2, m + 1.2, f"{m:.1f}", ha="center", va="bottom", fontsize=9.5)

    ax.set_xticks(x, labels)
    ax.set_ylabel("Packet Count (1,000 pkt/s UDP stream)")
    ax.set_title("E4 (Headline): Packet Loss & Reordering During Reconfiguration (n=10, 95% CI)\nConsistent Two-Phase Updates (Reitblatt et al., SIGCOMM 2012)")
    ax.set_ylim(0, max(lost_m + reord_m) * 1.25)
    ax.legend(frameon=False, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    _save_both(fig, out_dir / "e4_packet_loss")


def plot_e5(summary_dir: Path, out_dir: Path) -> None:
    rows = _group_metric_rows(summary_dir / "e5_flow_table_summary.csv")
    if not rows:
        return
    modes = [("all_relaxed", "All-Relaxed\n(0/4 Strict)"), ("selective", "Selective 50/50\n(2/4 Strict)"), ("all_strict", "All-Strict\n(4/4 Strict)")]
    colors = ["#c56a27", "#3b7ea1", "#147d79"]

    rules_m, rules_lo, rules_hi = [], [], []
    tot_m, tot_lo, tot_hi = [], [], []
    lost_m, lost_lo, lost_hi = [], [], []
    for key, _ in modes:
        rm, rlo, rhi, _ = _extract_ci(rows[(key, "peak_rules_max_switch")])
        rules_m.append(rm)
        rules_lo.append(rlo)
        rules_hi.append(rhi)
        tm, tlo, thi, _ = _extract_ci(rows[(key, "peak_rules_total")])
        tot_m.append(tm)
        tot_lo.append(tlo)
        tot_hi.append(thi)
        lm, llo, lhi, _ = _extract_ci(rows[(key, "packets_lost")])
        lost_m.append(lm)
        lost_lo.append(llo)
        lost_hi.append(lhi)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 4.5), constrained_layout=True)
    xlabels = [lbl for _, lbl in modes]
    b_sw = ax1.bar(xlabels, rules_m, color=colors, width=0.48)
    ax1.errorbar(xlabels, rules_m, yerr=[rules_lo, rules_hi], fmt="none", ecolor="#243746", capsize=5, linewidth=1.4)
    for bar, m in zip(b_sw, rules_m):
        ax1.text(bar.get_x() + bar.get_width() / 2, m + 0.3, f"{m:.1f}", ha="center", va="bottom", fontsize=9)
    ax1.set_ylabel("Peak Flow-Table Rules on Busiest Switch")
    ax1.set_title("Peak Rules per Switch (s7/s1)")
    ax1.set_ylim(0, max(rules_m) * 1.25)
    ax1.spines[["top", "right"]].set_visible(False)

    ax2.plot(rules_m, lost_m, linestyle="--", color="#666666", linewidth=1.3, zorder=1)
    for idx, (key, lbl) in enumerate(modes):
        clean_lbl = lbl.replace("\n", " ")
        ax2.errorbar(
            [rules_m[idx]],
            [lost_m[idx]],
            xerr=[[rules_lo[idx]], [rules_hi[idx]]],
            yerr=[[lost_lo[idx]], [lost_hi[idx]]],
            fmt="o",
            markersize=9,
            color=colors[idx],
            ecolor="#243746",
            capsize=5,
            label=f"{clean_lbl} (total={tot_m[idx]:.1f} rules, lost={lost_m[idx]:.1f})",
            zorder=3,
        )
    ax2.set_xlabel("Peak Flow-Table Entries per Switch (entries)")
    ax2.set_ylabel("Packets Lost During Reconfiguration (packets)")
    ax2.set_title("Consistency vs Rule Overhead Trade-Off\n(cites CCG, Zhou et al., NSDI 2015)")
    ax2.set_xlim(min(rules_m) - 1.5, max(rules_m) + 1.5)
    ax2.set_ylim(-4, max(lost_m) * 1.25 + 2)
    ax2.legend(frameon=False, loc="upper right", fontsize=8.5)
    ax2.spines[["top", "right"]].set_visible(False)

    fig.suptitle("E5: Flow-Table Entries vs Reconfiguration Packet Loss (n=10, 95% Student-t CI)", fontsize=11.5)
    _save_both(fig, out_dir / "e5_rules_vs_loss")


def plot_e6(summary_dir: Path, out_dir: Path) -> None:
    rows = _group_metric_rows(summary_dir / "e6_oscillation_summary.csv")
    if not rows:
        return
    labels = ["B2 (Hysteresis OFF,\nDwell=0 s, alpha=1.0, k=1)", "B3 (Hysteresis ON 10%,\nDwell=10 s, alpha=0.3, k=3)"]
    means, err_lo, err_hi, n_runs = [], [], [], 3
    for g in ("B2", "B3"):
        m, lo, hi, n = _extract_ci(rows[(g, "reroute_count_10min")])
        means.append(m)
        err_lo.append(lo)
        err_hi.append(hi)
        n_runs = n
    fig, ax = plt.subplots(figsize=(6.6, 4.2), constrained_layout=True)
    bars = ax.bar(labels, means, color=["#c56a27", "#147d79"], width=0.46)
    ax.errorbar(labels, means, yerr=[err_lo, err_hi], fmt="none", ecolor="#243746", capsize=6, linewidth=1.5)
    for bar, m in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width() / 2, m + max(means) * 0.03, f"{m:.1f}", ha="center", va="bottom", fontsize=9.5)
    ax.set_ylabel("Reroutes per 10 Minutes (count)")
    ax.set_title(f"E6: Route Oscillation on Scenario S6 (n={n_runs} ten-minute runs, 95% Student-t CI)")
    ax.set_ylim(0, max(m + h for m, h in zip(means, err_hi)) * 1.22)
    ax.spines[["top", "right"]].set_visible(False)
    _save_both(fig, out_dir / "e6_oscillation")


def plot_e7(summary_dir: Path, out_dir: Path) -> None:
    rows = _group_metric_rows(summary_dir / "e7_admission_scaling_summary.csv")
    if not rows:
        return
    ks = [1, 2, 4, 8, 16]
    means, err_lo, err_hi = [], [], []
    for k in ks:
        m, lo, hi, _ = _extract_ci(rows[(f"k={k:02d}", "admission_decision_latency_ms")])
        means.append(m)
        err_lo.append(lo)
        err_hi.append(hi)
    fig, ax = plt.subplots(figsize=(6.8, 4.2), constrained_layout=True)
    ax.errorbar(ks, means, yerr=[err_lo, err_hi], fmt="-o", color="#147d79", ecolor="#243746", capsize=5, linewidth=1.8, markersize=6.5)
    for k, m in zip(ks, means):
        y_off = -16 if k == 1 else 10
        ax.annotate(f"{m:.1f} ms", (k, m), textcoords="offset points", xytext=(0, y_off), ha="center", fontsize=8.5)
    ax.set_xticks(ks, [str(k) for k in ks])
    ax.set_xlabel("Active Intents in SQLite (count)")
    ax.set_ylabel("POST /intent Admission Decision Latency (ms)")
    ax.set_title("E7: Admission Decision Latency Scaling (n=10 per point, 95% Student-t CI)")
    ax.set_ylim(0, max(m + h for m, h in zip(means, err_hi)) * 1.25)
    ax.spines[["top", "right"]].set_visible(False)
    _save_both(fig, out_dir / "e7_admission_scaling")


def plot_e8(summary_dir: Path, out_dir: Path) -> None:
    rows = _group_metric_rows(summary_dir / "e8_control_overhead_summary.csv")
    if not rows:
        return
    labels = ["B1 (Open-Loop)", "B3 (Closed-Loop Full System)"]
    colors = ["#3b7ea1", "#c56a27"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.2, 4.2), constrained_layout=True)
    for ax, metric, title, ylabel in (
        (ax1, "openflow_msgs_per_s", "OpenFlow Message Rate (port 6653)", "OpenFlow Messages / s"),
        (ax2, "controller_cpu_pct", "Ryu Controller CPU Utilization", "Controller CPU (%)"),
    ):
        means, err_lo, err_hi = [], [], []
        for g in ("B1", "B3"):
            m, lo, hi, _ = _extract_ci(rows[(g, metric)])
            means.append(m)
            err_lo.append(lo)
            err_hi.append(hi)
        bars = ax.bar(labels, means, color=colors, width=0.46)
        ax.errorbar(labels, means, yerr=[err_lo, err_hi], fmt="none", ecolor="#243746", capsize=5, linewidth=1.4)
        for bar, m in zip(bars, means):
            ax.text(bar.get_x() + bar.get_width() / 2, m + max(means) * 0.04, f"{m:.2f}", ha="center", va="bottom", fontsize=9)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.set_ylim(0, max(m + h for m, h in zip(means, err_hi)) * 1.25)
        ax.spines[["top", "right"]].set_visible(False)

    fig.suptitle("E8: Control-Plane Overhead over 60 s Window — B3 Higher than B1 as Expected (n=10, 95% CI)", fontsize=11)
    _save_both(fig, out_dir / "e8_control_overhead")


def plot_o3(summary_dir: Path, out_dir: Path) -> None:
    rows = _group_metric_rows(summary_dir / "o3_queue_binding_summary.csv")
    if not rows:
        return
    labels = ["Unbound Control\n(No SET_QUEUE)", "Queue-Bound (Fixed)\n(OFPActionSetQueue:1)"]
    groups = ["unbound", "bound"]
    intent_m, intent_lo, intent_hi = [], [], []
    cross_m, cross_lo, cross_hi = [], [], []
    for g in groups:
        im, ilo, ihi, _ = _extract_ci(rows[(g, "intent_throughput_mbps")])
        intent_m.append(im)
        intent_lo.append(ilo)
        intent_hi.append(ihi)
        cm, clo, chi, _ = _extract_ci(rows[(g, "cross_traffic_throughput_mbps")])
        cross_m.append(cm)
        cross_lo.append(clo)
        cross_hi.append(chi)

    x = [0, 1]
    width = 0.34
    fig, ax = plt.subplots(figsize=(7.2, 4.4), constrained_layout=True)
    b1 = ax.bar([p - width / 2 for p in x], intent_m, width=width, color="#147d79", label="INT-001 SLA Flow (25 Mbps offered)")
    ax.errorbar([p - width / 2 for p in x], intent_m, yerr=[intent_lo, intent_hi], fmt="none", ecolor="#243746", capsize=5, linewidth=1.4)
    b2 = ax.bar([p + width / 2 for p in x], cross_m, width=width, color="#c56a27", label="Competing Cross-Traffic (150 Mbps offered)")
    ax.errorbar([p + width / 2 for p in x], cross_m, yerr=[cross_lo, cross_hi], fmt="none", ecolor="#243746", capsize=5, linewidth=1.4)
    ax.axhline(20.0, color="#1b4d3e", linestyle="--", linewidth=1.3, label="INT-001 SLA Guarantee (20.0 Mbps)")

    for bar, m in zip(b1, intent_m):
        ax.text(bar.get_x() + bar.get_width() / 2, m + 1.5, f"{m:.2f} Mbps", ha="center", va="bottom", fontsize=9, fontweight="bold")
    for bar, m in zip(b2, cross_m):
        ax.text(bar.get_x() + bar.get_width() / 2, m + 1.5, f"{m:.2f} Mbps", ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x, labels)
    ax.set_ylabel("Received Throughput (Mbit/s)")
    ax.set_title("O3: HTB Queue Binding Enforcement Under Cross-Traffic (n=10, 95% Student-t CI)")
    ax.set_ylim(0, max(cross_m) * 1.22)
    ax.legend(frameon=False, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    _save_both(fig, out_dir / "o3_queue_binding")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=Path("experiments/results/summary/b0_summary_20261025.csv"))
    parser.add_argument("--pilot", type=Path, default=Path("experiments/results/raw/flow_limit_pilot_20261025.csv"))
    parser.add_argument("--summary-dir", type=Path, default=Path("experiments/results/summary"))
    parser.add_argument("--out-dir", type=Path, default=Path("experiments/figures"))
    parser.add_argument("--suffix", default="20261025")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.summary.exists():
        rows = _summary_rows(args.summary)
        plot_b0_metric(
            rows,
            "rtt_avg",
            "B0 mean round-trip latency",
            "RTT (ms)",
            args.out_dir / f"b0_rtt_avg_{args.suffix}.png",
        )
        plot_b0_metric(
            rows,
            "throughput",
            "B0 mean throughput",
            "Throughput (Mbits/s)",
            args.out_dir / f"b0_throughput_{args.suffix}.png",
        )
    if args.pilot.exists():
        plot_flow_pilot(
            args.pilot,
            args.out_dir / f"e5_flow_limit_{args.suffix}.png",
        )

    plot_e1(args.summary_dir, args.out_dir)
    plot_e2_e3(args.summary_dir, args.out_dir)
    plot_e4(args.summary_dir, args.out_dir)
    plot_e5(args.summary_dir, args.out_dir)
    plot_e6(args.summary_dir, args.out_dir)
    plot_e7(args.summary_dir, args.out_dir)
    plot_e8(args.summary_dir, args.out_dir)
    plot_o3(args.summary_dir, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
