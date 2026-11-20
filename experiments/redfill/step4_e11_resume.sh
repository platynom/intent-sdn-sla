#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/E11/raw

run_e11_setting() {
    local D="$1"
    local TARGET_N="$2"
    local PREFIX="redfill_e11_d${D}"
    echo "=== E11 dwell=${D}s prefix=${PREFIX} (running ${TARGET_N} runs x 600s) ==="
    if ! docker compose exec -T \
        -e TEAM16_E6_DWELL_S="${D}" \
        -e E6_RESULT_PREFIX="${PREFIX}" \
        sdn bash -lc "sed 's/\r$//' experiments/scenarios/e6_oscillation.sh | bash -s -- --mode b3 --runs ${TARGET_N} --duration 600"; then
        echo "$(date -Iseconds) | E11 ${PREFIX} | batch exited nonzero, running mn -c and completing remaining slots" >> experiments/results/redfill_2026-11/FAILURES.md
        docker compose exec -T sdn mn -c >/dev/null 2>&1 || true
        if ls experiments/results/raw/${PREFIX}_*.csv >/dev/null 2>&1; then
            mv experiments/results/raw/${PREFIX}_*.csv experiments/results/redfill_2026-11/E11/raw/
        fi
        local HAVE
        HAVE=$(ls -1 experiments/results/redfill_2026-11/E11/raw/${PREFIX}_*.csv 2>/dev/null | wc -l || true)
        local REM=$((10 - HAVE))
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
}

HAVE_D20=$(ls -1 experiments/results/redfill_2026-11/E11/raw/redfill_e11_d20_*.csv 2>/dev/null | wc -l || true)
NEED_D20=$((10 - HAVE_D20))
if [ "${NEED_D20}" -gt 0 ]; then
    run_e11_setting 20 "${NEED_D20}"
fi

HAVE_D30=$(ls -1 experiments/results/redfill_2026-11/E11/raw/redfill_e11_d30_*.csv 2>/dev/null | wc -l || true)
NEED_D30=$((10 - HAVE_D30))
if [ "${NEED_D30}" -gt 0 ]; then
    run_e11_setting 30 "${NEED_D30}"
fi

sed 's/\r$//' "experiments/redfill/redfill_analysis.py" | docker compose exec -T sdn python3.9 - --exp E11
