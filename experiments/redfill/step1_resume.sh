#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"

rm -f .git/*.lock .git/refs/heads/*.lock || true
git status -sb

mkdir -p experiments/results/redfill_2026-11/E11/raw experiments/results/redfill_2026-11/SMOKE/raw
if ls experiments/results/raw/redfill_e11_*.csv >/dev/null 2>&1; then
    mv experiments/results/raw/redfill_e11_*.csv experiments/results/redfill_2026-11/E11/raw/
fi

docker compose up -d
docker update --restart=unless-stopped intent-sdn-sla >/dev/null
docker compose exec -T sdn git config --global --add safe.directory /app
docker compose exec -T sdn mn -c

echo "=== Syntax check s1_single_intent.sh ==="
sed 's/\r$//' experiments/scenarios/s1_single_intent.sh | bash -n

echo "=== Pytest after TEAM16_WAIT_FOR_LIVE_VIOLATION fix ==="
docker compose exec -T sdn pytest tests -q | tee experiments/results/redfill_2026-11/RULE5_SMOKE2_PYTEST.txt

echo "=== Smoke2 default B3 run (flag unset) ==="
docker compose exec -T -e TEAM16_RESULT_TAG=redfill_smoke2_b3 sdn bash -lc "sed 's/\r$//' experiments/scenarios/b3_closed_loop.sh | bash -s -- --runs 1" | tee experiments/results/redfill_2026-11/RULE5_SMOKE2.txt
mv experiments/results/raw/redfill_smoke2_b3_*.csv experiments/results/redfill_2026-11/SMOKE/raw/

echo "=== Existing E11 raw counts ==="
ls -1 experiments/results/redfill_2026-11/E11/raw/ | wc -l
for p in d0 d5 d10 d20 d30; do
    cnt=$(ls -1 experiments/results/redfill_2026-11/E11/raw/redfill_e11_${p}_*.csv 2>/dev/null | wc -l || true)
    echo "  ${p}: ${cnt}"
done
