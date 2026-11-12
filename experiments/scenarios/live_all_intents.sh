#!/usr/bin/env bash
# Live Mininet/OVS measurement of every active intent, written to the dashboard DB.
#
# Starts Ryu (which installs all active intents from SQLite), builds the Team 16
# topology, offers real UDP load slightly above each intent's guaranteed rate,
# and runs one telemetry collector per intent in parallel. Results appear on the
# dashboard as LIVE TELEMETRY. Intents are not deleted afterwards.
#
# Usage (inside the SDN container):
#   bash experiments/scenarios/live_all_intents.sh [SAMPLES] [A B ACTION [VALUE]]
# Examples:
#   bash experiments/scenarios/live_all_intents.sh 120
#   bash experiments/scenarios/live_all_intents.sh 150 s2 s3 down       # fail s2-s3 after FAULT_AT s
#   bash experiments/scenarios/live_all_intents.sh 150 s1 s4 delay 40   # add 40 ms after FAULT_AT s
set -euo pipefail

SAMPLES="${1:-60}"
FAULT_ARGS=("${@:2}")
FAULT_AT="${FAULT_AT:-40}"
export TEAM16_DB_PATH="${TEAM16_DB_PATH:-/app/experiments/results/state.db}"
LOG_DIR="/var/log/team16"
RUN_DIR="/var/run/team16"
mkdir -p "${LOG_DIR}" "${RUN_DIR}"

# intent | src host | dst host | dst ip | udp port | egress switch | offered Mbit/s
# Offered rate is about 1.15-1.2 x the guarantee so the bandwidth check sits
# above the detector's recovery band; egress switch counts forward traffic.
INTENTS=(
  "INT-001 h1 h2 10.0.0.2 5001 s7 23"
  "INT-010 h1 h2 10.0.0.2 5601 s7 10"
  "INT-011 h3 h4 10.0.0.4 5602 s5 23"
  "INT-012 h5 h6 10.0.0.6 5603 s6 15"
  "INT-013 h7 h8 10.0.0.8 5604 s7 6"
)

PIDS=()
RYU_PID=""
TOPO_PID=""

clean_mininet() {
    timeout 15s python3.9 /usr/local/bin/mn -c >/dev/null 2>&1 || true
    for switch in s1 s2 s3 s4 s5 s6 s7; do
        if sudo ovs-dpctl show ovs-system 2>/dev/null \
            | grep -Eq "port [0-9]+: ${switch} \(internal\)"; then
            sudo ovs-dpctl del-if ovs-system "${switch}" >/dev/null 2>&1 || true
        fi
    done
}

cleanup() {
    echo "*** Stopping load, collectors, controller and Mininet"
    for pid in "${PIDS[@]}" "${TOPO_PID}" "${RYU_PID}"; do
        if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
            kill "${pid}" 2>/dev/null || true
        fi
    done
    clean_mininet
}
trap cleanup EXIT INT TERM

clean_mininet
RUN_STARTED_AT=$(python3.9 -c 'import time; print(time.time())')

echo "=== Checking active intents in ${TEAM16_DB_PATH} ==="
ACTIVE=()
for spec in "${INTENTS[@]}"; do
    read -r iid _ <<<"${spec}"
    state=$(python3.9 -c "
from src.common import db
c = db.connect(); r = db.load_intent(c, '${iid}'); print(r.state.value if r else 'missing'); c.close()")
    if [ "${state}" = "active" ] || [ "${state}" = "admitted" ] || [ "${state}" = "pending" ]; then
        ACTIVE+=("${spec}")
        echo "  ${iid}: ${state}"
    else
        echo "  ${iid}: ${state} (skipped)"
    fi
done
if [ "${#ACTIVE[@]}" -eq 0 ]; then
    echo "FAIL: no active intents to measure"
    exit 1
fi

echo "=== Starting Ryu controller (installs intents from the database) ==="
ryu-manager --ofp-tcp-listen-port 6653 src/enforcement/controller.py >"${LOG_DIR}/ryu-live-all.log" 2>&1 &
RYU_PID=$!
sleep 2

echo "=== Starting Mininet topology ==="
TOPO_SECONDS=$((SAMPLES + 120))
python3.9 -c "
import time
from pathlib import Path
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from topology.team16_topo import Team16Topo
net = Mininet(topo=Team16Topo(), switch=OVSSwitch, link=TCLink,
              controller=None, autoSetMacs=True, autoStaticArp=True)
net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)
net.start()
for host in net.hosts:
    (Path('${RUN_DIR}') / f'{host.name}.pid').write_text(str(host.pid))
time.sleep(${TOPO_SECONDS})
net.stop()
" >"${LOG_DIR}/topo-live-all.log" 2>&1 &
TOPO_PID=$!

echo "=== Waiting for the controller to install every intent ==="
for spec in "${ACTIVE[@]}"; do
    read -r iid _ _ _ _ egress _ <<<"${spec}"
    cookie=$(python3.9 -c "from src.enforcement.flowmod import cookie_for_intent; print(hex(cookie_for_intent('${iid}')))")
    ok=0
    for attempt in $(seq 1 60); do
        if sudo ovs-ofctl -O OpenFlow13 dump-flows "${egress}" 2>/dev/null | grep -q "cookie=${cookie},"; then
            ok=1; break
        fi
        sleep 1
    done
    if [ "${ok}" -eq 1 ]; then
        echo "PASS: ${iid} rules installed (egress ${egress})"
    else
        echo "FAIL: ${iid} rules not found on ${egress}; see ${LOG_DIR}/ryu-live-all.log"
        exit 1
    fi
done

echo "=== Starting probe echo servers and real UDP load ==="
LOAD_SECONDS=$((SAMPLES + 15))
for spec in "${ACTIVE[@]}"; do
    read -r iid src dst dst_ip port egress rate <<<"${spec}"
    src_pid=$(cat "${RUN_DIR}/${src}.pid")
    dst_pid=$(cat "${RUN_DIR}/${dst}.pid")
    mnexec -da "${dst_pid}" python3.9 -u scripts/udp_probe_echo.py "${dst_ip}" "${port}" \
        >"${LOG_DIR}/echo-${iid}.log" 2>&1 &
    PIDS+=("$!")
    sleep 0.3
    mnexec -da "${src_pid}" python3.9 -u scripts/udp_load.py "${dst_ip}" "${port}" "${rate}" "${LOAD_SECONDS}" \
        >"${LOG_DIR}/load-${iid}.log" 2>&1 &
    PIDS+=("$!")
    echo "  ${iid}: ${src} -> ${dst} udp/${port} at ${rate} Mbit/s"
done
sleep 3

echo "=== Collecting ${SAMPLES} live samples per intent (about ${SAMPLES} s) ==="
COLLECTORS=()
for spec in "${ACTIVE[@]}"; do
    read -r iid src dst dst_ip port egress rate <<<"${spec}"
    src_pid=$(cat "${RUN_DIR}/${src}.pid")
    python3.9 -m src.telemetry.runtime --intent "${iid}" --source-pid "${src_pid}" \
        --target "${dst_ip}" --port "${port}" --switch "${egress}" \
        --samples "${SAMPLES}" --interval 1 >"${LOG_DIR}/telemetry-${iid}.log" 2>&1 &
    COLLECTORS+=("$!")
    PIDS+=("$!")
done
if [ "${#FAULT_ARGS[@]}" -ge 3 ]; then
    (
        sleep "${FAULT_AT}"
        echo "=== t=${FAULT_AT}s: injecting fault: ${FAULT_ARGS[*]} ==="
        bash scripts/inject_fault.sh "${FAULT_ARGS[@]}" || echo "WARN: fault injection failed"
    ) &
    PIDS+=("$!")
    echo "  (fault '${FAULT_ARGS[*]}' scheduled at t=${FAULT_AT}s)"
fi
FAILED=0
for pid in "${COLLECTORS[@]}"; do
    wait "${pid}" || FAILED=$((FAILED + 1))
done
if [ "${FAILED}" -gt 0 ]; then
    echo "WARN: ${FAILED} collector(s) exited with an error; see ${LOG_DIR}/telemetry-*.log"
fi

echo "=== OpenFlow rules for h1 -> h2 traffic at the end of the run (packets, bytes) ==="
for sw in s1 s2 s4; do
    echo "  -- ${sw}"
    sudo ovs-ofctl -O OpenFlow13 dump-flows "${sw}" 2>/dev/null \
        | grep -E 'nw_src=10.0.0.1,nw_dst=10.0.0.2' \
        | sed -E 's/ *duration=[^,]*,//; s/ *table=0,//; s/idle_age=[^,]*,? *//; s/hard_age=[^,]*,? *//' \
        | sed 's/^/     /' || true
done

echo "=== Live results written to the dashboard database ==="
python3.9 - <<PY
from statistics import mean
from src.common import db
conn = db.connect()
since = float("${RUN_STARTED_AT}")
print(f"{'intent':8} {'path':22} {'n':>3} {'delay ms':>9} {'loss %':>7} {'Mbit/s':>8} {'guarantee':>10} {'state':>9}")
ids = [line.split()[0] for line in """$(printf '%s\n' "${ACTIVE[@]}")""".strip().splitlines()]
for iid in ids:
    rows = conn.execute(
        "SELECT delay_ms, loss_pct, throughput_mbps FROM measurements WHERE intent_id=? AND at>=?",
        (iid, since)).fetchall()
    rec = db.load_intent(conn, iid)
    plan = db.current_path(conn, iid)
    d = [r[0] for r in rows if r[0] is not None]
    l = [r[1] for r in rows if r[1] is not None]
    t = [r[2] for r in rows if r[2] is not None]
    path = "-".join(plan.switches) if plan else "-"
    g = rec.guarantee.min_bandwidth_mbps if rec else None
    print(f"{iid:8} {path:22} {len(rows):>3} {mean(d) if d else float('nan'):9.2f} "
          f"{mean(l) if l else float('nan'):7.2f} {mean(t) if t else float('nan'):8.2f} "
          f"{(str(g)+' Mbps') if g else '-':>10} {rec.state.value if rec else '-':>9}")
    events = conn.execute(
        "SELECT type FROM events WHERE intent_id=? AND at>=? AND type IN ('sla.violated','path.installed','violation.suppressed')",
        (iid, since)).fetchall()
    if events:
        print("         events:", ", ".join(e[0] for e in events))
conn.close()
PY
echo "=== LIVE MEASUREMENT OF ALL INTENTS COMPLETE: refresh http://localhost:8080 ==="
