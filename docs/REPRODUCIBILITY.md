# Reproducibility Guide

## Supported environment

Use Linux with Docker Engine, or Windows/macOS with Docker Desktop or WSL2 Docker Engine (`Ubuntu-22.04`). Mininet depends on Linux network namespaces, `tc`, and the Open vSwitch kernel/userspace datapath; it runs inside the privileged `sdn` container (`intent-sdn-sla`, Ubuntu 22.04, Python 3.9.25, Ryu 4.34, Open vSwitch 2.17.12, Mininet).

## Setup and baseline checks (Objective O0)

From the repository root:

```bash
docker compose up --build -d
docker compose exec -T sdn pytest tests -q
docker compose exec -T sdn ruff check src tests topology experiments
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/s1_single_intent.sh | bash -s"
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/s1_single_intent.sh | bash -s -- --st7"
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/s9_preemption.sh | bash -s"
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/s10_two_phase.sh | bash -s"
```

## Full Evaluation Reproduction Commands (Objectives O1–O9)

All raw per-run CSVs are written with unique timestamps and run IDs to `experiments/results/raw/` without overwriting existing files:

```bash
# O1: B3 repetitions (n=9 + 1 existing pilot = 10) and matched-detector B2 (n=10)
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/b3_closed_loop.sh | bash -s -- --runs 9"
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/b2_matched_detector.sh | bash -s -- --runs 10"
docker compose exec -T sdn python3.9 experiments/analyze_closed_loop.py

# O2: E4 packet loss during reconfiguration (1,000 pkt/s UDP stream, n=10 each)
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e4_packet_loss.sh | bash -s -- --mode b2 --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e4_packet_loss.sh | bash -s -- --mode b3 --runs 10"

# O3: HTB queue binding verification under 150 Mbps cross-traffic (n=10 each)
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/o3_queue_binding.sh | bash -s -- --mode bound --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/o3_queue_binding.sh | bash -s -- --mode unbound --runs 10"

# O4: E5 flow-table entries across 4 concurrent intents (n=10 each)
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e5_flow_table_entries.sh | bash -s -- --mode all_strict --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e5_flow_table_entries.sh | bash -s -- --mode selective --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e5_flow_table_entries.sh | bash -s -- --mode all_relaxed --runs 10"

# O5: E6 live route oscillation over 10-minute runs on S6 (n=10 each: 3 initial + 7 additional runs)
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e6_oscillation.sh | bash -s -- --mode b2 --runs 10 --duration 600"
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e6_oscillation.sh | bash -s -- --mode b3 --runs 10 --duration 600"

# O6: E1 SLA violation duration (B1 right-censored vs B3, n=10 each)
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e1_violation_duration.sh | bash -s -- --mode b1 --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e1_violation_duration.sh | bash -s -- --mode b3 --runs 10"

# O7: E7 admission decision latency scaling (k=1,2,4,8,16 active intents, n=10 per point)
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e7_admission_scaling.sh | bash -s -- --runs 10"

# O8: E8 control-plane overhead over a 60 s window (B1 vs B3, n=10 each)
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e8_control_overhead.sh | bash -s -- --mode b1 --runs 10 --window 60"
docker compose exec -T sdn bash -lc "sed 's/\r$//' experiments/scenarios/e8_control_overhead.sh | bash -s -- --mode b3 --runs 10 --window 60"

# O9: Summarize all metrics, generate all PNG + PDF figures, and verify SHA-256 manifest
docker compose exec -T sdn python3.9 experiments/summarize_metrics.py
docker compose exec -T sdn python3.9 experiments/plot_results.py
docker compose exec -T sdn python3.9 experiments/verify_summaries.py
```

## Outputs

- Per-run raw CSVs: `experiments/results/raw/*.csv`
- Aggregated summaries (CSV + JSON with 95% Student-$t$ CIs and Welch $t$-tests): `experiments/results/summary/*`
- Figures (PNG + PDF): `experiments/figures/*.{png,pdf}`
- Cryptographic manifest: `experiments/results/MANIFEST.sha256`
- Evaluation report: `docs/EXPERIMENTAL_RESULTS.md` and `docs/PROJECT_REPORT.md`
