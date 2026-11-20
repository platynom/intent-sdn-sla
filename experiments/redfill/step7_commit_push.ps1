$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Run-Git {
    param([string[]]$GitArgs)
    & git -C $repo @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') failed with exit code $LASTEXITCODE"
    }
}

# Verify current branch and clean index
$branch = (& git -C $repo branch --show-current).Trim()
if ($branch -ne "exp/red-items-2026-11") {
    throw "Expected branch exp/red-items-2026-11, got $branch"
}

# 1. Parameterized scenario scripts, fixtures, baseline & Rule 5 smoke proofs
Run-Git @("add",
    "experiments/scenarios/s1_single_intent.sh",
    "experiments/scenarios/e6_oscillation.sh",
    "experiments/scenarios/e4_packet_loss.sh",
    "experiments/scenarios/fixtures/redfill_pairB_relaxed.yaml",
    "experiments/scenarios/fixtures/redfill_pairB_strict.yaml",
    "experiments/scenarios/fixtures/redfill_pairC_relaxed.yaml",
    "experiments/scenarios/fixtures/redfill_pairC_strict.yaml",
    "experiments/scenarios/fixtures/redfill_e13.yaml",
    "experiments/scenarios/fixtures/redfill_e15_north.yaml",
    "experiments/scenarios/fixtures/redfill_e15_middle.yaml",
    "experiments/scenarios/fixtures/redfill_e15_south.yaml",
    "experiments/results/redfill_2026-11/BASELINE.txt",
    "experiments/results/redfill_2026-11/RULE5_SMOKE2_PYTEST.txt",
    "experiments/results/redfill_2026-11/SMOKE"
)
Run-Git @("commit", "-m", "feat(experiments): parameterize scenario scripts and add redfill fixtures & baseline proofs")

# 2. E9
Run-Git @("add", "experiments/results/redfill_2026-11/E9")
Run-Git @("commit", "-m", "data(experiments): add E9 same-build Table I/O3 rerun data and Welch tests")

# 3. E10
Run-Git @("add", "experiments/results/redfill_2026-11/E10")
Run-Git @("commit", "-m", "data(experiments): add E10 detection delay sweep (150 runs), t0 fit, and figure")

# 4. E11
Run-Git @("add", "experiments/results/redfill_2026-11/E11")
Run-Git @("commit", "-m", "data(experiments): add E11 dwell timer sweep (50 runs), summaries, and figure")

# 5. E12
Run-Git @("add", "experiments/results/redfill_2026-11/E12")
Run-Git @("commit", "-m", "data(experiments): add E12 rate and path-pair sweep (180 runs) and figure")

# 6. E13
Run-Git @("add", "--chmod=+x", "experiments/scenarios/e13_false_confirmation.sh")
Run-Git @("add", "experiments/results/redfill_2026-11/E13")
Run-Git @("commit", "-m", "feat(experiments): add E13 false-confirmation scenario and jitter results")

# 7. E14
Run-Git @("add", "--chmod=+x", "experiments/e14_contention.py", "experiments/scenarios/e14_live_check.sh")
Run-Git @("add", "experiments/results/redfill_2026-11/E14")
Run-Git @("commit", "-m", "feat(experiments): add E14 contention-safe recovery evaluation (cf25af2 vs main)")

# 8. E15
Run-Git @("add", "--chmod=+x", "scripts/owd_probe.py", "experiments/scenarios/e15_one_way_delay.sh")
Run-Git @("add", "experiments/results/redfill_2026-11/E15")
Run-Git @("commit", "-m", "feat(experiments): add E15 shared-clock OWD probe, scenario, and results")

# 9. E16
Run-Git @("add", "--chmod=+x", "experiments/e16_topology_zoo.py")
Run-Git @("add", "experiments/results/redfill_2026-11/E16")
Run-Git @("commit", "-m", "feat(experiments): add E16 Geant2012 scaling benchmark and rule-count proxy")

# 10. Failure log & response doc
Run-Git @("add", "experiments/results/redfill_2026-11/FAILURES.md", "docs/RED_ITEMS_RESPONSE_2026-11.md")
Run-Git @("commit", "-m", "docs(report): add failure log and RED_ITEMS_RESPONSE_2026-11.md")

Write-Host "=== GIT LOG ==="
Run-Git @("log", "--oneline", "-n", "12")
Write-Host "=== GIT STATUS AFTER COMMITS ==="
Run-Git @("status", "--short")
Write-Host "=== PUSHING BRANCH ==="
Run-Git @("push", "-u", "origin", "exp/red-items-2026-11")
