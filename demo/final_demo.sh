#!/usr/bin/env bash
# Team 16 final review demo (about 8-10 minutes).
# Run from the repository root inside WSL Ubuntu-22.04:
#   bash demo/final_demo.sh          # live, pauses before each act
#   bash demo/final_demo.sh --auto   # rehearsal, no pauses, no windows opened
# Every run is saved to demo/transcripts/final_demo_<UTC>.txt (fallback evidence).
set -uo pipefail
cd "$(dirname "$0")/.."

AUTO=0
[ "${1:-}" = "--auto" ] && AUTO=1
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p demo/transcripts
LOG="demo/transcripts/final_demo_${STAMP}.txt"
exec > >(tee -a "${LOG}") 2>&1
FAILS=0

pause() {
    if [ "${AUTO}" -eq 0 ]; then
        read -r -p $'\n>>> Press Enter to continue ' _ </dev/tty
    fi
}

act() {
    echo
    echo "=================================================================="
    echo "ACT $1: $2"
    echo "SAY: $3"
    echo "=================================================================="
    pause
}

run() {
    echo
    echo "\$ $1"
    bash -c "$1"
    local rc=$?
    if [ "${rc}" -eq 0 ]; then
        echo "[OK]"
    else
        echo "[FAILED: exit ${rc}]"
        FAILS=$((FAILS + 1))
    fi
}

api() {
    # $1 = method, $2 = path, $3 = optional intent file inside the repository
    if [ -n "${3:-}" ]; then
        run "docker compose exec -T intent-api curl -sS -i -X $1 http://127.0.0.1:8000$2 -H 'Content-Type: text/plain' --data-binary @$3; echo"
    else
        run "docker compose exec -T intent-api curl -sS -i -X $1 http://127.0.0.1:8000$2; echo"
    fi
}

open_file() {
    if [ "${AUTO}" -eq 0 ]; then
        explorer.exe "$(wslpath -w "$1")" >/dev/null 2>&1 || true
    fi
    echo "(opened $1)"
}

echo "Team 16 final demo - started $(date -u) - transcript ${LOG}"
echo "Code revision: $(git log --oneline -1)"

act 0 "Check the system is up" \
    "Everything runs in Docker inside WSL: Mininet, Open vSwitch, the Ryu controller, the intent API and the dashboard."
run "docker compose ps"

act 1 "Operator dashboard" \
    "Open http://localhost:8080. Four application intents are seeded (V2X, remote surgery, public-safety video, smart grid). The yellow SIMULATED label marks illustrative telemetry; live values replace it when the collector runs."
echo "Presenter: show the dashboard in the browser now (INT-010 to INT-013, path, audit trail)."

act 2 "Intent API: reject, accept, refuse a duplicate" \
    "An operator states WHAT it needs, not how. Invalid grammar is rejected with a reason; a valid intent gets a path; a second copy of a live intent is refused (audit fix D6)."
api DELETE /intent/INT-001
api POST /intent intents/invalid/bad_sixth_constraint.yaml
api POST /intent intents/s1_urllc_baseline.yaml
echo "Presenter: refresh the dashboard - INT-001 now appears with its computed path."
pause
api POST /intent intents/s1_urllc_baseline.yaml
api DELETE /intent/INT-001

act 3 "Planning pipeline without the network" \
    "Validation, admission and constrained route selection are deterministic: the same input always gives the same decision, including an explained refusal."
run "docker compose exec -T sdn python3.9 demo_st4.py"

act 4 "Live closed loop: fault, detection, safe reroute" \
    "A 40 ms delay is injected on the primary link. The detector confirms the breach (EWMA, hysteresis, 3 samples), the controller computes a new path on the residual-capacity graph and installs it with the two-phase update."
B3_DB="/tmp/team16-final-b3-${STAMP}.db"
run "sed 's/\r\$//' experiments/scenarios/s1_single_intent.sh | docker compose exec -T -e TEAM16_DB_PATH=${B3_DB} -e TEAM16_RESULT_TAG=regression_final_demo_b3 sdn bash -s -- --b3"
run "docker compose exec -T sdn tail -n 12 /var/log/team16/telemetry.log"
run "docker compose exec -T -e TEAM16_DB_PATH=${B3_DB} sdn python3.9 scripts/show_demo_audit.py | head -n 60"

act 5 "Preemption and two-phase update" \
    "A critical intent preempts a lower-priority one when capacity is short; a strict intent moves paths with the versioned two-phase update so no packet is lost."
run "sed 's/\r\$//' experiments/scenarios/s9_preemption.sh | docker compose exec -T -e TEAM16_DB_PATH=/tmp/team16-final-s9-${STAMP}.db sdn bash -s"
run "sed 's/\r\$//' experiments/scenarios/s10_two_phase.sh | docker compose exec -T -e TEAM16_DB_PATH=/tmp/team16-final-s10-${STAMP}.db sdn bash -s"

act 6 "Evidence" \
    "E4: relaxed reroute loses 41 packets, two-phase loses 0 at the cost of 28 reordered. E6: damping cuts reroutes from 90 to 48 per 10 minutes. E10/E11: the cost models match measurement. Every summary is checked against the raw data."
open_file experiments/figures/e4_packet_loss.png
open_file experiments/figures/e6_oscillation.png
open_file experiments/results/redfill_2026-11/E10/fig_e10_detection_sweep.png
open_file experiments/results/redfill_2026-11/E11/fig_e11_dwell_sweep.png
run "docker compose exec -T sdn python3.9 experiments/verify_summaries.py"

act 7 "Close" \
    "Code, data, scripts and the report are public at github.com/platynom/intent-sdn-sla."

# Keep demo result files out of the evaluation data folder.
for f in experiments/results/raw/regression_final_demo_b3_*.csv; do
    [ -e "${f}" ] && mv "${f}" demo/transcripts/
done

echo
echo "Demo finished $(date -u). Failed steps: ${FAILS}. Transcript: ${LOG}"
