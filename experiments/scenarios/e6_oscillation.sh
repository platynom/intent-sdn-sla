#!/usr/bin/env bash
# Objective O5 (E6): Live route oscillation over 10-minute (600 s) runs on S6
# (intents/s6_oscillation_trap.yaml), comparing hysteresis+dwell OFF (B2) vs ON (B3).
set -euo pipefail

MODE="b2"
RUNS=3
DURATION_S=600
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
        --duration)
            DURATION_S="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--mode b2|b3] [--runs N] [--duration SEC]" >&2
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
# Keep automatic dashboard seeding out of this measurement process tree.
E6_DB_DIR=$(mktemp -d /tmp/team16-e6.XXXXXX)
export TEAM16_DB_PATH="${E6_DB_DIR}/state.db"

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
    local ryu_pid="" api_pid="" topo_pid="" echo_pid="" fault_pid="" telem_pid=""
    cleanup_one() {
        for pid in "${telem_pid:-}" "${fault_pid:-}" "${echo_pid:-}" "${topo_pid:-}" "${api_pid:-}" "${ryu_pid:-}"; do
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
        src/enforcement/controller.py >"${LOG_DIR}/ryu-e6.log" 2>&1 &
    ryu_pid=$!
    sleep 2

    python3.9 -m uvicorn src.intent_manager.api:app \
        --host 127.0.0.1 --port 8000 >"${LOG_DIR}/api-e6.log" 2>&1 &
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
time.sleep(900)
net.stop()
" >"${LOG_DIR}/topo-e6.log" 2>&1 &
    topo_pid=$!
    sleep 4

    # Make the middle route (s1-s4-s5-s7) near-equal in base RTT (~15 ms < 19.8 ms
    # recovery threshold for INT-006's 22 ms SLA) as specified by Scenario S6.
    for dev in s1-eth3 s4-eth2 s4-eth3 s5-eth2 s5-eth3 s7-eth4; do
        local np
        np=$(sudo tc qdisc show dev "${dev}" \
            | awk '/netem/ {for (i=1; i<=NF; i++) if ($i == "parent") {print $(i+1); exit}}')
        if [ -n "${np}" ]; then
            sudo tc qdisc change dev "${dev}" parent "${np}" netem delay 2.5ms
        fi
    done

    # Prepare S6 intent payload from intents/s6_oscillation_trap.yaml
    local s6_payload="/tmp/s6_${MODE}.yaml"
    if [ "${MODE}" = "b2" ]; then
        cp intents/s6_oscillation_trap.yaml "${s6_payload}"
    else
        sed -e 's/dwell_seconds: 0/dwell_seconds: 10/' \
            -e 's/consistency: relaxed/consistency: strict/' \
            intents/s6_oscillation_trap.yaml > "${s6_payload}"
    fi

    local code
    code=$(curl -s -o /tmp/e6_post.json -w "%{http_code}" -X POST \
        http://127.0.0.1:8000/intent -H "Content-Type: text/plain" \
        --data-binary "@${s6_payload}")
    if [ "${code}" != "201" ]; then
        echo "FAIL: POST /intent for INT-006 returned ${code}"
        cat /tmp/e6_post.json || true
        exit 1
    fi
    sleep 2

    local h1_pid h2_pid
    h1_pid=$(cat /var/run/team16/h1.pid)
    h2_pid=$(cat /var/run/team16/h2.pid)

    # Start UDP echo responder on h2:5003 (INT-006 dport)
    mnexec -da "${h2_pid}" python3.9 -u -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('10.0.0.2', 5003))
while True:
    data, addr = s.recvfrom(64)
    s.sendto(data, addr)
" >"${LOG_DIR}/e6-echo.log" 2>&1 &
    echo_pid=$!
    sleep 0.5

    # Background alternating fault injector on the active path (s1-eth2 vs s1-eth3)
    python3.9 - "${DURATION_S}" <<'PY' &
import subprocess
import sys
import time
from src.common import db

duration_s = int(sys.argv[1])

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
north_devs = ("s1-eth2", "s2-eth2", "s2-eth3", "s3-eth2", "s3-eth3", "s7-eth3")
mid_devs = ("s1-eth3", "s4-eth2", "s4-eth3", "s5-eth2", "s5-eth3", "s7-eth4")
all_devs = north_devs + mid_devs
dev_parents = {d: get_parent(d) for d in all_devs}

def set_delays(north_ms: float, mid_ms: float) -> None:
    subprocess.run(
        ["tc", "qdisc", "change", "dev", "s1-eth2", "parent", p_north, "netem", "delay", f"{north_ms}ms"],
        check=False,
    )
    subprocess.run(
        ["tc", "qdisc", "change", "dev", "s1-eth3", "parent", p_mid, "netem", "delay", f"{mid_ms}ms"],
        check=False,
    )

def set_all_healthy(fast: bool = False) -> None:
    for d in all_devs:
        ms = 0.2 if fast else (2.0 if d in north_devs else 2.5)
        subprocess.run(
            ["tc", "qdisc", "change", "dev", d, "parent", dev_parents[d], "netem", "delay", f"{ms}ms"],
            check=False,
        )

def active_is_north() -> bool:
    conn = db.connect()
    cur = db.current_path(conn, "INT-006")
    conn.close()
    return cur is None or ("s2" in cur.switches)

def spike_active(spike_ms: float) -> None:
    set_all_healthy(fast=False)
    if active_is_north():
        set_delays(spike_ms, 2.5)
    else:
        set_delays(2.0, spike_ms)

start = time.perf_counter()
# Initial 2.0 s healthy warm-up so telemetry seeds EWMA on baseline RTT
set_all_healthy(fast=False)
time.sleep(min(2.0, float(duration_s)))

while time.perf_counter() - start < duration_s:
    cycle_start = time.perf_counter()
    # Phase 1 (0..4.2 s): sustained breach (+30 ms -> ~43 ms RTT)
    spike_active(30.0)
    time.sleep(4.2)
    if time.perf_counter() - start >= duration_s:
        break

    # Phase 2 (4.2..7.5 s): fast recovery so EWMA clears hysteresis (<19.8 ms)
    set_all_healthy(fast=True)
    time.sleep(3.3)
    if time.perf_counter() - start >= duration_s:
        break

    # Phase 3 (7.5..10.5 s): secondary breach inside 10s dwell window
    spike_active(45.0)
    time.sleep(3.0)

    # Phase 4 (10.5..15.0 s): recovery before 10s dwell expires
    set_all_healthy(fast=True)
    time.sleep(4.5)
    if time.perf_counter() - start >= duration_s:
        break

    # Phase 5 (15.0..16.5 s): isolated 1-sample spike (+18 ms -> ~31 ms RTT)
    spike_active(18.0)
    time.sleep(1.5)
    if time.perf_counter() - start >= duration_s:
        break

    # Phase 6 (16.5..20.0 s): healthy baseline remainder of 20s macro-cycle
    set_all_healthy(fast=False)
    elapsed = time.perf_counter() - cycle_start
    rem = max(0.0, min(20.0 - elapsed, duration_s - (time.perf_counter() - start)))
    if rem > 0:
        time.sleep(rem)

set_all_healthy(fast=False)
PY
    fault_pid=$!

    local detector_args=()
    if [ "${MODE}" = "b2" ]; then
        detector_args=(--ewma-alpha 1.0 --hysteresis-pct 0.0 --consecutive-required 1)
    else
        detector_args=(--ewma-alpha 0.3 --hysteresis-pct 0.1 --consecutive-required 3)
    fi

    python3.9 -m src.telemetry.runtime \
        --intent INT-006 --source-pid "${h1_pid}" --target 10.0.0.2 --port 5003 \
        --switch s1 --samples "${DURATION_S}" --interval 1.0 "${detector_args[@]}" \
        >"${LOG_DIR}/telemetry-e6-${MODE}-${run_idx}.log" 2>&1 &
    telem_pid=$!

    wait "${telem_pid}"
    telem_pid=""
    if [ -n "${fault_pid}" ] && kill -0 "${fault_pid}" 2>/dev/null; then
        kill "${fault_pid}" 2>/dev/null || true
        wait "${fault_pid}" 2>/dev/null || true
    elif [ -n "${fault_pid}" ]; then
        wait "${fault_pid}"
    fi
    fault_pid=""
    sleep 1

    python3.9 - "${MODE}" "${run_idx}" "${run_start}" "${DURATION_S}" <<'PY'
import csv
import os
import sys
import time
from pathlib import Path
from src.common import db
from src.common.events import EventType

mode = sys.argv[1]
run_idx = int(sys.argv[2])
run_start = float(sys.argv[3])
duration_s = float(sys.argv[4])

conn = db.connect()
reroutes = db.reroute_count(conn, 'INT-006')
# Count the complete durable run directly. A dashboard history page is bounded
# and must not be used as an experiment's event-accounting source.
counts = dict(conn.execute(
    'SELECT type, COUNT(*) FROM events WHERE intent_id = ? AND at >= ? GROUP BY type',
    ('INT-006', run_start),
).fetchall())
violations = counts.get(EventType.SLA_VIOLATED.value, 0)
restorations = counts.get(EventType.SLA_RESTORED.value, 0)
suppressions = counts.get(EventType.VIOLATION_SUPPRESSED.value, 0)
sample_count = conn.execute(
    'SELECT COUNT(*) FROM measurements WHERE intent_id = ? AND at >= ?',
    ('INT-006', run_start),
).fetchone()[0]
if sample_count != int(duration_s):
    raise RuntimeError(f'incomplete telemetry: {sample_count} of {int(duration_s)} samples')
if mode == 'b2' and reroutes != violations:
    raise RuntimeError(f'event accounting mismatch: {reroutes} reroutes, {violations} violations')
conn.close()

reroutes_per_10min = reroutes * (600.0 / duration_s)

out_dir = Path(os.environ.get('E6_RAW_DIR', 'experiments/results/raw'))
out_dir.mkdir(parents=True, exist_ok=True)
stamp = time.strftime('%Y%m%d%H%M%S')
prefix = os.environ.get('E6_RESULT_PREFIX', 'e6_oscillation')
out_path = out_dir / f'{prefix}_{mode}_{stamp}_{run_idx:02d}.csv'
now_ts = int(time.time())
with out_path.open('w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['run_id', 'timestamp', 'metric', 'value', 'unit'])
    w.writerow([run_idx, now_ts, 'reroute_count_10min', f'{reroutes_per_10min:.6f}', 'count_per_10min'])
    w.writerow([run_idx, now_ts, 'raw_reroute_count', reroutes, 'count'])
    w.writerow([run_idx, now_ts, 'violations_emitted', violations, 'count'])
    w.writerow([run_idx, now_ts, 'restorations_emitted', restorations, 'count'])
    w.writerow([run_idx, now_ts, 'dwell_suppressions', suppressions, 'count'])
    w.writerow([run_idx, now_ts, 'duration_s', f'{duration_s:.1f}', 's'])
    w.writerow([run_idx, now_ts, 'measurement_count', sample_count, 'count'])

print(f"E6 {mode.upper()} run {run_idx}: reroutes_10min={reroutes_per_10min:.2f} (raw={reroutes}, violations={violations}, restorations={restorations}, suppressions={suppressions}) -> {out_path}")
PY
}

for ((r = 1; r <= RUNS; r++)); do
    echo "=== E6 ${MODE} run ${r}/${RUNS} (duration=${DURATION_S}s) ==="
    run_one "${r}"
done

echo "E6 durable accounting database retained at ${TEAM16_DB_PATH}"
