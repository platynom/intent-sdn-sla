#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/E9/raw

echo "=== Starting E9d: O3 unbound (n=10) ==="
docker compose exec -T -e O3_RESULT_PREFIX=redfill_e9_o3 sdn bash -lc "sed 's/\r$//' experiments/scenarios/o3_queue_binding.sh | bash -s -- --mode unbound --runs 10"
mv experiments/results/raw/redfill_e9_o3_unbound_*.csv experiments/results/redfill_2026-11/E9/raw/

echo "=== Starting E9e: O3 bound (n=10) ==="
docker compose exec -T -e O3_RESULT_PREFIX=redfill_e9_o3 sdn bash -lc "sed 's/\r$//' experiments/scenarios/o3_queue_binding.sh | bash -s -- --mode bound --runs 10"
mv experiments/results/raw/redfill_e9_o3_bound_*.csv experiments/results/redfill_2026-11/E9/raw/

echo "=== Summarizing E9 ==="
sed 's/\r$//' "experiments/redfill/redfill_analysis.py" | docker compose exec -T sdn python3.9 - --exp E9
