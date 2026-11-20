# Red-Items Analysis and Automation Scripts (`experiments/redfill/`)

This directory archives every analysis, verification, and batch-execution helper script used to produce and validate `experiments/results/redfill_2026-11/` (`E9`–`E16`) against build `75f2d2e` (with E14 also evaluating baseline `cf25af2`). Paths were updated to resolve relative to the repository root; script logic was preserved unchanged.

## Reproduction Order (Derived Summaries and Figures from Raw CSVs)

Start the container stack from the repository root:

```bash
docker compose up -d
```

Regenerate derived CSV, JSON, and figure outputs for all eight extension experiments (`E9`–`E16`) from `experiments/results/redfill_2026-11/*/raw/`:

```bash
for exp in E9 E10 E11 E12 E13 E14 E15 E16; do
    docker compose exec -T sdn python3.9 experiments/redfill/redfill_analysis.py --exp "$exp"
done
```

Notice that `matplotlib` embeds fresh PDF/PNG creation timestamps when figures are regenerated, so if verifying byte-identical derived CSV/JSON outputs in a clean working tree, restore `experiments/results/redfill_2026-11/*/fig_*` afterward via `git checkout --`. See [REPRODUCIBILITY_CHECK.txt](REPRODUCIBILITY_CHECK.txt) for the recorded verification log across all 24 derived CSV/JSON files (`E9`–`E16`).

Independently verify every `(group, metric)` row across `E9`–`E16` `summary.csv` against raw CSVs (plus `rtt_ms <= 1000 ms` in `E15`):

```bash
bash experiments/redfill/step5_verify_only.sh
```

Spot-check percentage errors and directory counts across `E9`, `E11`, `E12`, `E13`, and `E15`:

```bash
docker compose exec -T sdn python3.9 experiments/redfill/check_numbers.py
```

## File Inventory

- `redfill_analysis.py` — Main summarizer and plotter for `--exp E9`..`E16`: reads `experiments/results/redfill_2026-11/<EXP>/raw/*.csv`, computes 95% $t$-confidence intervals (`experiments/summarize_metrics.py`) and Welch $t$-tests (`experiments/analyze_closed_loop.py`), fits $t_0$ (`E10`) and analytical/model comparison tables, and exports PNG/PDF figures.
- `check_numbers.py` — Prints directory contents under `experiments/results/redfill_2026-11/` and percentage-error spot checks for `E9`, `E11`, `E12`, `E13`, and `E15`.
- `REPRODUCIBILITY_CHECK.txt` — Recorded diff output proving all 24 derived CSV/JSON files across `E9`–`E16` regenerate identically from `raw/` using `redfill_analysis.py`.
- `step0.sh` — Captures baseline git commit/branch, Docker/Python environment, `pytest tests -q`, `verify_summaries.py`, and `artifact_manifest.py verify` into `BASELINE.txt`.
- `syntax_check.sh` — Runs `bash -n` (after CRLF stripping) across the six modified/added scenario shell scripts.
- `rule5_verify.sh` — Runs `pytest tests -q` in the `sdn` container and executes a 1-run `b3_closed_loop.sh` smoke test (`redfill_smoke_b3`).
- `step1_recover.sh` — Removes stale `.git/*.lock` and `.redfill_worktrees/cf25af2`, restarts Docker Compose, and runs `mn -c` after interruption.
- `step1_resume.sh` — Recovers after interruption before resuming `E11`: clears git locks, archives completed `E11` CSVs, checks `s1_single_intent.sh` syntax, runs `pytest` + a `b3_closed_loop.sh` smoke2 run (`RULE5_SMOKE2_PYTEST.txt`), and counts existing `E11` raw files.
- `step2a.sh` — Executes `E9` B2 immediate (`b2_closed_loop.sh`, 10 runs) and moves raw CSVs to `E9/raw/`.
- `step2bc.sh` — Executes `E9` B2 matched-detector (`b2_matched_detector.sh`, 10 runs) and B3 damped (`b3_closed_loop.sh`, 10 runs) into `E9/raw/`.
- `step2de.sh` — Executes `E9` O3 unbound and bound (`o3_queue_binding.sh`, 10 runs each) into `E9/raw/` and runs `redfill_analysis.py --exp E9`.
- `step3_e10.sh` — Executes `E10` detection-delay sweep (`b3_closed_loop.sh`, $k \in \{1..5\}$, $\Delta t \in \{0.25, 0.5, 1.0\}\text{ s}$, 10 runs/cell, 150 runs total) with failure recovery into `E10/raw/` and runs `--exp E10`.
- `step4_e11.sh` — Executes `E11` dwell sweep (`e6_oscillation.sh --mode b3 --duration 600`, $\delta \in \{0, 5, 10, 20, 30\}\text{ s}$, 10 runs/cell) with per-slot retry into `E11/raw/` and runs `--exp E11`.
- `step4_e11_resume.sh` — Completes remaining `E11` $\delta = 20\text{ s}$ and $\delta = 30\text{ s}$ runs into `E11/raw/` after host shutdown and runs `--exp E11`.
- `step5_e12.sh` — Executes `E12` path-pair and rate sweep (`e4_packet_loss.sh`, Pairs `A`/`B`/`C`, target rates `250`/`1000`/`4000` pps, `b2`/`b3`, 10 runs/cell, 180 runs total) with failure recovery into `E12/raw/` and runs `--exp E12`.
- `step6_e13.sh` — Calibrates synthetic jitter $J \in \{6, 4, 8, 10\}\text{ ms}$ for $q_1 \in [0.02, 0.10]$, runs `e13_false_confirmation.sh` across `naive`, `k1`, `k2`, `k3` (10 runs each), and runs `--exp E13`.
- `step7_e14.sh` — Creates a `.redfill_worktrees/cf25af2` worktree and runs `experiments/e14_contention.py` (10 runs each on `/app` and `cf25af2`) into `E14/raw/`, then runs `--exp E14`.
- `step7b_e14_live.sh` — Runs `e14_live_check.sh` (20 s) on `/app` and `.redfill_worktrees/cf25af2` with `mn -c` cleanup on failure.
- `step8_e15.sh` — Executes `E15` shared-clock OWD vs. RTT/2 (`e15_one_way_delay.sh`, `north`/`middle`/`south` $\times$ `healthy`/`fault`, 10 runs/cell) into `E15/raw/` and runs `--exp E15`.
- `step2_3_fix.sh` — Moves the pause-corrupted `E15` run into `E15/excluded/`, runs 1 replacement `middle/healthy` run, and recomputes `E15` and `E13` summaries via `--exp E15` and `--exp E13`.
- `step9_e16.sh` — Downloads `Geant2012.graphml` (falling back to archived Topology Zoo mirror on timeout), executes `experiments/e16_topology_zoo.py --runs 10`, moves CSVs into `E16/raw/`, and runs `--exp E16`.
- `step5_verify.sh` — Early end-of-batch verification script (check git/pytest/summaries/manifest, recompute `--exp E9`..`E16`, and verify `summary.csv`); had a Python 3.9 f-string quote issue on lines 44+ and was superseded by `step5_verify_only.sh`.
- `step5_verify_only.sh` — Clean standalone verification of `75f2d2e:experiments/scenarios/e4_packet_loss.sh` and independent raw-to-summary recomputation across all `E9`–`E16` `summary.csv` rows plus `E15` `rtt_ms <= 1000` assertion.
- `step7_commit_push.ps1` — PowerShell helper used to stage, commit (10 logical commits), and push `exp/red-items-2026-11` after completing `E9`–`E16`.
