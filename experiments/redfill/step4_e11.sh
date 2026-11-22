#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/E11/raw

for D in 0 5 10 20 30; do
    PREFIX="redfill_e11_d${D}"
    echo "=== E11 dwell=${D}s prefix=${PREFIX} (n=10 x 600s) ==="
    if ! docker compose exec -T \
        -e TEAM16_E6_DWELL_S="${D}" \
        -e E6_RESULT_PREFIX="${PREFIX}" \
        sdn bash -lc "sed 's/\r$//' experiments/scenarios/e6_oscillation.sh | bash -s -- --mode b3 --runs 10 --duration 600"; then
        echo "$(date -Iseconds) | E11 ${PREFIX} | batch exited nonzero, running mn -c and completing remaining slots one-by-one" >> experiments/results/redfill_2026-11/FAILURES.md
        docker compose exec -T sdn mn -c >/dev/null 2>&1 || true
        DONE=$(ls -1 experiments/results/raw/${PREFIX}_*.csv experiments/results/redfill_2026-11/E11/raw/${PREFIX}_*.csv 2>/dev/null | wc -l || true)
        REM=$((10 - DONE))
        for ((s = 1; s <= REM; s++)); do
            if ! docker compose exec -T \
                -e TEAM16_E6_DWELL_S="${D}" \
                -e E6_RESULT_PREFIX="${PREFIX}" \
                sdn bash -lc "sed 's/\r$//' experiments/scenarios/e6_oscillation.sh | bash -s -- --mode b3 --runs 1 --duration 600"; then
                echo "$(date -Iseconds) | E11 ${PREFIX} extra-slot ${s} | failed, running mn -c and retrying once" >> experiments/results/redfill_2026-11/FAILURES.md
                docker compose exec -T sdn mn -c >/dev/null 2>&1 || true
                docker compose exec -T \
                    -e TEAM16_E6_DWELL_S="${D}" \
                    -e E6_RESULT_PREFIX="${PREFIX}" \
                    sdn bash -lc "sed 's/\r$//' experiments/scenarios/e6_oscillation.sh | bash -s -- --mode b3 --runs 1 --duration 600" || \
                    echo "$(date -Iseconds) | E11 ${PREFIX} extra-slot ${s} | retry failed, moving on" >> experiments/results/redfill_2026-11/FAILURES.md
            fi
        done
    fi
    if ls experiments/results/raw/redfill_e11_*.csv >/dev/null 2>&1; then
        mv experiments/results/raw/redfill_e11_*.csv experiments/results/redfill_2026-11/E11/raw/
    fi
done

sed 's/\r$//' "experiments/redfill/redfill_analysis.py" | docker compose exec -T sdn python3.9 - --exp E11
