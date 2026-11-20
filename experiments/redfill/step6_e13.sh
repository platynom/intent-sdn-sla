#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/E13/calibration experiments/results/redfill_2026-11/E13/raw experiments/results/redfill_2026-11/E13/traces

# Step 6 calibration: try J=6 first, then 4, 8, 10 until 0.02 <= q1_raw_gt22 <= 0.10
CHOSEN_J=""
for J in 6 4 8 10; do
    echo "=== E13 Calibration J=${J} ms (naive, 1 run x 600 samples @ 0.25s) ==="
    docker compose exec -T \
        -e E13_RESULT_PREFIX="redfill_e13_cal_j${J}" \
        sdn bash -lc "sed 's/\r$//' experiments/scenarios/e13_false_confirmation.sh | bash -s -- --config naive --jitter-ms ${J} --runs 1 --samples 600 --interval 0.25"
    mv experiments/results/raw/redfill_e13_cal_j${J}_*.csv experiments/results/redfill_2026-11/E13/calibration/
    Q1=$(python3 -c "
import csv, glob
p = sorted(glob.glob('experiments/results/redfill_2026-11/E13/calibration/redfill_e13_cal_j${J}_*.csv'))[-1]
with open(p) as f:
    rows = {r['metric']: float(r['value']) for r in csv.DictReader(f)}
print(f\"{rows['q1_raw_gt22']:.6f}\")
")
    echo "Calibration J=${J} ms -> q1(>22ms) = ${Q1}"
    OK=$(python3 -c "print(1 if 0.02 <= float('${Q1}') <= 0.10 else 0)")
    if [ "${OK}" = "1" ]; then
        CHOSEN_J="${J}"
        break
    fi
done

if [ -z "${CHOSEN_J}" ]; then
    echo "FAIL: No tested J in {6,4,8,10} gave q1 in [0.02, 0.10]"
    exit 1
fi

echo "${CHOSEN_J}" > experiments/results/redfill_2026-11/E13/chosen_jitter_ms.txt
echo "=== E13 Chosen J=${CHOSEN_J} ms ==="

for CFG in naive k1 k2 k3; do
    echo "=== E13 config=${CFG} J=${CHOSEN_J}ms (n=10 x 600 samples) ==="
    if ! docker compose exec -T \
        -e E13_RESULT_PREFIX="redfill_e13" \
        sdn bash -lc "sed 's/\r$//' experiments/scenarios/e13_false_confirmation.sh | bash -s -- --config ${CFG} --jitter-ms ${CHOSEN_J} --runs 10 --samples 600 --interval 0.25"; then
        echo "$(date -Iseconds) | E13 ${CFG} J=${CHOSEN_J} | batch error, cleaning mininet and retrying remainder" >> experiments/results/redfill_2026-11/FAILURES.md
        docker compose exec -T sdn mn -c >/dev/null 2>&1 || true
        DONE=$(ls -1 experiments/results/raw/redfill_e13_${CFG}_*.csv experiments/results/redfill_2026-11/E13/raw/redfill_e13_${CFG}_*.csv 2>/dev/null | wc -l || true)
        REM=$((10 - DONE))
        if [ "${REM}" -gt 0 ]; then
            docker compose exec -T \
                -e E13_RESULT_PREFIX="redfill_e13" \
                sdn bash -lc "sed 's/\r$//' experiments/scenarios/e13_false_confirmation.sh | bash -s -- --config ${CFG} --jitter-ms ${CHOSEN_J} --runs ${REM} --samples 600 --interval 0.25" || true
        fi
    fi
    if ls experiments/results/raw/redfill_e13_*.csv >/dev/null 2>&1; then
        mv experiments/results/raw/redfill_e13_*.csv experiments/results/redfill_2026-11/E13/raw/
    fi
done

sed 's/\r$//' "experiments/redfill/redfill_analysis.py" | docker compose exec -T sdn python3.9 - --exp E13
