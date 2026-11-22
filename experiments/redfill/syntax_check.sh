#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
for f in experiments/scenarios/{s1_single_intent,e6_oscillation,e4_packet_loss,e13_false_confirmation,e15_one_way_delay,e14_live_check}.sh; do
    sed 's/\r$//' "$f" | bash -n
done
echo "ALL_SH_SYNTAX_OK"
