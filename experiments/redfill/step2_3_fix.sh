#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"

mkdir -p experiments/results/redfill_2026-11/E15/excluded
if [ -f "experiments/results/redfill_2026-11/E15/raw/redfill_e15_middle_healthy_20261119133024_07.csv" ]; then
    mv "experiments/results/redfill_2026-11/E15/raw/redfill_e15_middle_healthy_20261119133024_07.csv" \
       "experiments/results/redfill_2026-11/E15/excluded/"
fi

docker compose exec -T -e E15_RESULT_PREFIX="redfill_e15" sdn bash -lc \
    "sed 's/\r\$//' experiments/scenarios/e15_one_way_delay.sh | bash -s -- --route middle --condition healthy --runs 1"

mv experiments/results/raw/redfill_e15_middle_healthy_*.csv experiments/results/redfill_2026-11/E15/raw/

echo "E15 middle_healthy count: $(ls -1 experiments/results/redfill_2026-11/E15/raw/redfill_e15_middle_healthy_*.csv | wc -l)"
echo "E15 total raw count: $(ls -1 experiments/results/redfill_2026-11/E15/raw/redfill_e15_*.csv | wc -l)"

sed 's/\r$//' "experiments/redfill/redfill_analysis.py" \
    | docker compose exec -T sdn python3.9 - --exp E15
sed 's/\r$//' "experiments/redfill/redfill_analysis.py" \
    | docker compose exec -T sdn python3.9 - --exp E13
