#!/usr/bin/env bash
# Objective O4 (E5): Flow-table entries and concurrent reconfiguration packet loss
# across all_strict, selective (50/50 strict/relaxed), and all_relaxed modes.
set -euo pipefail

MODE="all_strict"
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
            echo "Usage: $0 [--mode all_strict|selective|all_relaxed] [--runs N]" >&2
            exit 2
            ;;
    esac
done

if [[ "${MODE}" != "all_strict" && "${MODE}" != "selective" && "${MODE}" != "all_relaxed" ]]; then
    echo "--mode must be all_strict, selective, or all_relaxed" >&2
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
    local ryu_pid="" api_pid="" topo_pid="" poll_pid=""
    local rx_pids=() tx_pids=()
    cleanup_one() {
        for pid in "${tx_pids[@]:-}" "${rx_pids[@]:-}" "${poll_pid:-}" "${topo_pid:-}" "${api_pid:-}" "${ryu_pid:-}"; do
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
conn.execute(\"DELETE FROM events WHERE intent_id LIKE 'INT-50%'\")
conn.commit()
conn.close()
"
    local run_start
    run_start=$(python3.9 -c 'import time; print(time.time())')

    ryu-manager --ofp-tcp-listen-port 6653 \
        src/enforcement/controller.py >"${LOG_DIR}/ryu-e5.log" 2>&1 &
    ryu_pid=$!
    sleep 2

    python3.9 -m uvicorn src.intent_manager.api:app \
        --host 127.0.0.1 --port 8000 >"${LOG_DIR}/api-e5.log" 2>&1 &
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
" >"${LOG_DIR}/topo-e5.log" 2>&1 &
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
            echo "FAIL: switch ${sw} did not receive table-miss rule from Ryu"
            exit 1
        fi
    done

    local netem_parent
    netem_parent=$(sudo tc qdisc show dev s1-eth2 \
        | awk '/netem/ {for (i=1; i<=NF; i++) if ($i == "parent") {print $(i+1); exit}}')
    if [ -z "${netem_parent}" ]; then
        echo "FAIL: no primary-path netem qdisc found on s1-eth2"
        exit 1
    fi
    sudo tc qdisc change dev s1-eth2 parent "${netem_parent}" netem delay 40ms

    # Submit 4 intents (INT-E5-1..4 on UDP ports 5001..5004)
    for i in 1 2 3 4; do
        local consistency="strict"
        if [ "${MODE}" = "all_relaxed" ]; then
            consistency="relaxed"
        elif [ "${MODE}" = "selective" ] && [ "${i}" -ge 3 ]; then
            consistency="relaxed"
        fi
        local dport=$((5000 + i))
        local yaml_body
        yaml_body=$(cat <<EOF
intent:
  id: INT-50${i}
  tenant: eval-e5
  priority: 3
  match:
    src: 10.0.0.1/32
    dst: 10.0.0.2/32
    proto: udp
    dport: ${dport}
  guarantee:
    max_latency_ms: 35
  consistency: ${consistency}
  on_violation: reroute
EOF
)
        local code
        code=$(curl -s -o "/tmp/e5_post_${i}.json" -w "%{http_code}" -X POST \
            http://127.0.0.1:8000/intent -H "Content-Type: text/plain" \
            --data-binary "${yaml_body}")
        if [ "${code}" != "201" ]; then
            echo "FAIL: INT-50${i} returned ${code}"
            exit 1
        fi
    done

    local active_ok=0
    for _ in $(seq 1 40); do
        active_ok=$(python3.9 -c "
from src.common import db
conn = db.connect()
cnt = conn.execute(\"SELECT COUNT(*) FROM intents WHERE state = 'active'\").fetchone()[0]
print(1 if cnt == 4 else 0)
conn.close()")
        if [ "${active_ok}" = "1" ]; then
            break
        fi
        sleep 0.2
    done
    if [ "${active_ok}" != "1" ]; then
        echo "FAIL: not all 4 intents reached active state"
        exit 1
    fi
    sleep 0.5

    local h1_pid h2_pid
    h1_pid=$(cat /var/run/team16/h1.pid)
    h2_pid=$(cat /var/run/team16/h2.pid)

    for i in 1 2 3 4; do
        local dport=$((5000 + i))
        rm -f "/tmp/e5_tx_${MODE}_${run_idx}_${i}.csv" "/tmp/e5_rx_${MODE}_${run_idx}_${i}.csv"
        mnexec -da "${h2_pid}" python3.9 experiments/scenarios/udp_seq_probe.py recv \
            --bind 10.0.0.2 --port "${dport}" --duration 9.0 \
            --out "/tmp/e5_rx_${MODE}_${run_idx}_${i}.csv" &
        rx_pids+=("$!")
    done
    sleep 0.3
    for i in 1 2 3 4; do
        local dport=$((5000 + i))
        mnexec -da "${h1_pid}" python3.9 experiments/scenarios/udp_seq_probe.py send \
            --dst 10.0.0.2 --port "${dport}" --rate 250 --size 64 --duration 8.0 \
            --out "/tmp/e5_tx_${MODE}_${run_idx}_${i}.csv" &
        tx_pids+=("$!")
    done

    # Wait 2.5s so [fault_inject - 2 s] is inside the steady stream
    sleep 2.5

    local poll_json="/tmp/e5_poll_${MODE}_${run_idx}.json"
    rm -f "${poll_json}"
    # Start <=50 ms (20 ms interval) flow-table poller across s1..s7
    python3.9 - "${poll_json}" <<'PY' &
import json
import subprocess
import sys
import time
from pathlib import Path

out_path = Path(sys.argv[1])
switches = ["s1", "s2", "s3", "s4", "s5", "s6", "s7"]
peak_per_switch = {sw: 0 for sw in switches}
peak_total = 0
samples = 0
deadline = time.perf_counter() + 2.0

while time.perf_counter() < deadline:
    t0 = time.perf_counter()
    snap_total = 0
    for sw in switches:
        res = subprocess.run(
            ["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", sw],
            capture_output=True,
            text=True,
            check=False,
        )
        count = sum(1 for line in res.stdout.splitlines() if "cookie=" in line)
        if count > peak_per_switch[sw]:
            peak_per_switch[sw] = count
        snap_total += count
    if snap_total > peak_total:
        peak_total = snap_total
    samples += 1
    elapsed = time.perf_counter() - t0
    rem = 0.040 - elapsed
    if rem > 0:
        time.sleep(rem)

out_path.write_text(
    json.dumps({
        "peak_per_switch": peak_per_switch,
        "peak_total": peak_total,
        "samples": samples,
    }, indent=2) + "\n",
    encoding="utf-8",
)
PY
    poll_pid=$!
    sleep 0.2

    local fault_inject_at
    fault_inject_at=$(python3.9 -c 'import time; print(time.time())')

    # Inject simultaneous link-breach violation for all 4 intents sharing s1-s2
    python3.9 -c "
from src.common import db
from src.common.events import sla_violated
conn = db.connect()
for i in (1, 2, 3, 4):
    db.save_event(conn, sla_violated(f'INT-50{i}', 'delay_ms', 51.0, 35.0))
conn.close()
"

    # Wait for all 4 intents to move to s1,s4,s5,s7
    local all_moved=0
    for _ in $(seq 1 40); do
        all_moved=$(python3.9 -c "
from src.common import db
conn = db.connect()
ok = all(
    (db.current_path(conn, f'INT-50{i}') is not None and tuple(db.current_path(conn, f'INT-50{i}').switches) == ('s1', 's4', 's5', 's7'))
    for i in (1, 2, 3, 4)
)
print(1 if ok else 0)
conn.close()")
        if [ "${all_moved}" = "1" ]; then
            break
        fi
        sleep 0.2
    done
    if [ "${all_moved}" != "1" ]; then
        echo "FAIL: not all 4 intents moved to alternate route"
        exit 1
    fi

    wait "${poll_pid}" || true
    poll_pid=""
    for pid in "${tx_pids[@]}"; do
        wait "${pid}" || true
    done
    for pid in "${rx_pids[@]}"; do
        wait "${pid}" || true
    done
    tx_pids=()
    rx_pids=()

    python3.9 - "${MODE}" "${run_idx}" "${run_start}" "${fault_inject_at}" "${poll_json}" <<'PY'
import csv
import json
import os
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
poll_data = json.loads(Path(sys.argv[5]).read_text(encoding='utf-8'))

conn = db.connect()
installed_times = []
for i in (1, 2, 3, 4):
    events = [e for e in db.events_for(conn, f'INT-50{i}') if e.at >= run_start]
    installs = [
        e for e in events
        if e.type is EventType.PATH_INSTALLED
        and e.at >= fault_inject_at
        and {'measurement', 'threshold', 'decision', 'action'} <= set(e.payload)
    ]
    assert installs, f'No causal PATH_INSTALLED for INT-50{i}'
    installed_times.append(min(installs, key=lambda e: e.at).at)
conn.close()

path_installed_at = max(installed_times)
window_start = fault_inject_at - 2.0
window_end = path_installed_at + 2.0

total_sent = 0
total_recv = 0
total_lost = 0
total_dup = 0
total_reord = 0
lost_strict = 0
lost_relaxed = 0

for i in (1, 2, 3, 4):
    tx_log = Path(f'/tmp/e5_tx_{mode}_{run_idx}_{i}.csv')
    rx_log = Path(f'/tmp/e5_rx_{mode}_{run_idx}_{i}.csv')
    st = analyze_window(tx_log, rx_log, window_start, window_end)
    total_sent += st['packets_sent']
    total_recv += st['packets_received']
    total_lost += st['packets_lost']
    total_dup += st['packets_duplicated']
    total_reord += st['packets_reordered']
    is_strict = (mode == 'all_strict') or (mode == 'selective' and i <= 2)
    if is_strict:
        lost_strict += st['packets_lost']
    else:
        lost_relaxed += st['packets_lost']

peak_per_sw = poll_data['peak_per_switch']
peak_max_sw = max(peak_per_sw.values())
peak_total = poll_data['peak_total']
steady_max_sw = 6  # 1 table-miss + 4 forward rules + 1 reverse rule

out_dir = Path(os.environ.get('E5_RAW_DIR', 'experiments/results/raw'))
out_dir.mkdir(parents=True, exist_ok=True)
stamp = time.strftime('%Y%m%d%H%M%S')
out_path = out_dir / f'e5_{mode}_{stamp}_{run_idx:02d}.csv'
now_ts = int(time.time())
with out_path.open('w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['run_id', 'timestamp', 'metric', 'value', 'unit'])
    w.writerow([run_idx, now_ts, 'peak_rules_max_switch', peak_max_sw, 'entries'])
    w.writerow([run_idx, now_ts, 'peak_rules_total', peak_total, 'entries'])
    w.writerow([run_idx, now_ts, 'rule_overhead_max_switch', peak_max_sw - steady_max_sw, 'entries'])
    for sw, cnt in sorted(peak_per_sw.items()):
        w.writerow([run_idx, now_ts, f'peak_rules_{sw}', cnt, 'entries'])
    w.writerow([run_idx, now_ts, 'packets_lost', total_lost, 'packets'])
    w.writerow([run_idx, now_ts, 'packets_lost_strict_intents', lost_strict, 'packets'])
    w.writerow([run_idx, now_ts, 'packets_lost_relaxed_intents', lost_relaxed, 'packets'])
    w.writerow([run_idx, now_ts, 'packets_sent', total_sent, 'packets'])
    w.writerow([run_idx, now_ts, 'packets_reordered', total_reord, 'packets'])

print(f"E5 {mode.upper()} run {run_idx}: peak_max_sw={peak_max_sw} peak_total={peak_total} lost={total_lost} (strict_lost={lost_strict}, relaxed_lost={lost_relaxed}) -> {out_path}")
PY
}

for ((r = 1; r <= RUNS; r++)); do
    echo "=== E5 ${MODE} run ${r}/${RUNS} ==="
    run_one "${r}"
done
