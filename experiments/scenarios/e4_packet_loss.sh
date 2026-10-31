#!/usr/bin/env bash
# E4 packet loss during reconfiguration: sequence-numbered 1,000 pkt/s UDP stream
# across induced reroute in window [fault_inject - 2 s, path_installed + 2 s].
set -euo pipefail

MODE="b2"
RUNS=10
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
            echo "Usage: $0 [--mode b2|b3] [--runs N]" >&2
            exit 2
            ;;
    esac
done

if [[ "${MODE}" != "b2" && "${MODE}" != "b3" ]]; then
    echo "--mode must be b2 or b3" >&2
    exit 2
fi

LOG_DIR="/var/log/team16"
mkdir -p "${LOG_DIR}" /var/run/team16

clean_mininet() {
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
    local ryu_pid="" api_pid="" topo_pid="" rx_pid="" tx_pid=""
    cleanup_one() {
        for pid in "${tx_pid}" "${rx_pid}" "${topo_pid}" "${api_pid}" "${ryu_pid}"; do
            if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
                kill "${pid}" 2>/dev/null || true
                wait "${pid}" 2>/dev/null || true
            fi
        done
        clean_mininet
    }
    trap cleanup_one RETURN

    clean_mininet
    python3.9 -c "
from src.common import db
conn = db.connect()
db.init_db(conn)
conn.execute('DELETE FROM intents WHERE id = ?', ('INT-001',))
conn.commit()
conn.close()
"
    local run_start
    run_start=$(python3.9 -c 'import time; print(time.time())')

    ryu-manager --ofp-tcp-listen-port 6653 \
        src/enforcement/controller.py >"${LOG_DIR}/ryu-e4.log" 2>&1 &
    ryu_pid=$!
    sleep 2

    local intent_file="experiments/scenarios/fixtures/b2_single_intent.yaml"
    if [ "${MODE}" = "b3" ]; then
        intent_file="experiments/scenarios/fixtures/b3_single_intent.yaml"
        python3.9 -m uvicorn src.intent_manager.api:app \
            --host 127.0.0.1 --port 8000 >"${LOG_DIR}/api-e4.log" 2>&1 &
    else
        TEAM16_EXPERIMENT_MODE=b2 python3.9 -m uvicorn src.intent_manager.api:app \
            --host 127.0.0.1 --port 8000 >"${LOG_DIR}/api-e4.log" 2>&1 &
    fi
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
" >"${LOG_DIR}/topo-e4.log" 2>&1 &
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

    local http_code
    http_code=$(curl -s -o /tmp/e4_post.json -w "%{http_code}" -X POST \
        http://127.0.0.1:8000/intent -H "Content-Type: text/plain" \
        --data-binary "@${intent_file}")
    if [ "${http_code}" != "201" ]; then
        echo "FAIL: POST /intent returned ${http_code}"
        exit 1
    fi
    sleep 2

    local h1_pid h2_pid
    h1_pid=$(cat /var/run/team16/h1.pid)
    h2_pid=$(cat /var/run/team16/h2.pid)

    local tx_log="/tmp/e4_tx_${MODE}_${run_idx}.csv"
    local rx_log="/tmp/e4_rx_${MODE}_${run_idx}.csv"
    rm -f "${tx_log}" "${rx_log}"

    # Start receiver and 1,000 pkt/s sender on port 5001 (matched by INT-001)
    mnexec -da "${h2_pid}" python3.9 experiments/scenarios/udp_seq_probe.py recv \
        --bind 10.0.0.2 --port 5001 --duration 9.0 --out "${rx_log}" &
    rx_pid=$!
    sleep 0.3
    mnexec -da "${h1_pid}" python3.9 experiments/scenarios/udp_seq_probe.py send \
        --dst 10.0.0.2 --port 5001 --rate 1000 --size 64 --duration 8.0 --out "${tx_log}" &
    tx_pid=$!

    # Wait 2.5 seconds so [fault_inject - 2 s] is fully inside the steady stream
    sleep 2.5
    local fault_inject_at
    fault_inject_at=$(python3.9 -c 'import time; print(time.time())')

    # Inject the confirmed SLA violation to trigger immediate controller reroute
    python3.9 -c "
from src.common import db
from src.common.events import sla_violated
conn = db.connect()
db.save_event(conn, sla_violated('INT-001', 'delay_ms', 51.0, 35.0))
conn.close()
"

    # Wait for alternate route installation
    local alt_route=""
    for _ in $(seq 1 30); do
        alt_route=$(python3.9 -c "
from src.common import db
conn = db.connect()
p = db.current_path(conn, 'INT-001')
print(','.join(p.switches) if p else '')
conn.close()")
        if [ "${alt_route}" = "s1,s4,s5,s7" ]; then
            break
        fi
        sleep 0.2
    done
    if [ "${alt_route}" != "s1,s4,s5,s7" ]; then
        echo "FAIL: alternate route not installed (${alt_route})"
        exit 1
    fi

    # Wait for sender and receiver to finish their 8-9s window
    wait "${tx_pid}" || true
    wait "${rx_pid}" || true
    tx_pid=""
    rx_pid=""

    python3.9 - "${MODE}" "${run_idx}" "${run_start}" "${fault_inject_at}" "${tx_log}" "${rx_log}" <<'PY'
import csv
import sys
import time
from pathlib import Path
from src.common import db
from src.common.events import EventType
from experiments.scenarios.udp_seq_probe import analyze_window

mode = sys.argv[1]
run_idx = int(sys.argv[2])
run_start = float(sys.argv[3])
fault_inject_at = float(sys.argv[4])
tx_log = Path(sys.argv[5])
rx_log = Path(sys.argv[6])

conn = db.connect()
events = [e for e in db.events_for(conn, 'INT-001') if e.at >= run_start]
installs = [
    e for e in events
    if e.type is EventType.PATH_INSTALLED
    and e.at >= fault_inject_at
    and {'measurement', 'threshold', 'decision', 'action'} <= set(e.payload)
]
assert installs, 'No causal PATH_INSTALLED event found after fault injection'
path_installed_at = min(installs, key=lambda e: e.at).at
conn.close()

window_start = fault_inject_at - 2.0
window_end = path_installed_at + 2.0
stats = analyze_window(tx_log, rx_log, window_start, window_end)

import os
stamp = time.strftime('%Y%m%d%H%M%S')
out_dir = Path(os.environ.get('E4_RAW_DIR', 'experiments/results/raw'))
out_dir.mkdir(parents=True, exist_ok=True)
prefix = os.environ.get('E4_RESULT_PREFIX', 'e4')
out_path = out_dir / f'{prefix}_{mode}_reconfig_{stamp}_{run_idx:02d}.csv'
now_ts = int(time.time())
with out_path.open('w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['run_id', 'timestamp', 'metric', 'value', 'unit'])
    w.writerow([run_idx, now_ts, 'packets_sent', stats['packets_sent'], 'packets'])
    w.writerow([run_idx, now_ts, 'packets_received', stats['packets_received'], 'packets'])
    w.writerow([run_idx, now_ts, 'packets_lost', stats['packets_lost'], 'packets'])
    w.writerow([run_idx, now_ts, 'packets_duplicated', stats['packets_duplicated'], 'packets'])
    w.writerow([run_idx, now_ts, 'packets_reordered', stats['packets_reordered'], 'packets'])
    w.writerow([run_idx, now_ts, 'window_duration_s', f'{window_end - window_start:.6f}', 's'])
print(f"E4 {mode.upper()} run {run_idx}: sent={stats['packets_sent']} lost={stats['packets_lost']} dup={stats['packets_duplicated']} reord={stats['packets_reordered']} -> {out_path}")
PY
}

for ((r = 1; r <= RUNS; r++)); do
    echo "=== E4 ${MODE} run ${r}/${RUNS} ==="
    run_one "${r}"
done
