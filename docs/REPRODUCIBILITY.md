# Reproducibility Guide

## Supported environment

Use Linux with Docker Engine, or Windows/macOS with Docker Desktop backed by Linux (WSL2 on Windows). Mininet depends on Linux network namespaces, `tc`, and the Open vSwitch datapath; it is not supported natively in Windows PowerShell. Docker Compose runs the SDN service privileged with host networking. The project Docker image is the supported way to provide Python 3.9, Ryu, Mininet, and OVS. Software-only validation can run on Windows, macOS, or Linux with the development requirements, subject to the repository's pinned Python compatibility.

## Setup and baseline checks

From the repository root:

```bash
docker compose build
docker compose up -d
docker compose exec -T sdn python3.9 -m pytest tests -q
docker compose exec -T sdn ruff check src tests topology experiments
docker compose exec -T sdn python3.9 tools/verify_setup.py
```

On Windows PowerShell, use a Python 3.9 venv for software-only work:

```powershell
py -3.9 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python -m ruff check src tests topology experiments
python demo_st4.py
```

`requirements.txt` is for the container. The host development dependency file excludes Ryu and Mininet.

## Start, stop, and live checks

```bash
docker compose up -d
docker compose exec -T sdn ovs-vsctl --version
docker compose exec -T sdn python3.9 -c "import ryu; print(ryu.version)"
docker compose exec -T sdn bash experiments/scenarios/s1_single_intent.sh
docker compose exec -T sdn bash experiments/scenarios/s1_single_intent.sh --st7
docker compose down
```

## B2 and B3 experiment commands

Run from the Linux-backed container. The B3 command below asks for nine additional repetitions; do not run it until the container and baseline are verified. Each successful scenario writes a timestamped `b3_closed_loop_*.csv` file. Check the scenario output and each CSV's metrics before accepting a run.

```bash
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/b2_closed_loop.sh | bash -s -- --runs 10"
docker compose exec -T sdn bash -lc "sed 's/\\r$//' experiments/scenarios/b3_closed_loop.sh | bash -s -- --runs 9"
docker compose exec -T sdn python3.9 experiments/analyze_closed_loop.py
```

Historical raw files are append-only. The analysis writes `experiments/results/summary/b2_b3_comparison.json` and includes run-level values, sample sizes, sample SD, two-sided Student t intervals when n > 1, and exclusions.

## Alternating detector/dwell replay

The checked-in deterministic replay exercises the production detector on alternating samples without any network privileges:

```bash
python -m experiments.scenarios.alternating_trace --run-id local-trace-01 --dwell-seconds 10 --output experiments/results/raw/alternating_trace.csv
python -m pytest tests/test_evaluation_analysis.py -q
```

This replay measures detector state transitions and candidate replan events. It does not run the ControlLoop or install routes. A live extension requires a Linux-backed Docker host, a fault/recovery traffic schedule, run-unique state cleanup, and route/event verification before it can report reroute counts.

## Outputs

- Existing per-run observations: `experiments/results/raw/`
- Existing evaluation summaries: `experiments/results/summary/`
- Current machine-readable B2/B3 comparison: `experiments/results/summary/b2_b3_comparison.json`
- Alternating detector trace: `experiments/results/raw/alternating_trace.csv`
- Experiment and limitation narrative: `docs/EXPERIMENTAL_RESULTS.md`
- Academic report sources: `docs/PROJECT_REPORT.md` and `docs/LITERATURE_REVIEW.md`

## Troubleshooting and limits

- If Docker Desktop does not use a Linux backend, Mininet/OVS namespace setup cannot work; enable WSL2/Linux containers and restart Docker Desktop.
- If `docker compose exec` says no service is running, start with `docker compose up -d` and inspect `docker compose logs sdn`.
- Ryu is pinned for Python 3.9 in the image. Do not install the container requirements into an arbitrary modern host Python.
- The supplied Windows host for this continuation had no Docker CLI. Consequently, no live scenario was run here; the commands above remain instructions, not verified commands from this host.
- The checkpoint handoff reports 261 passed, 11 skipped and clean Ruff under the supported container. That historical result is attributed to the handoff, not repeated on this Windows host.
- Do not label metrics E1–E8 until the team supplies or approves their source definitions. `docs/EVALUATION_PROTOCOL_PROPOSAL.md` is explicitly a proposal.
