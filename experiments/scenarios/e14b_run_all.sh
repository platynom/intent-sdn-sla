#!/usr/bin/env bash
# E14b: live Mininet/OVS contention check, n runs on the current build, then summary.
#   bash experiments/scenarios/e14b_run_all.sh [RUNS]   (default 10, about 1 min per run)
set -uo pipefail
RUNS="${1:-10}"
LOG_DIR="experiments/results/redfill_2026-11/E14_LIVE"
mkdir -p "${LOG_DIR}/raw"
LOG="${LOG_DIR}/e14b_console_$(date +%Y%m%d%H%M%S).log"
pass=0
for i in $(seq 1 "${RUNS}"); do
    echo "=== E14b run ${i}/${RUNS} ===" | tee -a "${LOG}"
    if sed 's/\r$//' experiments/scenarios/e14_live_check.sh | bash -s -- --tag new 2>&1 | tee -a "${LOG}"; then
        pass=$((pass + 1))
    else
        echo "run ${i} FAILED" | tee -a "${LOG}"
    fi
done
echo "=== ${pass}/${RUNS} runs completed ===" | tee -a "${LOG}"
python3.9 experiments/e14_live_summary.py --tag new 2>&1 | tee -a "${LOG}"
echo "Console log: ${LOG}"
