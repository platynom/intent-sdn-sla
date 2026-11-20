#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/E10/raw

for DT in 0.25 0.5 1.0; do
    DT_TAG="${DT//./p}"
    for K in 1 2 3 4 5; do
        SAMPLES=$((K + 4))
        TAG="redfill_e10_k${K}_dt${DT_TAG}"
        echo "=== E10 K=${K} dt=${DT}s samples=${SAMPLES} tag=${TAG} ==="
        if ! docker compose exec -T \
            -e TEAM16_DETECTOR_K="${K}" \
            -e TEAM16_PROBE_INTERVAL_S="${DT}" \
            -e TEAM16_TELEMETRY_SAMPLES="${SAMPLES}" \
            -e TEAM16_RESULT_TAG="${TAG}" \
            sdn bash -lc "sed 's/\r$//' experiments/scenarios/b3_closed_loop.sh | bash -s -- --runs 10"; then
            echo "$(date -Iseconds) | E10 ${TAG} | failed during batch, running mn -c and filling remaining runs" >> experiments/results/redfill_2026-11/FAILURES.md
            docker compose exec -T sdn mn -c >/dev/null 2>&1 || true
            DONE=$(ls -1 experiments/results/raw/${TAG}_*.csv experiments/results/redfill_2026-11/E10/raw/${TAG}_*.csv 2>/dev/null | wc -l || true)
            REM=$((10 - DONE))
            if [ "${REM}" -gt 0 ]; then
                docker compose exec -T \
                    -e TEAM16_DETECTOR_K="${K}" \
                    -e TEAM16_PROBE_INTERVAL_S="${DT}" \
                    -e TEAM16_TELEMETRY_SAMPLES="${SAMPLES}" \
                    -e TEAM16_RESULT_TAG="${TAG}" \
                    sdn bash -lc "sed 's/\r$//' experiments/scenarios/b3_closed_loop.sh | bash -s -- --runs ${REM}" || true
            fi
        fi
        if ls experiments/results/raw/redfill_e10_*.csv >/dev/null 2>&1; then
            mv experiments/results/raw/redfill_e10_*.csv experiments/results/redfill_2026-11/E10/raw/
        fi
    done
done

sed 's/\r$//' "experiments/redfill/redfill_analysis.py" | docker compose exec -T sdn python3.9 - --exp E10
