#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/SMOKE/raw

echo "=== Hard Rule 5: pytest after scenario script edits ==="
docker compose exec -T sdn pytest tests -q | tee experiments/results/redfill_2026-11/RULE5_PYTEST.txt

echo "=== Hard Rule 5: default B3 smoke run (redfill_smoke_b3) ==="
docker compose exec -T -e TEAM16_RESULT_TAG=redfill_smoke_b3 sdn bash -lc "sed 's/\r$//' experiments/scenarios/b3_closed_loop.sh | bash -s -- --runs 1" | tee experiments/results/redfill_2026-11/RULE5_SMOKE.txt

mv experiments/results/raw/redfill_smoke_b3_*.csv experiments/results/redfill_2026-11/SMOKE/raw/
cat experiments/results/redfill_2026-11/SMOKE/raw/redfill_smoke_b3_*.csv
