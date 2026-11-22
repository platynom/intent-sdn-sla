#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd))"
mkdir -p experiments/results/redfill_2026-11/E16/raw

if [ ! -f "experiments/results/redfill_2026-11/E16/Geant2012.graphml" ]; then
    if ! curl -fL --max-time 20 "http://www.topology-zoo.org/files/Geant2012.graphml" -o "experiments/results/redfill_2026-11/E16/Geant2012.graphml"; then
        echo "$(date -Iseconds) | E16 download | curl http://www.topology-zoo.org/files/Geant2012.graphml timed out/failed; falling back to archived Topology Zoo GitHub mirror (mroughan/InternetTopologyZoo or prateekshyap/CPP-in-SDN)" >> experiments/results/redfill_2026-11/FAILURES.md
        curl -fL --max-time 30 "https://raw.githubusercontent.com/prateekshyap/CPP-in-SDN/master/Geant2012.graphml" -o "experiments/results/redfill_2026-11/E16/Geant2012.graphml"
    fi
fi

docker compose exec -T sdn python3.9 experiments/e16_topology_zoo.py --graphml experiments/results/redfill_2026-11/E16/Geant2012.graphml --runs 10
mv experiments/results/raw/redfill_e16_*.csv experiments/results/redfill_2026-11/E16/raw/
sed 's/\r$//' "experiments/redfill/redfill_analysis.py" | docker compose exec -T sdn python3.9 - --exp E16
