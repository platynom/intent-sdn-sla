# Project Handover

## What this project does

An operator describes a network promise as a YAML intent: which traffic matters
and the bandwidth, latency, loss, isolation or link-avoidance requirement it must
meet. The system validates that request, decides whether it is feasible, computes
a suitable path, generates OpenFlow 1.3 rules and OVS HTB queue commands (bound via
`OFPActionSetQueue`), measures the delivered service, and automatically re-plans
when a real SLA breach persists. It is a compact, reproducible reference
implementation for 5G-style service assurance, not a claim of a novel networking
algorithm.

## How to get the code

```bash
git clone --branch feat/st-12-eval-completion https://github.com/5rikanth/SDN.git
cd SDN
```

## The six modules

| Module | Question it answers | Responsibility |
|---|---|---|
| M1 Intent Manager | What does the user want? | Validate and store machine-readable intents; expose the REST API. |
| M2 Admission and Conflict | Can we provide it? | Decide whether capacity exists and resolve competing requests. |
| M3 Path Computation | How can we provide it? | Compute and prune candidate paths, then choose deterministically. |
| M4 Enforcement | Can we make the network do it? | Generate OpenFlow 1.3 rules (`OFPActionSetQueue`) and OVS HTB queue commands; two-phase update. |
| M5 Telemetry and SLA Monitor | Is it actually working? | Collect measurements and distinguish persistent breaches from noise. |
| M6 Dashboard and Audit | What is happening, and why? | Present status and preserve the causal explanation of every action. |

## Current state (`feat/st-12-eval-completion`)

- **Container test suite & lint**: `270 passed, 11 skipped` (`pytest tests -q`), `ruff check src tests topology experiments` clean (`0` errors).
- **Live smoke scenarios**: `s1_single_intent.sh`, `s1_single_intent.sh --st7`, `s9_preemption.sh`, and `s10_two_phase.sh` all pass in sequence inside the privileged Python 3.9 container.
- **Objective O1 (B3 repetitions & matched-detector B2, $n=10$ each)**:
  - `B2` ($n=10$): detection `99.467 ms` (`[96.249, 102.684]`), recovery `279.355 ms` (`[228.889, 329.821]`).
  - `B2_matched_detector` ($n=10$): detection `2116.845 ms` (`[2107.259, 2126.432]`), recovery `467.711 ms` (`[424.880, 510.542]`).
  - `B3` ($n=10$): detection `2104.262 ms` (`[2101.405, 2107.119]`), recovery `618.535 ms` (`[559.508, 677.561]`).
- **Objective O2 (E4 headline packet loss during reconfiguration, $n=10$ each)**:
  - `B2` (`relaxed`): `42.000` packets lost (`[42.000, 42.000]`), `0.000` reordered.
  - `B3` (`strict` two-phase, citing Reitblatt et al., SIGCOMM 2012): `0.000` packets lost (`[0.000, 0.000]`), `28.000` reordered (`[28.000, 28.000]`).
- **Objective O3 (HTB queue binding fix & verification, $n=10$ each)**:
  - Fixed `src/enforcement/flowmod.py` and `src/enforcement/queues.py` so forward inter-switch hops emit `OFPActionSetQueue(1)` when `min_bandwidth_mbps > 0`.
  - `bound` ($n=10$): `24.995 Mbit/s` (`[24.995, 24.996]`, `0.000%` loss) under `150 Mbit/s` competing `iperf3` cross-traffic (`74.352 Mbit/s`).
  - `unbound` control ($n=10$): `19.091 Mbit/s` (`[18.818, 19.365]`, `23.620%` loss — violates the `20 Mbit/s` SLA in all 10 runs).
- **Objective O4 (E5 flow-table entries across 4 concurrent intents, $n=10$ each)**:
  - `all_relaxed`: peak `6.000` rules on busiest switch (`27.500` total across fabric), `56.800` packets lost (`[55.087, 58.513]`).
  - `selective` (2 strict + 2 relaxed, citing CCG, Zhou et al., NSDI 2015): peak `9.000` rules on busiest switch (`39.800` total), `33.900` total packets lost (`0.000` lost on strict intents).
  - `all_strict`: peak `10.000` rules on busiest switch (`42.000` total), `0.000` packets lost.
- **Objective O5 (E6 live route oscillation over 10-minute runs on S6, $n=10$ each)**:
  - `B2` (hysteresis+dwell OFF): `90.000` reroutes/10 min (`[90.000, 90.000]`, `0` dwell suppressions).
  - `B3` (hysteresis+dwell ON): `48.300` reroutes/10 min (`[47.542, 49.058]`, `28.700` dwell suppressions/10 min).
- **Objective O6 (E1 SLA violation duration, $n=10$ each)**:
  - `B1` (open-loop): `15.000 s` (`[15.000, 15.000]`, right-censored at the 15 s fault window).
  - `B3` (closed-loop): `3.003 s` (`[3.003, 3.003]`, uncensored).
- **Objective O7 (E7 admission decision latency scaling, $n=10$ per point)**:
  - `k=1`: `47.889 ms` (`[45.179, 50.599]`); `k=2`: `49.420 ms` (`[46.253, 52.587]`); `k=4`: `49.665 ms` (`[48.146, 51.184]`); `k=8`: `51.845 ms` (`[50.336, 53.354]`); `k=16`: `59.496 ms` (`[53.442, 65.550]`).
- **Objective O8 (E8 control-plane overhead over 60 s window, $n=10$ each)**:
  - `B1` (open-loop): `8.108 msgs/s` (`[8.032, 8.185]`), `0.826%` `ryu-manager` CPU (`[0.789, 0.863]`).
  - `B3` (closed-loop): `9.228 msgs/s` (`[9.129, 9.327]`, $+13.8\%$ higher than `B1`), `0.794%` `ryu-manager` CPU (`[0.768, 0.819]`).
  - Corrected `E8v2` full-stack CPU (primary): `B1` `0.939%` (`[0.907, 0.971]`); `B3` `5.078%` (`[4.954, 5.201]`). The earlier CPU field measured Ryu alone and is preserved but superseded.
- **Objective O9 (ST-13 figures & documentation)**:
  - All PNG and PDF figures generated in `experiments/figures/`.
  - SHA-256 manifest written to `experiments/results/MANIFEST.sha256`.

## Remaining limitations

1. All experiments run in containerized Mininet + Open vSwitch 2.17.12 on a single laptop, not physical ASIC switch hardware or a 5G RAN.
2. Topology is fixed at 7 switches and 8 hosts; links `s3-s7` and `s6-s7` are marked `inferred` in `topology/topology_spec.py`.
3. The 250 ms two-phase drain window is calibrated for this emulated topology, not a general WAN delay bound.
4. For `E6`, $n=10$ ten-minute live runs per baseline (200 minutes total runtime) were executed.
