#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/E14/raw

# Ensure .redfill_worktrees/ is excluded from git
if ! grep -qxF ".redfill_worktrees/" .git/info/exclude 2>/dev/null; then
    echo ".redfill_worktrees/" >> .git/info/exclude
fi

if [ ! -d ".redfill_worktrees/cf25af2" ]; then
    git worktree add .redfill_worktrees/cf25af2 cf25af2
fi

docker compose exec -T sdn python3.9 experiments/e14_contention.py --repo /app --tag new --runs 10
docker compose exec -T sdn python3.9 experiments/e14_contention.py --repo /app/.redfill_worktrees/cf25af2 --tag old --runs 10

mv experiments/results/raw/redfill_e14_*.csv experiments/results/redfill_2026-11/E14/raw/
sed 's/\r$//' "experiments/redfill/redfill_analysis.py" | docker compose exec -T sdn python3.9 - --exp E14
