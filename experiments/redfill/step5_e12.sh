#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/E12/raw

for PAIR in A B C; do
    for RATE in 250 1000 4000; do
        for MODE in b2 b3; do
            MODE_TAG="relaxed"
            if [ "${MODE}" = "b3" ]; then
                MODE_TAG="strict"
            fi
            INTENT_FILE=""
            FAULT_DEV="s1-eth2"
            EXP_INIT="s1,s2,s3,s7"
            EXP_ALT="s1,s4,s5,s7"
            if [ "${PAIR}" = "B" ]; then
                INTENT_FILE="experiments/scenarios/fixtures/redfill_pairB_${MODE_TAG}.yaml"
                FAULT_DEV="s1-eth2"
                EXP_INIT="s1,s2,s3,s7"
                EXP_ALT="s1,s6,s7"
            elif [ "${PAIR}" = "C" ]; then
                INTENT_FILE="experiments/scenarios/fixtures/redfill_pairC_${MODE_TAG}.yaml"
                FAULT_DEV="s1-eth3"
                EXP_INIT="s1,s4,s5,s7"
                EXP_ALT="s1,s6,s7"
            fi
            PREFIX="redfill_e12_${PAIR}_r${RATE}"
            if ls experiments/results/raw/${PREFIX}_${MODE}_*.csv >/dev/null 2>&1; then
                mv experiments/results/raw/${PREFIX}_${MODE}_*.csv experiments/results/redfill_2026-11/E12/raw/
            fi
            HAVE=$(ls -1 experiments/results/redfill_2026-11/E12/raw/${PREFIX}_${MODE}_*.csv 2>/dev/null | wc -l || true)
            NEED=$((10 - HAVE))
            if [ "${NEED}" -le 0 ]; then
                echo "=== E12 SKIP already complete (${HAVE}/10): ${PREFIX} ${MODE} ==="
                continue
            fi
            echo "=== E12 pair=${PAIR} rate=${RATE} mode=${MODE} (running ${NEED}, have ${HAVE}) ==="
            if ! docker compose exec -T \
                -e E4_RESULT_PREFIX="${PREFIX}" \
                -e E4_RATE="${RATE}" \
                -e E4_INTENT_FILE="${INTENT_FILE}" \
                -e E4_FAULT_DEV="${FAULT_DEV}" \
                -e E4_EXPECTED_INITIAL="${EXP_INIT}" \
                -e E4_EXPECTED_ALT="${EXP_ALT}" \
                sdn bash -lc "sed 's/\r$//' experiments/scenarios/e4_packet_loss.sh | bash -s -- --mode ${MODE} --runs ${NEED}"; then
                echo "$(date -Iseconds) | E12 ${PREFIX}_${MODE} | batch error, cleaning mininet and retrying remaining slots" >> experiments/results/redfill_2026-11/FAILURES.md
                docker compose exec -T sdn mn -c >/dev/null 2>&1 || true
                if ls experiments/results/raw/${PREFIX}_${MODE}_*.csv >/dev/null 2>&1; then
                    mv experiments/results/raw/${PREFIX}_${MODE}_*.csv experiments/results/redfill_2026-11/E12/raw/
                fi
                DONE=$(ls -1 experiments/results/redfill_2026-11/E12/raw/${PREFIX}_${MODE}_*.csv 2>/dev/null | wc -l || true)
                REM=$((10 - DONE))
                for ((s = 1; s <= REM; s++)); do
                    if ! docker compose exec -T \
                        -e E4_RESULT_PREFIX="${PREFIX}" \
                        -e E4_RATE="${RATE}" \
                        -e E4_INTENT_FILE="${INTENT_FILE}" \
                        -e E4_FAULT_DEV="${FAULT_DEV}" \
                        -e E4_EXPECTED_INITIAL="${EXP_INIT}" \
                        -e E4_EXPECTED_ALT="${EXP_ALT}" \
                        sdn bash -lc "sed 's/\r$//' experiments/scenarios/e4_packet_loss.sh | bash -s -- --mode ${MODE} --runs 1"; then
                        echo "$(date -Iseconds) | E12 ${PREFIX}_${MODE} slot ${s} | failed, running mn -c and retrying once" >> experiments/results/redfill_2026-11/FAILURES.md
                        docker compose exec -T sdn mn -c >/dev/null 2>&1 || true
                        docker compose exec -T \
                            -e E4_RESULT_PREFIX="${PREFIX}" \
                            -e E4_RATE="${RATE}" \
                            -e E4_INTENT_FILE="${INTENT_FILE}" \
                            -e E4_FAULT_DEV="${FAULT_DEV}" \
                            -e E4_EXPECTED_INITIAL="${EXP_INIT}" \
                            -e E4_EXPECTED_ALT="${EXP_ALT}" \
                            sdn bash -lc "sed 's/\r$//' experiments/scenarios/e4_packet_loss.sh | bash -s -- --mode ${MODE} --runs 1" || \
                            echo "$(date -Iseconds) | E12 ${PREFIX}_${MODE} slot ${s} | retry failed, moving on" >> experiments/results/redfill_2026-11/FAILURES.md
                    fi
                done
            fi
            if ls experiments/results/raw/redfill_e12_*.csv >/dev/null 2>&1; then
                mv experiments/results/raw/redfill_e12_*.csv experiments/results/redfill_2026-11/E12/raw/
            fi
        done
    done
done

sed 's/\r$//' "experiments/redfill/redfill_analysis.py" | docker compose exec -T sdn python3.9 - --exp E12
