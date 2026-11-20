#!/usr/bin/env bash
set -uo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"

echo "=== E14 Step 7b: new (/app) ==="
docker compose exec -T sdn bash -lc "sed 's/\r\$//' experiments/scenarios/e14_live_check.sh | bash -s -- --repo /app --tag new --duration 20"
rc_new=$?
echo "rc_new=$rc_new"
if [ "$rc_new" -ne 0 ]; then
    echo "Cleaning mininet after new failure..."
    docker compose exec -T sdn python3.9 /usr/local/bin/mn -c || true
fi

echo "=== E14 Step 7b: old (.redfill_worktrees/cf25af2) ==="
docker compose exec -T sdn bash -lc "sed 's/\r\$//' experiments/scenarios/e14_live_check.sh | bash -s -- --repo /app/.redfill_worktrees/cf25af2 --tag old --duration 20"
rc_old=$?
echo "rc_old=$rc_old"
if [ "$rc_old" -ne 0 ]; then
    echo "Cleaning mininet after old failure..."
    docker compose exec -T sdn python3.9 /usr/local/bin/mn -c || true
fi
exit $(( rc_new != 0 || rc_old != 0 ? 1 : 0 ))
