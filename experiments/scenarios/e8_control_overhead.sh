#!/usr/bin/env bash
# Objective O8 (E8): Control-plane overhead over a fixed 60 s window (B1 vs B3).
# Measures OpenFlow message rate (msgs/s on port 6653) and CPU for the full
# control stack over the same window.  The v1 experiment sampled only the
# ryu-manager PID.  v2 records Ryu, API, telemetry runtime, active-probe
# responder, and their descendants separately, plus their summed total.
set -euo pipefail

# Isolate measurement state from the automatically seeded dashboard database.
if [ -z "${TEAM16_DB_PATH:-}" ]; then
    export TEAM16_DB_PATH="$(mktemp -d /tmp/team16-e8.XXXXXX)/state.db"
fi

MODE="b1"
RUNS=10
WINDOW_S=60
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
        --window)
            WINDOW_S="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--mode b1|b3] [--runs N] [--window SEC]" >&2
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
    local ryu_pid="" api_pid="" topo_pid="" echo_pid="" pcap_pid="" workload_pid="" telemetry_pid=""
    cleanup_one() {
        for pid in "${telemetry_pid:-}" "${workload_pid:-}" "${pcap_pid:-}" "${echo_pid:-}" "${topo_pid:-}" "${api_pid:-}" "${ryu_pid:-}"; do
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
    ryu-manager --ofp-tcp-listen-port 6653 \
        src/enforcement/controller.py >"${LOG_DIR}/ryu-e8.log" 2>&1 &
    ryu_pid=$!
    sleep 2

    python3.9 -m uvicorn src.intent_manager.api:app \
        --host 127.0.0.1 --port 8000 >"${LOG_DIR}/api-e8.log" 2>&1 &
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
" >"${LOG_DIR}/topo-e8.log" 2>&1 &
    topo_pid=$!
    sleep 4

    local intent_file="intents/s1_urllc_baseline.yaml"
    if [ "${MODE}" = "b3" ]; then
        intent_file="experiments/scenarios/fixtures/b3_single_intent.yaml"
        for dev in s1-eth3 s4-eth2 s4-eth3 s5-eth2 s5-eth3 s7-eth4; do
            local np
            np=$(sudo tc qdisc show dev "${dev}" \
                | awk '/netem/ {for (i=1; i<=NF; i++) if ($i == "parent") {print $(i+1); exit}}')
            if [ -n "${np}" ]; then
                sudo tc qdisc change dev "${dev}" parent "${np}" netem delay 1ms
            fi
        done
    fi
    local code
    code=$(curl -s -o /tmp/e8_post.json -w "%{http_code}" -X POST \
        http://127.0.0.1:8000/intent -H "Content-Type: text/plain" \
        --data-binary "@${intent_file}")
    if [ "${code}" != "201" ]; then
        echo "FAIL: POST /intent returned ${code}"
        exit 1
    fi
    sleep 2

    local h1_pid h2_pid
    h1_pid=$(cat /var/run/team16/h1.pid)
    h2_pid=$(cat /var/run/team16/h2.pid)

    local pcap_file="/tmp/e8_${MODE}_${run_idx}.pcap"
    rm -f "${pcap_file}"
    tcpdump -i lo -nn -U -w "${pcap_file}" "tcp port 6653 and (tcp[tcpflags] & tcp-push != 0)" >/dev/null 2>&1 &
    pcap_pid=$!
    sleep 0.3

    if [ "${MODE}" = "b1" ]; then
        # B1 open-loop: no telemetry polling or closed-loop adaptation during the 60 s window
        :
    else
        # B3 closed-loop: active 1 Hz telemetry + periodic fault/recovery triggers over the 60 s window
        mnexec -da "${h2_pid}" python3.9 -u -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('10.0.0.2', 5001))
while True:
    data, addr = s.recvfrom(64)
    s.sendto(data, addr)
" >"${LOG_DIR}/e8-echo.log" 2>&1 &
        echo_pid=$!

        python3.9 - "${WINDOW_S}" <<'PY' &
import subprocess
import sys
import time
window_s = int(sys.argv[1])
def get_parent(dev: str) -> str:
    out = subprocess.check_output(["tc", "qdisc", "show", "dev", dev], text=True)
    for line in out.splitlines():
        if "netem" in line:
            parts = line.split()
            for idx, tok in enumerate(parts):
                if tok == "parent" and idx + 1 < len(parts):
                    return parts[idx + 1]
    raise RuntimeError(f"No netem parent on {dev}")

p_north = get_parent("s1-eth2")
p_mid = get_parent("s1-eth3")
start = time.perf_counter()
step = 0
while time.perf_counter() - start < window_s:
    step += 1
    if step % 2 == 1:
        subprocess.run(["tc", "qdisc", "change", "dev", "s1-eth2", "parent", p_north, "netem", "delay", "40ms"], check=False)
        subprocess.run(["tc", "qdisc", "change", "dev", "s1-eth3", "parent", p_mid, "netem", "delay", "1ms"], check=False)
    else:
        subprocess.run(["tc", "qdisc", "change", "dev", "s1-eth2", "parent", p_north, "netem", "delay", "2ms"], check=False)
        subprocess.run(["tc", "qdisc", "change", "dev", "s1-eth3", "parent", p_mid, "netem", "delay", "40ms"], check=False)
    time.sleep(5.0)
    subprocess.run(["tc", "qdisc", "change", "dev", "s1-eth2", "parent", p_north, "netem", "delay", "2ms"], check=False)
    subprocess.run(["tc", "qdisc", "change", "dev", "s1-eth3", "parent", p_mid, "netem", "delay", "1ms"], check=False)
    rem = min(10.0, max(0.0, window_s - (time.perf_counter() - start)))
    if rem > 0:
        time.sleep(rem)
PY
        workload_pid=$!

        # Keep telemetry alive slightly beyond the measurement window so its
        # final /proc counters (including reaped probe children) remain readable.
        python3.9 -m src.telemetry.runtime \
            --intent INT-001 --source-pid "${h1_pid}" --target 10.0.0.2 --port 5001 \
            --switch s1 --samples "$((WINDOW_S + 5))" --interval 1.0 \
            >"${LOG_DIR}/telemetry-e8-${run_idx}.log" 2>&1 &
        telemetry_pid=$!
    fi

    local cpu_start_info cpu_end_info
    cpu_start_info=$(python3.9 experiments/process_cpu.py \
        --component "ryu=${ryu_pid}" --component "api=${api_pid}" \
        --component "telemetry=${telemetry_pid:-0}" --component "probe=${echo_pid:-0}")
    sleep "${WINDOW_S}"
    cpu_end_info=$(python3.9 experiments/process_cpu.py \
        --component "ryu=${ryu_pid}" --component "api=${api_pid}" \
        --component "telemetry=${telemetry_pid:-0}" --component "probe=${echo_pid:-0}")

    if [ "${MODE}" = "b3" ]; then
        if [ -n "${workload_pid}" ] && kill -0 "${workload_pid}" 2>/dev/null; then
            kill "${workload_pid}" 2>/dev/null || true
            wait "${workload_pid}" 2>/dev/null || true
        fi
        workload_pid=""
        if [ -n "${telemetry_pid}" ] && kill -0 "${telemetry_pid}" 2>/dev/null; then
            kill "${telemetry_pid}" 2>/dev/null || true
            wait "${telemetry_pid}" 2>/dev/null || true
        fi
        telemetry_pid=""
    fi

    if [ -n "${pcap_pid}" ] && kill -0 "${pcap_pid}" 2>/dev/null; then
        kill "${pcap_pid}" 2>/dev/null || true
        wait "${pcap_pid}" 2>/dev/null || true
    fi
    pcap_pid=""

    local of_packets
    of_packets=$(tcpdump -r "${pcap_file}" -nn 2>/dev/null | wc -l || echo 0)

    python3.9 - "${MODE}" "${run_idx}" "${cpu_start_info}" "${cpu_end_info}" "${of_packets}" <<'PY'
import csv
import json
import os
import sys
import time
from pathlib import Path

mode = sys.argv[1]
run_idx = int(sys.argv[2])
start = json.loads(sys.argv[3])
end = json.loads(sys.argv[4])
of_packets = int(sys.argv[5])

clk = float(start["clock_ticks_per_s"])
elapsed_s = max(0.001, float(end["monotonic_s"]) - float(start["monotonic_s"]))
cpu_pct = {}
for component in ("ryu", "api", "telemetry", "probe"):
    delta = max(0, int(end["components"].get(component, 0)) - int(start["components"].get(component, 0)))
    cpu_pct[component] = ((delta / clk) / elapsed_s) * 100.0
total_cpu_pct = sum(cpu_pct.values())
msgs_per_s = of_packets / elapsed_s

out_dir = Path(os.environ.get('E8_RAW_DIR', 'experiments/results/raw'))
out_dir.mkdir(parents=True, exist_ok=True)
stamp = time.strftime('%Y%m%d%H%M%S')
out_path = out_dir / f'e8v2_overhead_{mode}_{stamp}_{run_idx:02d}.csv'
now_ts = int(time.time())
with out_path.open('w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['run_id', 'timestamp', 'metric', 'value', 'unit'])
    w.writerow([run_idx, now_ts, 'openflow_msgs_per_s', f'{msgs_per_s:.6f}', 'msgs_per_s'])
    w.writerow([run_idx, now_ts, 'ryu_cpu_pct', f'{cpu_pct["ryu"]:.6f}', 'pct'])
    w.writerow([run_idx, now_ts, 'api_cpu_pct', f'{cpu_pct["api"]:.6f}', 'pct'])
    w.writerow([run_idx, now_ts, 'telemetry_cpu_pct', f'{cpu_pct["telemetry"]:.6f}', 'pct'])
    w.writerow([run_idx, now_ts, 'probe_cpu_pct', f'{cpu_pct["probe"]:.6f}', 'pct'])
    w.writerow([run_idx, now_ts, 'control_stack_cpu_pct', f'{total_cpu_pct:.6f}', 'pct'])
    w.writerow([run_idx, now_ts, 'openflow_msgs_total', of_packets, 'count'])
    w.writerow([run_idx, now_ts, 'window_duration_s', f'{elapsed_s:.6f}', 's'])

print(
    f"E8v2 {mode.upper()} run {run_idx}: of_msgs_per_s={msgs_per_s:.3f} "
    f"(total={of_packets}), control_stack_cpu={total_cpu_pct:.3f}% "
    f"[ryu={cpu_pct['ryu']:.3f}, api={cpu_pct['api']:.3f}, "
    f"telemetry={cpu_pct['telemetry']:.3f}, probe={cpu_pct['probe']:.3f}] "
    f"(window={elapsed_s:.1f}s) -> {out_path}"
)
PY
}

for ((r = 1; r <= RUNS; r++)); do
    echo "=== E8 ${MODE} run ${r}/${RUNS} (window=${WINDOW_S}s) ==="
    run_one "${r}"
done
