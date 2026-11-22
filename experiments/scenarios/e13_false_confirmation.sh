#!/usr/bin/env bash
# E13: False SLA confirmations under healthy-link Gaussian jitter across detector
# configurations (naive, k1, k2, k3), testing Proposition 4 (q_alpha^k scaling).
set -euo pipefail

if [ -z "${TEAM16_DB_PATH:-}" ]; then
    export TEAM16_DB_PATH="$(mktemp -d /tmp/team16-e13.XXXXXX)/state.db"
fi

CONFIG="k3"
JITTER_MS="6"
RUNS=10
SAMPLES=600
INTERVAL="0.25"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            CONFIG="$2"
            shift 2
            ;;
        --jitter-ms)
            JITTER_MS="$2"
            shift 2
            ;;
        --runs)
            RUNS="$2"
            shift 2
            ;;
        --samples)
            SAMPLES="$2"
            shift 2
            ;;
        --interval)
            INTERVAL="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--config naive|k1|k2|k3] [--jitter-ms J] [--runs N] [--samples S] [--interval DT]" >&2
            exit 2
            ;;
    esac
done

case "${CONFIG}" in
    naive)
        DETECTOR_ARGS=(--ewma-alpha 1.0 --hysteresis-pct 0.0 --consecutive-required 1)
        K_REQ=1
        ;;
    k1)
        DETECTOR_ARGS=(--ewma-alpha 0.3 --hysteresis-pct 0.1 --consecutive-required 1)
        K_REQ=1
        ;;
    k2)
        DETECTOR_ARGS=(--ewma-alpha 0.3 --hysteresis-pct 0.1 --consecutive-required 2)
        K_REQ=2
        ;;
    k3)
        DETECTOR_ARGS=(--ewma-alpha 0.3 --hysteresis-pct 0.1 --consecutive-required 3)
        K_REQ=3
        ;;
    *)
        echo "--config must be naive, k1, k2, or k3" >&2
        exit 2
        ;;
esac

LOG_DIR="/var/log/team16"
mkdir -p "${LOG_DIR}" /var/run/team16

clean_mininet() {
    pkill -9 -f "ryu-manager" >/dev/null 2>&1 || true
    pkill -9 -f "src.intent_manager.api:app" >/dev/null 2>&1 || true
    pkill -9 -f "Team16Topo" >/dev/null 2>&1 || true
    timeout 15s python3.9 /usr/local/bin/mn -c >/dev/null 2>&1 || true
    for switch in s1 s2 s3 s4 s5 s6 s7; do
        if sudo ovs-dpctl show ovs-system 2>/dev/null \
            | grep -Eq "port [0-9]+: ${switch} \\(internal\\)"; then
            sudo ovs-dpctl del-if ovs-system "${switch}" >/dev/null 2>&1 || true
        fi
    done
}

run_one() {
    local run_idx="$1"
    local ryu_pid="" api_pid="" topo_pid="" echo_pid=""
    cleanup_one() {
        for pid in "${echo_pid:-}" "${topo_pid:-}" "${api_pid:-}" "${ryu_pid:-}"; do
            if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
                kill "${pid}" 2>/dev/null || true
                wait "${pid}" 2>/dev/null || true
            fi
        done
        clean_mininet
    }
    trap cleanup_one EXIT INT TERM RETURN

    clean_mininet
    python3.9 -c "
from src.common import db
conn = db.connect()
db.init_db(conn)
conn.execute('DELETE FROM intents')
conn.execute('DELETE FROM events')
conn.execute('DELETE FROM measurements')
conn.commit()
conn.close()
"
    local run_start
    run_start=$(python3.9 -c 'import time; print(time.time())')

    ryu-manager --ofp-tcp-listen-port 6653 \
        src/enforcement/controller.py >"${LOG_DIR}/ryu-e13.log" 2>&1 &
    ryu_pid=$!
    sleep 2

    python3.9 -m uvicorn src.intent_manager.api:app \
        --host 127.0.0.1 --port 8000 >"${LOG_DIR}/api-e13.log" 2>&1 &
    api_pid=$!
    sleep 2

    python3.9 -c "
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from topology.team16_topo import Team16Topo
from pathlib import Path
import time

net = Mininet(topo=Team16Topo(), switch=OVSSwitch, link=TCLink,
              controller=None, autoSetMacs=True, autoStaticArp=True)
net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)
net.start()
pid_dir = Path('/var/run/team16')
for host in net.hosts:
    (pid_dir / f'{host.name}.pid').write_text(str(host.pid))
time.sleep(600)
net.stop()
" >"${LOG_DIR}/topo-e13.log" 2>&1 &
    topo_pid=$!
    sleep 4

    for sw in s1 s2 s3 s4 s5 s6 s7; do
        local sw_ready=0
        for _ in $(seq 1 60); do
            if sudo ovs-ofctl -O OpenFlow13 dump-flows "${sw}" 2>/dev/null | grep -q "CONTROLLER"; then
                sw_ready=1
                break
            fi
            sleep 0.2
        done
        if [ "${sw_ready}" -ne 1 ]; then
            echo "FAIL: switch ${sw} did not receive table-miss rule"
            exit 1
        fi
    done

    local netem_parent
    netem_parent=$(sudo tc qdisc show dev s1-eth2 \
        | awk '/netem/ {for (i=1; i<=NF; i++) if ($i == "parent") {print $(i+1); exit}}')
    if [ -z "${netem_parent}" ]; then
        echo "FAIL: no netem qdisc found on s1-eth2"
        exit 1
    fi
    sudo tc qdisc change dev s1-eth2 parent "${netem_parent}" \
        netem delay 2ms "${JITTER_MS}ms" distribution normal

    local code
    code=$(curl -s -o /tmp/e13_post.json -w "%{http_code}" -X POST \
        http://127.0.0.1:8000/intent -H "Content-Type: text/plain" \
        --data-binary "@experiments/scenarios/fixtures/redfill_e13.yaml")
    if [ "${code}" != "201" ]; then
        echo "FAIL: POST /intent returned ${code}"
        cat /tmp/e13_post.json || true
        exit 1
    fi

    local active_ok=0
    for _ in $(seq 1 40); do
        active_ok=$(python3.9 -c "
from src.common import db
conn = db.connect()
rec = db.load_intent(conn, 'INT-001')
p = db.current_path(conn, 'INT-001')
sws = ','.join(p.switches) if p else ''
print(1 if (rec and rec.state.value == 'active' and sws == 's1,s2,s3,s7') else 0)
conn.close()")
        if [ "${active_ok}" = "1" ]; then
            break
        fi
        sleep 0.2
    done
    if [ "${active_ok}" != "1" ]; then
        echo "FAIL: INT-001 did not become active on s1,s2,s3,s7"
        exit 1
    fi
    sleep 0.5

    local h1_pid h2_pid
    h1_pid=$(cat /var/run/team16/h1.pid)
    h2_pid=$(cat /var/run/team16/h2.pid)

    mnexec -da "${h2_pid}" python3.9 -u -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('10.0.0.2', 5001))
while True:
    data, addr = s.recvfrom(64)
    s.sendto(data, addr)
" >"${LOG_DIR}/e13-echo.log" 2>&1 &
    echo_pid=$!
    sleep 0.5

    python3.9 -m src.telemetry.runtime \
        --intent INT-001 --source-pid "${h1_pid}" --target 10.0.0.2 --port 5001 \
        --switch s1 --samples "${SAMPLES}" --interval "${INTERVAL}" "${DETECTOR_ARGS[@]}" \
        >"${LOG_DIR}/telemetry-e13-${CONFIG}-${run_idx}.log" 2>&1

    sleep 0.5

    python3.9 - "${CONFIG}" "${K_REQ}" "${JITTER_MS}" "${run_idx}" "${run_start}" <<'PY'
import csv
import os
import sys
import time
from pathlib import Path
from src.common import db
from src.common.events import EventType

config = sys.argv[1]
k_req = int(sys.argv[2])
jitter_ms = float(sys.argv[3])
run_idx = int(sys.argv[4])
run_start = float(sys.argv[5])

conn = db.connect()
rows = db.measurements_for(conn, "INT-001", since=run_start)
delays = [float(r["delay_ms"]) for r in rows if r["delay_ms"] is not None]
confirmations = conn.execute(
    "SELECT COUNT(*) FROM events WHERE intent_id = ? AND at >= ? AND type = ?",
    ("INT-001", run_start, EventType.SLA_VIOLATED.value),
).fetchone()[0]
plan = db.current_path(conn, "INT-001")
conn.close()

assert plan is not None and tuple(plan.switches) == ("s1", "s2", "s3", "s7"), (
    f"Path unexpectedly changed under alert_only: {plan}"
)
n_samples = len(delays)
assert n_samples > 0, "No delay samples collected"

q1_22 = sum(1 for d in delays if d > 22.0) / n_samples
q1_20 = sum(1 for d in delays if d > 20.0) / n_samples

# Offline EWMA replay (alpha=0.3, seeded from first sample) matching ViolationDetector
alpha = 0.3
smoothed = []
prev = None
for d in delays:
    val = d if prev is None else alpha * d + (1.0 - alpha) * prev
    prev = val
    smoothed.append(val)
q_alpha_22 = sum(1 for s in smoothed if s > 22.0) / n_samples

windows = max(1, n_samples - k_req + 1)
empirical_rate = confirmations / float(windows)

prefix = os.environ.get("E13_RESULT_PREFIX", "redfill_e13")
out_dir = Path(os.environ.get("E13_RAW_DIR", "experiments/results/raw"))
out_dir.mkdir(parents=True, exist_ok=True)
trace_dir = Path(os.environ.get("E13_TRACE_DIR", "experiments/results/redfill_2026-11/E13/traces"))
trace_dir.mkdir(parents=True, exist_ok=True)

stamp = time.strftime("%Y%m%d%H%M%S")
trace_path = trace_dir / f"trace_{prefix}_{config}_j{int(jitter_ms)}_{stamp}_{run_idx:02d}.csv"
with trace_path.open("w", newline="", encoding="utf-8") as tf:
    tw = csv.writer(tf)
    tw.writerow(["sample_idx", "at", "delay_ms", "ewma_alpha0p3_ms"])
    for idx, (r, s) in enumerate(zip(rows, smoothed), start=1):
        tw.writerow([idx, f"{float(r['at']):.6f}", r["delay_ms"], f"{s:.6f}"])

out_path = out_dir / f"{prefix}_{config}_j{int(jitter_ms)}_{stamp}_{run_idx:02d}.csv"
now_ts = int(time.time())
with out_path.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["run_id", "timestamp", "metric", "value", "unit"])
    w.writerow([run_idx, now_ts, "false_confirmations", confirmations, "count"])
    w.writerow([run_idx, now_ts, "windows", windows, "count"])
    w.writerow([run_idx, now_ts, "empirical_rate", f"{empirical_rate:.8f}", "rate"])
    w.writerow([run_idx, now_ts, "q1_raw_gt22", f"{q1_22:.8f}", "prob"])
    w.writerow([run_idx, now_ts, "q1_raw_gt20", f"{q1_20:.8f}", "prob"])
    w.writerow([run_idx, now_ts, "q_alpha_gt22", f"{q_alpha_22:.8f}", "prob"])
    w.writerow([run_idx, now_ts, "samples_collected", n_samples, "count"])
    w.writerow([run_idx, now_ts, "jitter_ms", f"{jitter_ms:.3f}", "ms"])
    w.writerow([run_idx, now_ts, "k_required", k_req, "count"])

print(
    f"E13 {config} (J={jitter_ms:g}ms) run {run_idx}: conf={confirmations}/{windows} "
    f"(rate={empirical_rate:.6f}), q1(>22)={q1_22:.4f}, q1(>20)={q1_20:.4f}, "
    f"q_alpha(>22)={q_alpha_22:.4f} -> {out_path}"
)
PY
}

for ((r = 1; r <= RUNS; r++)); do
    echo "=== E13 ${CONFIG} (J=${JITTER_MS}ms) run ${r}/${RUNS} ==="
    run_one "${r}"
done
