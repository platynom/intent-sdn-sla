#!/usr/bin/env bash
# Objective O3: Verify HTB queue binding (SET_QUEUE) vs unbound control under
# competing iperf3 cross-traffic on the 100 Mbit/s northern path (s1-s2-s3-s7).
set -euo pipefail

# Isolate measurement state from the automatically seeded dashboard database.
if [ -z "${TEAM16_DB_PATH:-}" ]; then
    export TEAM16_DB_PATH="$(mktemp -d /tmp/team16-o3.XXXXXX)/state.db"
fi

MODE="bound"
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
            echo "Usage: $0 [--mode bound|unbound] [--runs N]" >&2
            exit 2
            ;;
    esac
done

if [[ "${MODE}" != "bound" && "${MODE}" != "unbound" ]]; then
    echo "--mode must be bound or unbound" >&2
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
    local ryu_pid="" api_pid="" topo_pid="" srv1_pid="" srv2_pid="" cli1_pid="" cli2_pid=""
    cleanup_one() {
        for pid in "${cli1_pid}" "${cli2_pid}" "${srv1_pid}" "${srv2_pid}" "${topo_pid}" "${api_pid}" "${ryu_pid}"; do
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
conn.execute('DELETE FROM intents')
conn.commit()
conn.close()
"
    if [ "${MODE}" = "unbound" ]; then
        TEAM16_DISABLE_SET_QUEUE=1 ryu-manager --ofp-tcp-listen-port 6653 \
            src/enforcement/controller.py >"${LOG_DIR}/ryu-o3.log" 2>&1 &
    else
        ryu-manager --ofp-tcp-listen-port 6653 \
            src/enforcement/controller.py >"${LOG_DIR}/ryu-o3.log" 2>&1 &
    fi
    ryu_pid=$!
    sleep 2

    python3.9 -m uvicorn src.intent_manager.api:app \
        --host 127.0.0.1 --port 8000 >"${LOG_DIR}/api-o3.log" 2>&1 &
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
" >"${LOG_DIR}/topo-o3.log" 2>&1 &
    topo_pid=$!
    sleep 4

    # 1. Submit 20 Mbit/s SLA intent (INT-001, UDP dport 5001)
    local code1
    code1=$(curl -s -o /tmp/o3_post1.json -w "%{http_code}" -X POST \
        http://127.0.0.1:8000/intent -H "Content-Type: text/plain" \
        --data-binary "@intents/s1_urllc_baseline.yaml")
    if [ "${code1}" != "201" ]; then
        echo "FAIL: INT-001 returned ${code1}"
        exit 1
    fi
    sleep 2

    # Verify whether set_queue:1 is present on s1 as expected for the mode
    if [ "${MODE}" = "bound" ]; then
        if ! sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep -q "set_queue:1"; then
            echo "FAIL: set_queue:1 missing in bound mode on s1"
            sudo ovs-ofctl -O OpenFlow13 dump-flows s1
            exit 1
        fi
    else
        if sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep -q "set_queue:1"; then
            echo "FAIL: set_queue:1 unexpectedly present in unbound mode on s1"
            exit 1
        fi
    fi

    # Install best-effort forwarding rules (priority=50, no set_queue) along s1-s2-s3-s7
    # for competing cross-traffic (UDP 5201) and iperf3 TCP control channels.
    sudo ovs-ofctl -O OpenFlow13 add-flow s1 "priority=50,ip,nw_src=10.0.0.1,nw_dst=10.0.0.2,actions=output:2"
    sudo ovs-ofctl -O OpenFlow13 add-flow s2 "priority=50,ip,nw_src=10.0.0.1,nw_dst=10.0.0.2,actions=output:3"
    sudo ovs-ofctl -O OpenFlow13 add-flow s3 "priority=50,ip,nw_src=10.0.0.1,nw_dst=10.0.0.2,actions=output:3"
    sudo ovs-ofctl -O OpenFlow13 add-flow s7 "priority=50,ip,nw_src=10.0.0.1,nw_dst=10.0.0.2,actions=output:1"
    sudo ovs-ofctl -O OpenFlow13 add-flow s7 "priority=50,ip,nw_src=10.0.0.2,nw_dst=10.0.0.1,actions=output:3"
    sudo ovs-ofctl -O OpenFlow13 add-flow s3 "priority=50,ip,nw_src=10.0.0.2,nw_dst=10.0.0.1,actions=output:2"
    sudo ovs-ofctl -O OpenFlow13 add-flow s2 "priority=50,ip,nw_src=10.0.0.2,nw_dst=10.0.0.1,actions=output:2"
    sudo ovs-ofctl -O OpenFlow13 add-flow s1 "priority=50,ip,nw_src=10.0.0.2,nw_dst=10.0.0.1,actions=output:1"

    local h1_pid h2_pid
    h1_pid=$(cat /var/run/team16/h1.pid)
    h2_pid=$(cat /var/run/team16/h2.pid)

    # Orphan host socket skbs at the h1-eth0 NIC boundary so switch s1 queues do not
    # couple back into h1 per-socket sk_wmem_alloc buffers across the veth pair.
    mnexec -a "${h1_pid}" tc qdisc replace dev h1-eth0 root netem delay 1ms limit 10000

    local intent_json="/tmp/o3_intent_${MODE}_${run_idx}.json"
    local cross_json="/tmp/o3_cross_${MODE}_${run_idx}.json"
    rm -f "${intent_json}" "${cross_json}"

    mnexec -da "${h2_pid}" iperf3 -s -p 5001 -1 > /dev/null 2>&1 &
    srv1_pid=$!
    mnexec -da "${h2_pid}" iperf3 -s -p 5201 -1 > /dev/null 2>&1 &
    srv2_pid=$!
    sleep 0.5

    # Launch competing 150 Mbit/s UDP cross-traffic on port 5201 and 25 Mbit/s SLA intent traffic on port 5001
    mnexec -da "${h1_pid}" iperf3 -c 10.0.0.2 -p 5201 -u -b 150M -t 5 -J > "${cross_json}" 2>&1 &
    cli2_pid=$!
    mnexec -da "${h1_pid}" iperf3 -c 10.0.0.2 -p 5001 -u -b 25M -t 5 -J > "${intent_json}" 2>&1 &
    cli1_pid=$!

    wait "${cli1_pid}" || true
    wait "${cli2_pid}" || true
    wait "${srv1_pid}" || true
    wait "${srv2_pid}" || true
    cli1_pid=""
    cli2_pid=""
    srv1_pid=""
    srv2_pid=""

    python3.9 - "${MODE}" "${run_idx}" "${intent_json}" "${cross_json}" <<'PY'
import csv
import json
import os
import sys
import time
from pathlib import Path

mode = sys.argv[1]
run_idx = int(sys.argv[2])
intent_data = json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
cross_data = json.loads(Path(sys.argv[4]).read_text(encoding='utf-8'))

def rx_mbps_and_loss(data: dict) -> tuple[float, float]:
    end = data['end']
    if 'sum_received' in end and end['sum_received'].get('bits_per_second', 0) > 0:
        rx_bps = float(end['sum_received']['bits_per_second'])
        loss_pct = float(end.get('sum', {}).get('lost_percent', 0.0))
        return rx_bps / 1e6, loss_pct
    s = end['sum']
    tx_bps = float(s['bits_per_second'])
    loss_pct = float(s.get('lost_percent', 0.0))
    rx_bps = tx_bps * max(0.0, (100.0 - loss_pct) / 100.0)
    return rx_bps / 1e6, loss_pct

intent_mbps, intent_loss = rx_mbps_and_loss(intent_data)
cross_mbps, cross_loss = rx_mbps_and_loss(cross_data)

out_dir = Path(os.environ.get('O3_RAW_DIR', 'experiments/results/raw'))
out_dir.mkdir(parents=True, exist_ok=True)
stamp = time.strftime('%Y%m%d%H%M%S')
prefix = os.environ.get('O3_RESULT_PREFIX', 'o3_queue')
out_path = out_dir / f'{prefix}_{mode}_{stamp}_{run_idx:02d}.csv'
now_ts = int(time.time())
with out_path.open('w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['run_id', 'timestamp', 'metric', 'value', 'unit'])
    w.writerow([run_idx, now_ts, 'intent_throughput_mbps', f'{intent_mbps:.6f}', 'Mbps'])
    w.writerow([run_idx, now_ts, 'intent_loss_pct', f'{intent_loss:.6f}', 'pct'])
    w.writerow([run_idx, now_ts, 'cross_traffic_throughput_mbps', f'{cross_mbps:.6f}', 'Mbps'])
    w.writerow([run_idx, now_ts, 'cross_traffic_loss_pct', f'{cross_loss:.6f}', 'pct'])

print(f"O3 {mode.upper()} run {run_idx}: intent={intent_mbps:.3f} Mbps (loss={intent_loss:.2f}%), cross={cross_mbps:.3f} Mbps (loss={cross_loss:.2f}%) -> {out_path}")
PY
}

for ((r = 1; r <= RUNS; r++)); do
    echo "=== O3 ${MODE} run ${r}/${RUNS} ==="
    run_one "${r}"
done
