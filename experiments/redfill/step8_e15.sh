#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/E15/raw

for ROUTE in north middle south; do
    for COND in healthy fault; do
        if ls experiments/results/raw/redfill_e15_${ROUTE}_${COND}_*.csv >/dev/null 2>&1; then
            mv experiments/results/raw/redfill_e15_${ROUTE}_${COND}_*.csv experiments/results/redfill_2026-11/E15/raw/
        fi
        HAVE=$(ls -1 experiments/results/redfill_2026-11/E15/raw/redfill_e15_${ROUTE}_${COND}_*.csv 2>/dev/null | wc -l || true)
        NEED=$((10 - HAVE))
        if [ "${NEED}" -le 0 ]; then
            echo "=== E15 SKIP already complete (${HAVE}/10): ${ROUTE} ${COND} ==="
            continue
        fi
        echo "=== E15 route=${ROUTE} condition=${COND} (running ${NEED}, have ${HAVE}) ==="
        if ! docker compose exec -T \
            -e E15_RESULT_PREFIX="redfill_e15" \
            sdn bash -lc "sed 's/\r$//' experiments/scenarios/e15_one_way_delay.sh | bash -s -- --route ${ROUTE} --condition ${COND} --runs ${NEED}"; then
            echo "$(date -Iseconds) | E15 ${ROUTE} ${COND} | batch error, cleaning mininet and retrying remainder" >> experiments/results/redfill_2026-11/FAILURES.md
            docker compose exec -T sdn mn -c >/dev/null 2>&1 || true
            if ls experiments/results/raw/redfill_e15_${ROUTE}_${COND}_*.csv >/dev/null 2>&1; then
                mv experiments/results/raw/redfill_e15_${ROUTE}_${COND}_*.csv experiments/results/redfill_2026-11/E15/raw/
            fi
            DONE=$(ls -1 experiments/results/redfill_2026-11/E15/raw/redfill_e15_${ROUTE}_${COND}_*.csv 2>/dev/null | wc -l || true)
            REM=$((10 - DONE))
            if [ "${REM}" -gt 0 ]; then
                docker compose exec -T \
                    -e E15_RESULT_PREFIX="redfill_e15" \
                    sdn bash -lc "sed 's/\r$//' experiments/scenarios/e15_one_way_delay.sh | bash -s -- --route ${ROUTE} --condition ${COND} --runs ${REM}" || true
            fi
        fi
        if ls experiments/results/raw/redfill_e15_*.csv >/dev/null 2>&1; then
            mv experiments/results/raw/redfill_e15_*.csv experiments/results/redfill_2026-11/E15/raw/
        fi
    done
done

sed 's/\r$//' "experiments/redfill/redfill_analysis.py" | docker compose exec -T sdn python3.9 - --exp E15
