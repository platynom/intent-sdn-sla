# Experimental Results and Evaluation Limits

## Evidence and environment

The checked-out evaluation checkpoint is `024910099e91bb8a3fbf1021249ce1eea0ea4dcf`; work is on `feat/st-12-b3-evaluation`. The existing raw run CSVs are in `experiments/results/raw/`, and the checkpoint summary files are under `experiments/results/summary/`. The present Windows host has no Docker CLI. It therefore cannot run the privileged Mininet/OVS/Ryu scenarios or the nine requested additional B3 repetitions. The per-run files discussed below were already present at the checkpoint; they were not produced during this continuation.

The repository's B2/B3 runner invokes `s1_single_intent.sh` with either `--b2` or `--b3`. Both apply a controlled primary-path delay and collect persisted telemetry and path events. B2 uses relaxed updates, alpha 1, no hysteresis and one-sample confirmation. B3 uses strict versioned updates and default smoothing/hysteresis/detector settings. The supplied intent fixtures and scenario script are the operational source; the B2/B3 protocol itself remains a proposal pending team agreement.

## B2/B3 run validation and results

The new analysis script validates required columns, numeric finite values, exactly one run identifier per file, duplicate metrics, and expected units. One CSV file is one run; rows within a file are not counted as independent replicates. It read 10 B2 files and one B3 pilot, with no rejected records. The individual values are included in `experiments/results/summary/b2_b3_comparison.json`.

| Baseline / metric | Valid independent runs | Individual values | Mean | Sample SD | 95% two-sided t interval |
|---|---:|---|---:|---:|---:|
| B2 detection persistence latency (ms) | 10 | See JSON run list | 99.467 | 4.498 | [96.249, 102.684] |
| B2 violation-to-path-install latency (ms) | 10 | See JSON run list | 279.355 | 70.552 | [228.889, 329.821] |
| B2 successful reroutes (count/run) | 10 | 1 each | 1.000 | 0.000 | [1.000, 1.000] |
| B3 detection persistence latency (ms) | 1 | 2,097.640 | 2,097.640 | Not estimable | Not estimable |
| B3 violation-to-path-install latency (ms) | 1 | 475.152 | 475.152 | Not estimable | Not estimable |
| B3 successful reroutes (count/run) | 1 | 1 | 1.000 | Not estimable | Not estimable |

The B2/B3 comparison is not inferential: one B3 run cannot estimate its run-to-run variability or a t interval. Its result is a pilot observation. The detector profiles intentionally differ, so the detection time is an outcome of configuration as well as platform execution. The controlled topology and fault trace are aligned in the scripts, but no claim of B3 improvement or statistical significance follows from these data. The summary's B2 values reproduce the handoff's reported means and intervals within rounding.

### Proposed operational metric definitions (not approved E1–E8)

The values above mean: (1) detection latency is from the first violating telemetry sample to the telemetry process's log timestamp for persisting a confirmed `sla.violated` event; (2) recovery latency is from the confirmed event timestamp to the causal path-installed event timestamp; (3) reroute count is the scenario intent's recorded successful path changes. These correspond to candidate definitions in `docs/EVALUATION_PROTOCOL_PROPOSAL.md`; they are not official E1–E8 definitions.

## Alternating violation/recovery trace

`python -m experiments.scenarios.alternating_trace` replays nine deterministic samples against the actual `ViolationDetector` implementation. The fixed trace alternates 30 ms measured delay (above the 20 ms maximum) and 10 ms delay (below its recovery boundary), uses alpha 1, 10% hysteresis, one-sample confirmation, and a 10-second dwell. The recorded output `experiments/results/raw/alternating_trace.csv` contains sample/phase timestamps, values, detector state, emitted event, event timestamp, remaining dwell seconds, and cumulative accepted violation events.

Observed in this software-only trace: 3 `sla.violated` events, 4 `sla.restored` events, and 2 `violation.suppressed` events. The accepted violation events are detector-level replan signals. This harness updates the model's last-replan timestamp to exercise the real dwell gate, but does not call the live ControlLoop, install switch routes, or measure reroutes. Accordingly, its count is not a live reroute count, and it has no packet loss, throughput or network SLA compliance result. A live alternating fault/recovery run remains required once Docker/Linux networking is available.

## Baseline checks on this host

The bundled runtime is Python 3.12.14. `pytest` and the project's core packages were installed for validation, but the repository pins FastAPI 0.95.2 and Pydantic 1.10.13, whose forward-reference handling fails during test collection on Python 3.12. Full suite collection stopped with errors in `tests/test_dashboard.py` and `tests/test_preemption.py`; this is an interpreter/dependency compatibility issue, not a passing test result. The setup guide specifies the project-supported Python 3.9 container. The full requirements install also stopped while building pinned pandas 1.5.3 on Python 3.12. Ruff passed after the new source was corrected. The four new focused tests pass.

## Comparison limitations and next evidence

- Do not compare B0/B1 raw RTT/throughput with B2/B3 event latency: their traffic windows and metric meanings differ.
- The B2/B3 raw outputs have 10 and 1 independent runs respectively. Additional B3 runs are necessary before uncertainty can be estimated.
- The B3 pilot uses default detector smoothing and strict updates, unlike B2; response latency is not an isolated update-mode effect.
- The protocol proposal's E1–E8 metric names are not approved, and ST-13/ST-14 briefs are absent.
- The emulation validates a small virtual topology and Open vSwitch behavior, not production hardware performance or 5G radio access.
- No chart is generated from this dataset because the B3 sample size is one and the comparative figure would visually overstate precision.
