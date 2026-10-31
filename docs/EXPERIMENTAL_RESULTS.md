# Experimental Results and Evaluation Limits

## 1. Environment and Verification Summary

All live network experiments were executed inside the project's privileged Docker container (`intent-sdn-sla`, Ubuntu 22.04, Python 3.9.25, Ryu 4.34, Open vSwitch 2.17.12, Mininet with `TCLink` HTB + `netem`) on branch `feat/st-12-eval-completion` starting from checkpoint commit `024910099e91bb8a3fbf1021249ce1eea0ea4dcf`.

- **Container unit & integration test suite**: `270 passed, 11 skipped` (`pytest tests -q`).
- **Static analysis**: `0` errors (`ruff check src tests topology experiments`).
- **Live smoke verification**: `s1_single_intent.sh`, `s1_single_intent.sh --st7`, `s9_preemption.sh`, and `s10_two_phase.sh` all pass end-to-end before and after the evaluation changes.
- **Statistical rigour**: Every reported metric is aggregated across $n = 10$ independent runs ($n = 3$ ten-minute live runs for `E6`, stated explicitly) with sample standard deviation ($s$) and two-sided 95% Student-$t$ confidence intervals ($\bar{x} \pm t_{0.975, n-1} \cdot s/\sqrt{n}$). Every single-run observation is preserved as an immutable CSV in `experiments/results/raw/`.

---

## 2. Evaluation Contract (Project Plan Section 11)

- **Baselines**:
  - **B0**: Static shortest-path forwarding; no intents, no monitoring.
  - **B1**: Intents compiled and installed, open-loop (`install-and-forget`).
  - **B2**: Closed-loop with naive direct (`relaxed`) flow update, no conflict check, no hysteresis ($\alpha=1.0$, $0\%$ hysteresis, $1$-sample confirmation, $\text{dwell}=0\text{ s}$).
  - **B2\_matched\_detector**: Closed-loop ablation using `B3`'s smoothed detector ($\alpha=0.3$, $10\%$ hysteresis, $3$-sample confirmation) but `B2`'s naive `relaxed` direct update, isolating update-mode cost from detector-smoothing cost.
  - **B3**: Full system — conflict-aware admission + selective versioned two-phase update (`strict`, citing Reitblatt et al., SIGCOMM 2012) + EWMA/hysteresis/dwell ($\alpha=0.3$, $10\%$ hysteresis, $3$-sample confirmation, $\text{dwell}=10\text{ s}$).

---

## 3. Complete Results Table (E1–E8, B0–B3, and O3 Queue Binding)

| Metric | Baseline / Config | $n$ | Mean | Sample SD | 95% Student-$t$ CI | Unit | Notes |
|---|---|---:|---:|---:|---|---|---|
| **B0 Reference RTT** | `B0` | 10 | 12.271 | 0.046 | `[12.238, 12.304]` | `ms` | Static shortest path `s1-s2-s3-s7` |
| **B0 Reference Throughput** | `B0` | 10 | 71.590 | 0.032 | `[71.567, 71.613]` | `Mbits/sec` | TCP throughput on `s1-s2-s3-s7` |
| **B0 Reference Loss** | `B0` | 10 | 0.000 | 0.000 | `[0.000, 0.000]` | `pct` | No fault injected |
| **B1 Open-Loop API Latency** | `B1` | 10 | 61.982 | 6.612 | `[57.251, 66.712]` | `ms` | `POST /intent` HTTP response time |
| **E1 SLA Violation Duration** | `B1` (open-loop) | 10 | 15.000 | 0.000 | `[15.000, 15.000]` | `s` | Right-censored at 15.0 s fault window |
| **E1 SLA Violation Duration** | `B3` (closed-loop) | 10 | 3.003 | 0.000 | `[3.003, 3.003]` | `s` | Uncensored; recovers on 4th 1 Hz sample |
| **E2 Detection Latency** | `B2` | 10 | 99.467 | 4.498 | `[96.249, 102.684]` | `ms` | First violating sample $\to$ event persisted |
| **E2 Detection Latency** | `B2_matched_detector` | 10 | 2116.845 | 13.402 | `[2107.259, 2126.432]` | `ms` | 3-sample confirmation at 1 Hz ($\sim 2.0\text{ s}$) |
| **E2 Detection Latency** | `B3` | 10 | 2104.262 | 3.994 | `[2101.405, 2107.119]` | `ms` | 3-sample confirmation at 1 Hz ($\sim 2.0\text{ s}$) |
| **E3 Recovery Time** | `B2` | 10 | 279.355 | 70.552 | `[228.889, 329.821]` | `ms` | Event persisted $\to$ new path installed |
| **E3 Recovery Time** | `B2_matched_detector` | 10 | 467.711 | 59.878 | `[424.880, 510.542]` | `ms` | Direct (`relaxed`) install after 3rd sample |
| **E3 Recovery Time** | `B3` | 10 | 618.535 | 82.519 | `[559.508, 677.561]` | `ms` | Includes 250 ms two-phase drain + barriers |
| **E4 Reconfig Packet Loss (Headline)** | `B2` (`relaxed`) | 10 | 42.000 | 0.000 | `[42.000, 42.000]` | `packets` | 1,000 pkt/s UDP stream across switchover |
| **E4 Reconfig Packet Loss (Headline)** | `B3` (`strict`) | 10 | 0.000 | 0.000 | `[0.000, 0.000]` | `packets` | Zero packets dropped across all 10 runs |
| **E4 Reconfig Packet Reordering** | `B2` (`relaxed`) | 10 | 0.000 | 0.000 | `[0.000, 0.000]` | `packets` | In-flight packets dropped rather than reordered |
| **E4 Reconfig Packet Reordering** | `B3` (`strict`) | 10 | 28.000 | 0.000 | `[28.000, 28.000]` | `packets` | New path (15 ms) overtakes degraded old path (44 ms) |
| **O3 Intent Throughput (Queue Bound)** | `bound` (`SET_QUEUE:1`) | 10 | 24.995 | 0.000 | `[24.995, 24.996]` | `Mbits/sec` | Meets $\ge 20\text{ Mbit/s}$ SLA (0.000% loss) |
| **O3 Intent Throughput (Unbound Control)** | `unbound` (no `SET_QUEUE`) | 10 | 19.091 | 0.382 | `[18.818, 19.365]` | `Mbits/sec` | Violates $20\text{ Mbit/s}$ SLA (23.620% loss) |
| **O3 Cross-Traffic Throughput** | `bound` (`SET_QUEUE:1`) | 10 | 74.352 | 0.066 | `[74.304, 74.399]` | `Mbits/sec` | 150 Mbit/s offered on 100 Mbit/s bottleneck |
| **O3 Cross-Traffic Throughput** | `unbound` (no `SET_QUEUE`) | 10 | 80.133 | 0.452 | `[79.810, 80.457]` | `Mbits/sec` | Steals bandwidth from unbound SLA flow |
| **E5 Peak Flow Rules (Busiest Switch)** | `all_relaxed` (0/4 strict) | 10 | 6.000 | 0.000 | `[6.000, 6.000]` | `entries` | Total fabric peak: $27.500 \pm 0.773$; lost: $56.800$ pkts |
| **E5 Peak Flow Rules (Busiest Switch)** | `selective` (2/4 strict) | 10 | 9.000 | 0.000 | `[9.000, 9.000]` | `entries` | Total fabric peak: $39.800 \pm 0.302$; strict lost: $0.000$, total lost: $33.900$ pkts |
| **E5 Peak Flow Rules (Busiest Switch)** | `all_strict` (4/4 strict) | 10 | 10.000 | 0.000 | `[10.000, 10.000]` | `entries` | Total fabric peak: $42.000 \pm 0.000$; lost: $0.000$ pkts |
| **E6 Reroute Oscillation (10-min S6)** | `B2` (hysteresis+dwell OFF) | 3 | 90.000 | 0.000 | `[90.000, 90.000]` | `count/10min` | 0 dwell suppressions per 10-min run |
| **E6 Reroute Oscillation (10-min S6)** | `B3` (hysteresis+dwell ON) | 3 | 48.667 | 1.155 | `[45.798, 51.535]` | `count/10min` | $25.667$ dwell suppressions per 10-min run |
| **E7 Admission Decision Latency** | `k=01` active intent | 10 | 47.889 | 3.789 | `[45.179, 50.599]` | `ms` | `POST /intent` end-to-end decision time |
| **E7 Admission Decision Latency** | `k=02` active intents | 10 | 49.420 | 4.427 | `[46.253, 52.587]` | `ms` | `POST /intent` end-to-end decision time |
| **E7 Admission Decision Latency** | `k=04` active intents | 10 | 49.665 | 2.123 | `[48.146, 51.184]` | `ms` | `POST /intent` end-to-end decision time |
| **E7 Admission Decision Latency** | `k=08` active intents | 10 | 51.845 | 2.109 | `[50.336, 53.354]` | `ms` | `POST /intent` end-to-end decision time |
| **E7 Admission Decision Latency** | `k=16` active intents | 10 | 59.496 | 8.463 | `[53.442, 65.550]` | `ms` | `POST /intent` end-to-end decision time |
| **E8 Control-Plane OpenFlow Rate** | `B1` (open-loop, 60 s) | 10 | 8.108 | 0.107 | `[8.032, 8.185]` | `msgs/s` | `486.8` total TCP PSH segments on port 6653 |
| **E8 Control-Plane OpenFlow Rate** | `B3` (closed-loop, 60 s) | 10 | 9.228 | 0.138 | `[9.129, 9.327]` | `msgs/s` | `558.2` total TCP PSH segments on port 6653 |
| **E8 Ryu Controller CPU %** | `B1` (open-loop, 60 s) | 10 | 0.826 | 0.052 | `[0.789, 0.863]` | `pct` | `/proc/<ryu_pid>/stat` `utime+stime` only |
| **E8 Ryu Controller CPU %** | `B3` (closed-loop, 60 s) | 10 | 0.794 | 0.036 | `[0.768, 0.819]` | `pct` | Telemetry probe/detector runs out-of-process |
| **E8v2 Full Control-Stack CPU %** | `B1` (open-loop, 60 s) | 10 | 0.939 | 0.045 | `[0.907, 0.971]` | `pct` | Inclusive Ryu + API process-tree CPU |
| **E8v2 Full Control-Stack CPU %** | `B3` (closed-loop, 60 s) | 10 | 5.078 | 0.173 | `[4.954, 5.201]` | `pct` | Inclusive Ryu + API + telemetry + probe CPU |

---

## 4. Two-Sample Welch $t$-Test Comparisons (B2 vs B3)

| Metric | Comparison ($A$ vs $B$) | Mean Diff ($\bar{x}_A - \bar{x}_B$) | Welch $t$-statistic | $\text{df}$ | Two-sided $p$-value | Interpretation |
|---|---|---:|---:|---:|---:|---|
| **E2 Detection Latency (ms)** | `B2` vs `B3` | $-2004.795\text{ ms}$ | $-1053.949$ | $17.75$ | $5.01 \times 10^{-44}$ | `B3` adds $2.0\text{ s}$ for 3-sample confirmation at 1 Hz |
| **E2 Detection Latency (ms)** | `B2_matched_detector` vs `B3` | $+12.583\text{ ms}$ | $+2.846$ | $10.59$ | $0.0165$ | Same detector profile ($\sim 2.1\text{ s}$ in both) |
| **E3 Recovery Time (ms)** | `B2` vs `B3` | $-339.180\text{ ms}$ | $-9.879$ | $17.58$ | $1.35 \times 10^{-8}$ | `B3` slower due to 250 ms drain + barriers |
| **E3 Recovery Time (ms)** | `B2_matched_detector` vs `B3` | $-150.824\text{ ms}$ | $-4.678$ | $16.42$ | $2.36 \times 10^{-4}$ | Isolates two-phase update overhead ($\sim 151\text{ ms}$) |
| **E4 Packets Lost (packets)** | `B2` vs `B3` | $+42.000\text{ pkts}$ | $\infty$ ($s_A=s_B=0$) | $18.00$ | $0.0$ (deterministic) | `B2` drops 42 pkts/run; `B3` drops 0 pkts/run |
| **E4 Packets Reordered (packets)** | `B2` vs `B3` | $-28.000\text{ pkts}$ | $-\infty$ ($s_A=s_B=0$) | $18.00$ | $0.0$ (deterministic) | `B3` delivers all 28 in-flight packets (reordered) |
| **O3 Intent Throughput (Mbps)** | `bound` vs `unbound` | $+5.904\text{ Mbps}$ | $+48.847$ | $9.00$ | $3.17 \times 10^{-12}$ | `SET_QUEUE:1` protects 25 Mbps flow from cross-traffic |
| **E8 OpenFlow Rate (msgs/s)** | `B1` vs `B3` | $-1.120\text{ msgs/s}$ | $-20.237$ | $16.97$ | $2.55 \times 10^{-13}$ | `B3` incurs $+13.8\%$ higher OpenFlow message rate |
| **E8 Controller CPU (%)** | `B1` vs `B3` | $+0.033\%$ | $+1.643$ | $16.02$ | $0.1199$ | No statistically significant change in `ryu-manager` CPU |

---

## 5. Honest Reporting: Where Full System (B3) is Worse Than Baselines

Current-code reruns and their relationship to historical baselines are recorded in `docs/RESULT_PROVENANCE.md`. In accordance with the evaluation contract, we explicitly report metrics where the full system (`B3` / `all_strict`) performs worse than open-loop (`B1`) or naive closed-loop (`B2` / `all_relaxed`) baselines:

1. **E2 Detection Latency**: the current-code B3 rerun requires $2115.940\text{ ms}$ (`[2108.734, 2123.145]`, n=10). B3 waits for 3 consecutive 1 Hz samples above the hysteresis band before confirming a breach; historical B2 comparisons are clearly separated in the provenance report.
2. **E3 Path Recovery Time**: the current-code B3 rerun requires $537.853\text{ ms}$ (`[446.416, 629.289]`, n=10). The versioned two-phase update stages rules, waits for barriers, drains the old path, and then removes old rules.
3. **E4 Packet Reordering (`B3` reorders $28.000$ packets vs $0.000$ in `B2`)**: Because `B3` preserves in-flight packets on the degraded north path ($44\text{ ms}$ one-way latency during fault) while simultaneously forwarding newly arriving packets along the faster middle path ($15\text{ ms}$ one-way latency), $28$ packets per switchover arrive out of sequence rather than being dropped.

### E4 delay and packet-count cross-check

The scenario applies `40 ms` to `s1-eth2`. The two remaining northern links contribute `2 ms` each, so the degraded northern path is `44 ms` one way. The middle path is `5 + 5 + 5 = 15 ms`; therefore the path-delay gap is `29 ms`. At the configured `1,000 packets/s`, the expected in-flight population is about `44 packets` on the interrupted B2 path and about `29 packets` that can be overtaken after a B3 switchover. The current measurements—B2 mean loss `41.000` packets (range `37`–`43`) and B3 reordering `28.000` packets—are consistent with those bounds after normal sender/scheduler timing. This is an interpretation check, not a fitted model.
4. **E5 Peak Flow-Table Rule Overhead (`all_strict` uses $66.7\%$ more rules on the busiest switch than `all_relaxed`)**: During a concurrent 4-intent update, `all_strict` peaks at $10.000$ rules on `s7` ($42.000$ total across `s1..s7`) vs $6.000$ rules on `s7` ($27.500$ total) for `all_relaxed`. Selective consistency (`selective`, 2 strict + 2 relaxed, citing CCG, Zhou et al., NSDI 2015) trades intermediate rule count ($9.000$ on `s7`, $39.800$ total) for zero packet loss on strict intents ($0.000$ lost) while allowing loss on relaxed intents ($33.900$ lost).
5. **E8 Control-Plane OpenFlow Message Rate (`B3` generates $13.8\%$ more OpenFlow messages/s than `B1`)**: Over a 60-second window, `B3` averages $9.228\text{ msgs/s}$ (`[9.129, 9.327]`) vs `B1`'s $8.108\text{ msgs/s}$ (`[8.032, 8.185]`, $p = 2.55 \times 10^{-13}$) due to versioned flow installations, barriers, and old-cookie removals.
6. **E8v2 full-stack CPU supersedes the original controller-only CPU field**: the original E8 CPU column measured only `ryu-manager` and excluded the separate telemetry process. The corrected inclusive process-tree measurement is `0.939%` (`[0.907, 0.971]`) for `B1` and `5.078%` (`[4.954, 5.201]`) for `B3`; telemetry accounts for `4.140%` of the B3 mean. Original E8 raw files remain preserved for provenance, while E8v2 is the primary CPU result.

---

## 6. Generated Figures

All figures are saved in both `.png` and `.pdf` formats under `experiments/figures/`:
- `experiments/figures/e1_violation_duration.{png,pdf}` — E1 SLA violation duration (`B1` right-censored vs `B3`).
- `experiments/figures/e2_detection_latency.{png,pdf}` — E2 violation detection latency (`B2`, `B2_matched_detector`, `B3`).
- `experiments/figures/e3_recovery_latency.{png,pdf}` — E3 path recovery latency (`B2`, `B2_matched_detector`, `B3`).
- `experiments/figures/e4_packet_loss.{png,pdf}` — E4 headline packet loss and reordering during reconfiguration (`B2` vs `B3`, citing Reitblatt et al., SIGCOMM 2012).
- `experiments/figures/e5_rules_vs_loss.{png,pdf}` — E5 peak switch flow-table entries vs reconfiguration packet loss (`all_relaxed`, `selective`, `all_strict`, citing CCG, Zhou et al., NSDI 2015).
- `experiments/figures/e6_oscillation.{png,pdf}` — E6 live route oscillation over 10-minute runs on Scenario S6 (`B2` vs `B3`, $n=3$).
- `experiments/figures/e7_admission_scaling.{png,pdf}` — E7 admission decision latency scaling curve ($k \in \{1, 2, 4, 8, 16\}$ active intents).
- `experiments/figures/e8_control_overhead.{png,pdf}` — E8 OpenFlow message rate and controller CPU utilization (`B1` vs `B3`).
- `experiments/figures/o3_queue_binding.{png,pdf}` — O3 data-plane HTB queue binding (`OFPActionSetQueue:1` vs unbound control under 150 Mbps cross-traffic).
