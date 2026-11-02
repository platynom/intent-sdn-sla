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
docker compose exec -T sdn python3.9 experiments/artifact_manifest.py verify
```

## Outputs

- Per-run raw CSVs: `experiments/results/raw/*.csv`
- Aggregated summaries (CSV + JSON with 95% Student-$t$ CIs and Welch $t$-tests): `experiments/results/summary/*`
- Figures (PNG + PDF): `experiments/figures/*.{png,pdf}`
- Cryptographic manifest: `experiments/results/MANIFEST.sha256`
- Evaluation report: `docs/EXPERIMENTAL_RESULTS.md` and `docs/PROJECT_REPORT.md`

## Final integration verification and report

Use `feat/final-integration`. Run one live scenario at a time. Measurement harnesses
use isolated temporary databases so the dashboard seed job cannot change their
reservations or traffic-control configuration. Presentation/regression prefixes are
excluded from the registered headline families.

```bash
docker compose exec -T sdn python3.9 scripts/verify_final_integration.py software
docker compose exec -T intent-api python3.9 scripts/verify_final_integration.py api
docker compose exec -T sdn python3.9 scripts/verify_final_integration.py smoke
docker compose exec -T sdn python3.9 scripts/verify_final_integration.py regression
```

The smoke recorder also captures the B3 presentation sequence, a real flow dump,
and read-only database audit output. Recordings in `docs/demo_assets/` contain
actual command output with the code revision and capture date.

For a fresh accounting series, use a new prefix; never append new repetitions to
the retained ten-run family. The final integration series is
`e6accounting_oscillation_b2_*.csv`, documented in `docs/E6_ACCOUNTING.md`.
The historical default-prefix family remains immutable.

Report generation is separate from the SDN runtime dependencies:

```powershell
python -m pip install -r docs/requirements-report.txt
python docs/build_final_report.py
powershell -NoProfile -File docs/render_final_report.ps1 -InputDocx docs/FINAL_REPORT.docx -OutputPdf docs/FINAL_REPORT.pdf
python experiments/verify_summaries.py
```

PDF export requires Microsoft Word on Windows. The committed retained cover,
logo, topology image, and provenance JSON make the DOCX build independent of the
original literature-report file on another machine. Word export updates the page
fields; review every rendered page after changing content or figures. The final
report and its Markdown source supersede earlier progress snapshots.

The final manifest hashes CSV/JSON after CRLF-to-LF canonicalization, matching
Git's cross-platform text representation; it hashes PNG/PDF bytes verbatim.
This avoids false corruption reports caused solely by Windows checkout line
endings. It never rewrites raw data. Verify it with
`python experiments/artifact_manifest.py verify`; regenerate only after reviewing
new result/summary/figure files with `python experiments/artifact_manifest.py write`.
