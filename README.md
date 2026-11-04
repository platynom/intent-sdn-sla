# Intent-Based SDN for 5G SLA Enforcement

This project implements and evaluates an intent-based SDN service-assurance system: an operator submits a structured bandwidth, latency and loss requirement; the system validates it, checks capacity, selects a path, installs OpenFlow rules and HTB queues, measures traffic, and responds to confirmed violations. It runs on a live Mininet/Open vSwitch software datapath in Docker and uses established methods; it is not a physical 5G deployment or a claim of standards compliance.

**Final report:** [docs/FINAL_REPORT.pdf](docs/FINAL_REPORT.pdf) (18 pages).
**Team 16:** Tanmaya Kumar, Srikanth Dinesh, Dheepak K.
**Design evidence:** [Parameter provenance](docs/PARAMETER_PROVENANCE.md) and [service profiles](docs/SERVICE_PROFILES.md).
[Contributor checkpoint and setup](README_CONTINUE.md).

### Quick start

Use a Linux Docker engine (WSL2 on Windows). The dashboard is at **http://localhost:8080**; its seeded demo samples are labelled simulated. Live Mininet scenarios run separately inside the SDN container.

```bash
git clone --branch feat/final-integration https://github.com/platynom/intent-sdn-sla.git
cd intent-sdn-sla
docker compose up --build -d          # pinned Mininet + OVS + Ryu
docker compose exec sdn make demo     # topology, controller, one URLLC intent
```

The operator dashboard is available locally at `http://localhost:8080`
after `docker compose up --build -d`. It displays intents, current paths, recent
measurements and the audit trail. Four realistic application intents—V2X emergency
telemetry, remote-surgery video, public-safety live video, and smart-grid protection—
are seeded automatically when Docker Compose starts. No manual intent entry is
required. The seed job adds 20 clearly labelled illustrative telemetry samples per
intent only when no samples already exist; these values are simulated, not live network
measurements. Once real collector readings are available, charts show live readings
instead of mixing them with demo samples. The internal M1 API is not published to the
host; the dashboard remains read-only.

## Headline measurements

Generated from the linked summary CSVs; each row has ten runs. E4 also has exact permutation comparisons. These are emulation results using illustrative evaluation intents; runtime delay is RTT while planning uses one-way delay.

| Measurement | n | Mean | 95% t confidence interval | Unit | Source |
|---|---|---|---|---|---|
| Current B3 detection | 10 | 2115.940 | [2108.734, 2123.145] | ms | [b3_current_closed_loop_summary.csv](experiments/results/summary/b3_current_closed_loop_summary.csv) |
| Current B3 recovery | 10 | 537.853 | [446.416, 629.289] | ms | [b3_current_closed_loop_summary.csv](experiments/results/summary/b3_current_closed_loop_summary.csv) |
| Current E4 B2 packets lost | 10 | 41.000 | [39.455, 42.545] | packets | [e4_current_packet_loss_summary.csv](experiments/results/summary/e4_current_packet_loss_summary.csv) |
| Current E4 B3 packets lost | 10 | 0.000 | [0.000, 0.000] | packets | [e4_current_packet_loss_summary.csv](experiments/results/summary/e4_current_packet_loss_summary.csv) |
| Current E4 B3 packets reordered | 10 | 28.000 | [28.000, 28.000] | packets | [e4_current_packet_loss_summary.csv](experiments/results/summary/e4_current_packet_loss_summary.csv) |
| Current O3 protected throughput | 10 | 24.995 | [24.995, 24.996] | Mbps | [o3_current_queue_binding_summary.csv](experiments/results/summary/o3_current_queue_binding_summary.csv) |

See [experimental results](docs/EXPERIMENTAL_RESULTS.md) for E1-E8, exact tests, historical/current-code distinctions and limitations.

---

## What this is

A reference implementation of the intent lifecycle — expression, translation,
activation and **assurance** — for transport-layer network slices, built to run on a
single commodity laptop with 8 GB of RAM.

**We make no novelty claim.** Intent-based SLA assurance is established work, as is
consistent network update (Reitblatt et al., SIGCOMM 2012) and selective update
consistency (CCG, Zhou et al., NSDI 2015). What this repository contributes is an
artifact: an implementation small enough that anyone can run it, measured against
explicit baselines with confidence intervals, with each component's contribution
isolated.

## Architecture

| Module | Question it answers | What it does |
|---|---|---|
| **M1** Intent Manager | *What does the user want?* | YAML parse, JSON-Schema validation, REST API, SQLite store |
| **M2** Admission & Conflict | *Can we provide it?* | Residual-capacity graph; admit / reject / preempt / degrade |
| **M3** Path Computation | *How can we provide it?* | Yen k-shortest paths with constraint pruning |
| **M4** Enforcement | *Can we make the network do it?* | OpenFlow 1.3 rules, HTB queues (`SET_QUEUE`), two-phase versioned update |
| **M5** Telemetry & SLA Monitor | *Is it actually working?* | Per-intent delay, jitter and loss; hysteresis and dwell timer |
| **M6** Dashboard & Audit Log | *What is happening, and why?* | Live topology, SLA badges, causal event chain |

```
intents/*.yaml → M1 → M2 → M3 → M4 → [ Mininet / Open vSwitch ] → M5
                            ↑                                       │
                            └───────── violation event ─────────────┘
```

The edge from M5 back to M3 is the closed loop. Everything above it is compilation;
everything below it is assurance.

## The intent grammar is frozen

Five constraint types, three violation actions, one 1–5 priority scale. See
[`src/intent_manager/schema.json`](src/intent_manager/schema.json) and ADR-002 in
[`docs/decisions.md`](docs/decisions.md). CI fails if the grammar widens.

```yaml
intent:
  id: INT-001
  tenant: telemedicine-video
  priority: 1                    # 1 = highest … 5 = best effort
  match:
    src: 10.0.0.1/32
    dst: 10.0.0.2/32
    proto: udp
    dport: 5001
  guarantee:                     # the five frozen constraint types
    min_bandwidth_mbps: 20
    max_latency_ms: 20
    max_loss_pct: 0.5
    # isolate_from: [public-internet]
    # avoid_links: [s3-s4]
  consistency: strict            # strict → two-phase update | relaxed → direct install
  on_violation: reroute          # reroute | degrade | alert_only
  dwell_seconds: 10              # anti-oscillation hold-off
```

## Service profiles

`GET /profiles` exposes pinned Release 17 QoS references, source metadata and
assumptions. `POST /intent/from-profile` generates a normal intent and calls the
unchanged validation/admission path. The frozen schema and topology are unchanged.
The default latency target is CN PDB; bandwidth assumptions and the PER/IP-loss
proxy are disclosed in [SERVICE_PROFILES.md](docs/SERVICE_PROFILES.md).

```bash
docker compose exec -T intent-api curl -s http://127.0.0.1:8000/profiles
docker compose exec -T intent-api curl -sS http://127.0.0.1:8000/intent/from-profile \
  -H 'Content-Type: application/json' --data-binary @- <<'JSON'
{"service_class":"embb","intent_id":"INT-950","tenant":"profile-video","match":{"src":"10.0.0.1/32","dst":"10.0.0.2/32","proto":"udp","dport":5001}}
JSON
```

Classes: `urllc` (remote-surgery proxy), `v2x`, `smart_grid` (high-voltage
protection), `embb`, `mmtc` (project-selected non-GBR 5QI 9). Optional `overrides`
contains guarantee fields; looser settings produce warnings. Default delay-critical
profiles are intentionally infeasible on the h1-to-h2 topology and return explained
refusals, not weakened budgets. HTTP 201 alone does not prove activation: inspect
the response state and actual forwarding evidence. Existing demos and E1-E8 use
illustrative intents; their evaluation scope is unchanged.

## Repository layout

```
intents/              example intent per scenario, plus deliberately invalid ones
src/
  intent_manager/     M1  schema.json, validator.py, REST API
  admission/          M2  residual graph, feasibility, preemption
  pathing/            M3  yen_ksp.py, prune.py
  enforcement/        M4  flowmod.py, queues.py, two_phase.py, controller.py
  telemetry/          M5  collector.py, probes.py, detector.py, loop.py, runtime.py
  dashboard/          M6  read-only operator dashboard and audit view
  common/             models.py, db.py, events.py, audit.py
topology/             Mininet topology and tc link budgets
experiments/          scenarios/, results/{raw,summary}/, figures/, analyze/summarize/plot scripts
docs/                 architecture.md, decisions.md, EXPERIMENTAL_RESULTS.md, PROJECT_REPORT.md
tests/                unit tests plus end-to-end smoke and evaluation analysis tests
```

## Development

```bash
python3.9 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests -q          # software-only suite; no network or root needed
ruff check src tests topology experiments
```

Everything touching Mininet, Open vSwitch or Ryu **must** run inside the container.
The verified Ryu 4.34 stack is pinned to Python 3.9 inside Docker. See ADR-001
and its compatibility correction in `docs/decisions.md`; the host interpreter is
not the runtime used for live-network verification.

### Branch policy

`main` is protected. Work on `feat/<subtask>-<short-name>`, open a pull request, and
have one other member review it. CI must pass before merge. A change to a module
interface needs agreement from both sides, recorded in `docs/decisions.md`.

## Evaluation

The project plan (Section 11 of `00_TEAM16_Project_Plan.pdf`) defines four baselines (`B0`–`B3`) and eight metrics (`E1`–`E8`), plus data-plane HTB queue-binding verification (`O3`), with at least 10 independent runs per configuration, including ten-minute live runs for `E6`, and two-sided 95% Student-$t$ confidence intervals. Results, statistical comparisons, and limitations are documented in [`docs/EXPERIMENTAL_RESULTS.md`](docs/EXPERIMENTAL_RESULTS.md).

```bash
# Closed-loop E2/E3 latency evaluation (B2, B2_matched_detector, B3):
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/b2_closed_loop.sh | bash -s -- --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/b2_matched_detector.sh | bash -s -- --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/b3_closed_loop.sh | bash -s -- --runs 10"
# Headline E4 packet loss during reconfiguration (1,000 pkt/s UDP stream):
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/e4_packet_loss.sh | bash -s -- --mode b2 --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/e4_packet_loss.sh | bash -s -- --mode b3 --runs 10"
# O3 HTB queue binding under 150 Mbps cross-traffic (bound vs unbound control):
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/o3_queue_binding.sh | bash -s -- --mode bound --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/o3_queue_binding.sh | bash -s -- --mode unbound --runs 10"
# E5 flow-table entries (all_strict, selective, all_relaxed), E6 oscillation, E1, E7, E8:
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/e5_flow_table_entries.sh | bash -s -- --mode all_strict --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/e6_oscillation.sh | bash -s -- --mode b3 --runs 3 --duration 600"
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/e1_violation_duration.sh | bash -s -- --mode b3 --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/e7_admission_scaling.sh | bash -s -- --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/e8_control_overhead.sh | bash -s -- --mode b3 --runs 10 --window 60"
# Recompute summaries and regenerate all PNG + PDF figures:
docker compose exec -T sdn python3.9 experiments/analyze_closed_loop.py
docker compose exec -T sdn python3.9 experiments/summarize_metrics.py
docker compose exec -T sdn python3.9 experiments/plot_results.py
```

| | Baseline |
|---|---|
| **B0** | Static shortest-path forwarding; no intents, no monitoring |
| **B1** | Intents installed, but open-loop (install-and-forget) |
| **B2** | Closed loop, naive update, no conflict check, no hysteresis |
| **B3** | Full system: conflict-aware admission + two-phase + hysteresis |

## Status

The evaluated implementation and standards-derived profile layer are integrated on
branch `feat/final-integration`; the final report is in `docs/FINAL_REPORT.docx/.pdf`.
- **Current tests**: container `305 passed, 11 skipped`; Windows host `316 passed`. `ruff check src tests topology experiments` exits 0.
- **Profile functional checks**: eMBB and non-GBR mMTC installed the northern path and forwarded matching traffic; the default delay-critical profiles returned explained refusals. This is not 3GPP service-compliance evidence.
- **Live smoke scenarios**: `s1_single_intent.sh`, `s1_single_intent.sh --st7`, `s9_preemption.sh`, and `s10_two_phase.sh` all pass in sequence.
- **Resolved HTB queue-binding defect (O3)**: Forward inter-switch OpenFlow rules now emit `OFPActionSetQueue(1)` when `min_bandwidth_mbps > 0`. Under 150 Mbit/s competing cross-traffic (`n=10`), the queue-bound 20 Mbit/s SLA intent achieves `24.995 Mbit/s` (`[24.995, 24.996]`, `0.000%` loss), whereas the unbound control drops to `19.091 Mbit/s` (`[18.818, 19.365]`, `23.620%` loss).
- **Complete E1–E8 evaluation (`n=10` per configuration, including ten-minute live runs for E6)**:
  - **E1 Violation duration**: `15.000 s` right-censored (`B1`) vs `3.003 s` (`[3.003, 3.003]`, `B3`).
  - **E2 Detection latency**: current-code `B3` is `2115.940 ms` (`[2108.734, 2123.145]`, n=10). Historical baseline comparisons are retained in the provenance report.
  - **E3 Recovery latency**: current-code `B3` is `537.853 ms` (`[446.416, 629.289]`, n=10). Historical baseline comparisons are retained in the provenance report.
  - **E4 Headline packet loss during reconfiguration (current code)**: `41.000` packets lost (`[39.455, 42.545]`, `B2` relaxed) vs `0.000` (`B3` strict two-phase), with `28.000` packets reordered due to the faster alternate path.
  - **E5 Flow-table entries (4 concurrent intents)**: peak `6.000` rules on busiest switch (`56.800` pkts lost) for `all_relaxed`, `9.000` rules (`33.900` total pkts lost, `0.000` strict pkts lost) for `selective` 50/50 (citing CCG, Zhou et al., NSDI 2015), and `10.000` rules (`0.000` pkts lost) for `all_strict`.
  - **E6 Route oscillation (10-min live S6)**: `90.000` reroutes/10 min (`B2`) vs `48.300` (`[47.542, 49.058]`, `B3`, with `28.700` dwell suppressions/10 min).
  - **E7 Admission scaling**: `47.889 ms` (`k=1`), `49.420 ms` (`k=2`), `49.665 ms` (`k=4`), `51.845 ms` (`k=8`), `59.496 ms` (`k=16`).
  - **E8 Control-plane overhead (60 s window)**: corrected E8v2 full-control-stack CPU is `0.939%` (`[0.907, 0.971]`, `B1`) vs `5.078%` (`[4.954, 5.201]`, `B3`). The original controller-only CPU result is retained as provenance but superseded because it excluded the telemetry process.
- See [`docs/HANDOVER.md`](docs/HANDOVER.md), [`docs/EXPERIMENTAL_RESULTS.md`](docs/EXPERIMENTAL_RESULTS.md), and [`docs/RESULT_PROVENANCE.md`](docs/RESULT_PROVENANCE.md) for full details.

**Resolved ST-7 defect.** Confirmed violation events are persisted to SQLite for
the controller and audit log to consume. The live ST-7 scenario verified
the persisted event, reroute, causal audit entry and post-reroute UDP delivery.

## Licence

MIT. See [`CITATION.cff`](CITATION.cff) for the work whose methods this implements —
in particular the two-phase versioned update of Reitblatt et al. (SIGCOMM 2012) and
selective consistency of Zhou et al. (NSDI 2015), which we use as building blocks and
do not claim as contributions.
