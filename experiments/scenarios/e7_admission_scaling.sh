#!/usr/bin/env bash
# Objective O7 (E7): Admission decision latency (POST /intent -> decision in ms)
# vs number of active intents in SQLite (1, 2, 4, 8, 16), n=10 runs per point.
set -euo pipefail

RUNS=10
while [[ $# -gt 0 ]]; do
    case "$1" in
        --runs)
            RUNS="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--runs N]" >&2
            exit 2
            ;;
    esac
done

LOG_DIR="/var/log/team16"
mkdir -p "${LOG_DIR}" /var/run/team16

API_PID=""
cleanup() {
    if [ -n "${API_PID}" ] && kill -0 "${API_PID}" 2>/dev/null; then
        kill "${API_PID}" 2>/dev/null || true
        wait "${API_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

python3.9 -m uvicorn src.intent_manager.api:app \
    --host 127.0.0.1 --port 8000 >"${LOG_DIR}/api-e7.log" 2>&1 &
API_PID=$!
sleep 2

python3.9 - "${RUNS}" <<'PY'
import csv
import os
import sys
import time
import urllib.request
from pathlib import Path
from src.common import db
from src.common.models import Guarantee, IntentRecord, IntentState, Match, PathPlan

runs = int(sys.argv[1])
active_counts = [1, 2, 4, 8, 16]
out_dir = Path(os.environ.get("E7_RAW_DIR", "experiments/results/raw"))
out_dir.mkdir(parents=True, exist_ok=True)

# Warm up uvicorn/FastAPI once before timed runs
conn = db.connect()
db.init_db(conn)
conn.execute("DELETE FROM intents")
conn.commit()
conn.close()

warmup_yaml = """intent:
  id: INT-999
  tenant: warmup
  priority: 3
  match:
    src: 10.0.0.1/32
    dst: 10.0.0.2/32
    proto: udp
    dport: 5999
  guarantee:
    min_bandwidth_mbps: 1
    max_latency_ms: 20
  consistency: strict
  on_violation: reroute
"""
req = urllib.request.Request(
    "http://127.0.0.1:8000/intent",
    data=warmup_yaml.encode("utf-8"),
    headers={"Content-Type": "text/plain"},
    method="POST",
)
with urllib.request.urlopen(req) as resp:
    assert resp.status == 201

for k in active_counts:
    for r in range(1, runs + 1):
        conn = db.connect()
        db.init_db(conn)
        conn.execute("DELETE FROM paths")
        conn.execute("DELETE FROM intents")
        conn.execute("DELETE FROM events")
        conn.commit()

        # Seed k active intents with paths in SQLite
        for idx in range(1, k + 1):
            intent = IntentRecord(
                id=f"INT-{100 + idx:03d}",
                tenant=f"tenant-{idx}",
                priority=3,
                match=Match(
                    src="10.0.0.1/32",
                    dst="10.0.0.2/32",
                    proto="udp",
                    dport=5100 + idx,
                ),
                guarantee=Guarantee(min_bandwidth_mbps=2.0, max_latency_ms=30.0),
                state=IntentState.ACTIVE,
            )
            plan = PathPlan(
                intent_id=intent.id,
                switches=("s1", "s2", "s3", "s7"),
                links=PathPlan.links_for(["s1", "s2", "s3", "s7"]),
                est_latency_ms=6.0,
                bottleneck_mbps=100.0,
                version=0,
            )
            db.save_intent(conn, intent)
            db.save_path(conn, plan)
        conn.close()

        probe_id = f"INT-{700 + k * 10 + r:03d}"
        probe_yaml = f"""intent:
  id: {probe_id}
  tenant: eval-e7
  priority: 2
  match:
    src: 10.0.0.1/32
    dst: 10.0.0.2/32
    proto: udp
    dport: 5500
  guarantee:
    min_bandwidth_mbps: 5
    max_latency_ms: 20
  consistency: strict
  on_violation: reroute
"""
        req = urllib.request.Request(
            "http://127.0.0.1:8000/intent",
            data=probe_yaml.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            status_code = resp.status
        latency_ms = (time.perf_counter() - t0) * 1000.0
        assert status_code == 201, f"Expected 201, got {status_code}: {body}"

        stamp = time.strftime("%Y%m%d%H%M%S")
        out_path = out_dir / f"e7_admission_k{k:02d}_{stamp}_{r:02d}.csv"
        now_ts = int(time.time())
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["run_id", "timestamp", "metric", "value", "unit"])
            w.writerow([r, now_ts, "admission_decision_latency_ms", f"{latency_ms:.6f}", "ms"])
            w.writerow([r, now_ts, "active_intents", k, "count"])
        print(f"E7 k={k:2d} run {r:2d}/{runs}: {latency_ms:.3f} ms -> {out_path}")
PY
