#!/usr/bin/env bash
# Objective O6 (E1): SLA violation duration (s) from first breach sample to first
# restored-compliance sample under a 15 s primary-link 40 ms delay fault (B1 vs B3).
# For B1 (open-loop), violation persists for the entire 15 s fault window and is
# capped at the 15.0 s fault duration (right-censored = 1).
set -euo pipefail

# Isolate measurement state from the automatically seeded dashboard database.
if [ -z "${TEAM16_DB_PATH:-}" ]; then
    export TEAM16_DB_PATH="$(mktemp -d /tmp/team16-e1.XXXXXX)/state.db"
fi

MODE="b3"
RUNS=10
FAULT_WINDOW_S=15
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --runs)
            RUNS="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--mode b1|b3] [--runs N]" >&2
            exit 2
            ;;
    esac
done

if [[ "${MODE}" != "b1" && "${MODE}" != "b3" ]]; then
    echo "--mode must be b1 or b3" >&2
    exit 2
fi

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
        src/enforcement/controller.py >"${LOG_DIR}/ryu-e1.log" 2>&1 &
    ryu_pid=$!
    sleep 2

    python3.9 -m uvicorn src.intent_manager.api:app \
        --host 127.0.0.1 --port 8000 >"${LOG_DIR}/api-e1.log" 2>&1 &
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
time.sleep(300)
net.stop()
" >"${LOG_DIR}/topo-e1.log" 2>&1 &
    topo_pid=$!
    sleep 4

    local netem_parent
    netem_parent=$(sudo tc qdisc show dev s1-eth2 \
        | awk '/netem/ {for (i=1; i<=NF; i++) if ($i == "parent") {print $(i+1); exit}}')
    if [ -z "${netem_parent}" ]; then
        echo "FAIL: no primary-path netem qdisc found on s1-eth2"
        exit 1
    fi
    sudo tc qdisc change dev s1-eth2 parent "${netem_parent}" netem delay 40ms

    local intent_payload="/tmp/e1_intent_${MODE}.yaml"
    if [ "${MODE}" = "b1" ]; then
        # B1 is open-loop (install-and-forget: no closed-loop reroute on violation)
        sed 's/on_violation: reroute/on_violation: alert_only/' \
            experiments/scenarios/fixtures/b3_single_intent.yaml > "${intent_payload}"
    else
        cp experiments/scenarios/fixtures/b3_single_intent.yaml "${intent_payload}"
    fi

    local code
    code=$(curl -s -o /tmp/e1_post.json -w "%{http_code}" -X POST \
        http://127.0.0.1:8000/intent -H "Content-Type: text/plain" \
        --data-binary "@${intent_payload}")
    if [ "${code}" != "201" ]; then
        echo "FAIL: POST /intent returned ${code}"
        exit 1
    fi
    sleep 2

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
" >"${LOG_DIR}/e1-echo.log" 2>&1 &
    echo_pid=$!
    sleep 0.5

    # Collect 8 samples for B3 (recovers at sample ~4) or 15 samples for B1 (persists across 15s fault window)
    local n_samples=8
    if [ "${MODE}" = "b1" ]; then
        n_samples=15
    fi
    python3.9 -m src.telemetry.runtime \
        --intent INT-001 --source-pid "${h1_pid}" --target 10.0.0.2 --port 5001 \
        --switch s1 --samples "${n_samples}" --interval 1.0 \
        >"${LOG_DIR}/telemetry-e1-${MODE}-${run_idx}.log" 2>&1

    python3.9 - "${MODE}" "${run_idx}" "${run_start}" "${FAULT_WINDOW_S}" <<'PY'
import csv
import os
import sys
import time
from pathlib import Path
from src.common import db
from src.common.models import Measurement

mode = sys.argv[1]
run_idx = int(sys.argv[2])
run_start = float(sys.argv[3])
fault_window_s = float(sys.argv[4])

conn = db.connect()
intent = db.load_intent(conn, 'INT-001')
rows = db.measurements_for(conn, 'INT-001', since=run_start)
samples = [
    Measurement(
        'INT-001',
        float(r['at']),
        r['delay_ms'],
        r['jitter_ms'],
        r['loss_pct'],
        r['throughput_mbps'],
    )
    for r in rows
]
conn.close()

first_breach = next((s for s in samples if s.violates(intent.guarantee)), None)
assert first_breach is not None, 'No breach sample observed'
first_restored = next(
    (s for s in samples if s.at > first_breach.at and not s.violates(intent.guarantee)),
    None,
)
if first_restored is not None:
    duration_s = first_restored.at - first_breach.at
    right_censored = 0
else:
    # Right-censored at the fault window duration
    duration_s = fault_window_s
    right_censored = 1

out_dir = Path(os.environ.get('E1_RAW_DIR', 'experiments/results/raw'))
out_dir.mkdir(parents=True, exist_ok=True)
stamp = time.strftime('%Y%m%d%H%M%S')
out_path = out_dir / f'e1_violation_duration_{mode}_{stamp}_{run_idx:02d}.csv'
now_ts = int(time.time())
with out_path.open('w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['run_id', 'timestamp', 'metric', 'value', 'unit'])
    w.writerow([run_idx, now_ts, 'sla_violation_duration_s', f'{duration_s:.6f}', 's'])
    w.writerow([run_idx, now_ts, 'right_censored', right_censored, 'flag'])

print(f"E1 {mode.upper()} run {run_idx}: violation_duration={duration_s:.3f}s (right_censored={right_censored}) -> {out_path}")
PY
}

for ((r = 1; r <= RUNS; r++)); do
    echo "=== E1 ${MODE} run ${r}/${RUNS} ==="
    run_one "${r}"
done
