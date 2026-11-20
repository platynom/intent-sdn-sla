#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
docker compose exec -T sdn git config --global --add safe.directory /app
{
  echo "=== GIT ==="
  git rev-parse HEAD
  git log --oneline -1
  git branch --show-current
  echo ""
  echo "=== DOCKER & ENV ==="
  docker --version
  docker compose version
  docker compose exec -T sdn uname -a
  docker compose exec -T sdn python3.9 --version
  echo ""
  echo "=== PYTEST ==="
  docker compose exec -T sdn pytest tests -q
  echo ""
  echo "=== VERIFY SUMMARIES ==="
  docker compose exec -T sdn python3.9 experiments/verify_summaries.py
  echo ""
  echo "=== ARTIFACT MANIFEST ==="
  docker compose exec -T sdn python3.9 experiments/artifact_manifest.py verify
} | tee experiments/results/redfill_2026-11/BASELINE.txt
