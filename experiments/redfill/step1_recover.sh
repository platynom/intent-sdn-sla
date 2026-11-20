#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
rm -f .git/*.lock
if ! grep -qxF ".redfill_worktrees/" .git/info/exclude 2>/dev/null; then
    echo ".redfill_worktrees/" >> .git/info/exclude
fi
git worktree remove --force .redfill_worktrees/cf25af2 || rm -rf .redfill_worktrees
rmdir .redfill_worktrees 2>/dev/null || true
docker compose up -d
docker compose exec -T sdn mn -c
docker compose ps
