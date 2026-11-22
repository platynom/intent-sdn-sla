#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/E9/raw
docker compose exec -T -e TEAM16_RESULT_TAG=redfill_e9_b2 sdn bash -lc "sed 's/\r$//' experiments/scenarios/b2_closed_loop.sh | bash -s -- --runs 10"
mv experiments/results/raw/redfill_e9_b2_*.csv experiments/results/redfill_2026-11/E9/raw/
ls -1 experiments/results/redfill_2026-11/E9/raw/redfill_e9_b2_*.csv | wc -l
