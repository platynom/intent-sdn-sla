#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/E9/raw

echo "=== Starting E9b: B2 matched-detector (n=10) ==="
docker compose exec -T -e TEAM16_RESULT_TAG=redfill_e9_b2matched sdn bash -lc "sed 's/\r$//' experiments/scenarios/b2_matched_detector.sh | bash -s -- --runs 10"
mv experiments/results/raw/redfill_e9_b2matched_*.csv experiments/results/redfill_2026-11/E9/raw/

echo "=== Starting E9c: B3 damped (n=10) ==="
docker compose exec -T -e TEAM16_RESULT_TAG=redfill_e9_b3 sdn bash -lc "sed 's/\r$//' experiments/scenarios/b3_closed_loop.sh | bash -s -- --runs 10"
mv experiments/results/raw/redfill_e9_b3_*.csv experiments/results/redfill_2026-11/E9/raw/

echo "=== E9b + E9c counts ==="
ls -1 experiments/results/redfill_2026-11/E9/raw/redfill_e9_b2matched_*.csv | wc -l
ls -1 experiments/results/redfill_2026-11/E9/raw/redfill_e9_b3_*.csv | wc -l
