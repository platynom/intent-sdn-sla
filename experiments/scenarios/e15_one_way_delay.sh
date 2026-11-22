#!/usr/bin/env bash
# E15: TWAMP-Light-style shared-clock one-way delay (OWD) vs RTT/2 evaluation
# across north, middle, and south routes in healthy and 40 ms fault conditions.
set -euo pipefail

if [ -z "${TEAM16_DB_PATH:-}" ]; then
    export TEAM16_DB_PATH="$(mktemp -d /tmp/team16-e15.XXXXXX)/state.db"
fi

ROUTE="north"
CONDITION="healthy"
RUNS=10
while [[ $# -gt 0 ]]; do
    case "$1" in
        --route)
            ROUTE="$2"
            shift 2
            ;;
        --condition)
            CONDITION="$2"
            shift 2
            ;;
        --runs)
            RUNS="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--route north|middle|south] [--condition healthy|fault] [--runs N]" >&2
            exit 2
            ;;
    esac
done

case "${ROUTE}" in
    north)
        INTENT_FILE="experiments/scenarios/fixtures/redfill_e15_north.yaml"
        FAULT_DEV="s1-eth2"
        EXPECTED_ROUTE="s1,s2,s3,s7"
        PLANNED_HEALTHY="6.0"
        PLANNED_FAULT="44.0"
        ;;
    middle)
        INTENT_FILE="experiments/scenarios/fixtures/redfill_e15_middle.yaml"
        FAULT_DEV="s1-eth3"
        EXPECTED_ROUTE="s1,s4,s5,s7"
        PLANNED_HEALTHY="15.0"
        PLANNED_FAULT="50.0"
        ;;
    south)
        INTENT_FILE="experiments/scenarios/fixtures/redfill_e15_south.yaml"
        FAULT_DEV="s1-eth4"
        EXPECTED_ROUTE="s1,s6,s7"
        PLANNED_HEALTHY="24.0"
        PLANNED_FAULT="52.0"
        ;;
    *)
        echo "--route must be north, middle, or south" >&2
        exit 2
        ;;
esac

if [[ "${CONDITION}" != "healthy" && "${CONDITION}" != "fault" ]]; then
    echo "--condition must be healthy or fault" >&2
    exit 2
fi

PLANNED_OWD="${PLANNED_HEALTHY}"
if [ "${CONDITION}" = "fault" ]; then
    PLANNED_OWD="${PLANNED_FAULT}"
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
    local ryu_pid="" api_pid="" topo_pid="" rx_pid=""
    cleanup_one() {
        for pid in "${rx_pid:-}" "${topo_pid:-}" "${api_pid:-}" "${ryu_pid:-}"; do
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
        src/enforcement/controller.py >"${LOG_DIR}/ryu-e15.log" 2>&1 &
    ryu_pid=$!
    sleep 2

    python3.9 -m uvicorn src.intent_manager.api:app \
        --host 127.0.0.1 --port 8000 >"${LOG_DIR}/api-e15.log" 2>&1 &
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
" >"${LOG_DIR}/topo-e15.log" 2>&1 &
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
            echo "FAIL: switch ${sw} not ready"
            exit 1
        fi
    done

    if [ "${CONDITION}" = "fault" ]; then
        local netem_parent
        netem_parent=$(sudo tc qdisc show dev "${FAULT_DEV}" \
            | awk '/netem/ {for (i=1; i<=NF; i++) if ($i == "parent") {print $(i+1); exit}}')
        if [ -z "${netem_parent}" ]; then
            echo "FAIL: no netem qdisc found on ${FAULT_DEV}"
            exit 1
        fi
        sudo tc qdisc change dev "${FAULT_DEV}" parent "${netem_parent}" netem delay 40ms
    fi

    local code
    code=$(curl -s -o /tmp/e15_post.json -w "%{http_code}" -X POST \
        http://127.0.0.1:8000/intent -H "Content-Type: text/plain" \
        --data-binary "@${INTENT_FILE}")
    if [ "${code}" != "201" ]; then
        echo "FAIL: POST /intent returned ${code}"
        cat /tmp/e15_post.json || true
        exit 1
    fi

    local route_ok=0
    local installed_route=""
    for _ in $(seq 1 40); do
        installed_route=$(python3.9 -c "
from src.common import db
conn = db.connect()
rec = db.load_intent(conn, 'INT-001')
p = db.current_path(conn, 'INT-001')
state = rec.state.value if rec else ''
sws = ','.join(p.switches) if p else ''
print(f'{state}|{sws}')
conn.close()")
        if [ "${installed_route}" = "active|${EXPECTED_ROUTE}" ]; then
            route_ok=1
            break
        fi
        sleep 0.2
    done
    if [ "${route_ok}" -ne 1 ]; then
        echo "FAIL: expected active|${EXPECTED_ROUTE}, got '${installed_route}'"
        exit 1
    fi
    sleep 0.5

    local h1_pid h2_pid
    h1_pid=$(cat /var/run/team16/h1.pid)
    h2_pid=$(cat /var/run/team16/h2.pid)

    local probe_csv="/tmp/e15_probes_${ROUTE}_${CONDITION}_${run_idx}.csv"
    rm -f "${probe_csv}"

    mnexec -da "${h2_pid}" python3.9 -u scripts/owd_probe.py recv \
        --bind 10.0.0.2 --port 5001 --duration 14.0 >"${LOG_DIR}/e15-rx.log" 2>&1 &
    rx_pid=$!
    sleep 0.3

    mnexec -da "${h1_pid}" python3.9 -u scripts/owd_probe.py send \
        --dst 10.0.0.2 --port 5001 --count 100 --interval 0.1 --drain 1.0 \
        --out "${probe_csv}" >"${LOG_DIR}/e15-tx.log" 2>&1

    wait "${rx_pid}" || true
    rx_pid=""

    python3.9 - "${ROUTE}" "${CONDITION}" "${run_idx}" "${PLANNED_OWD}" "${probe_csv}" <<'PY'
import csv
import os
import statistics
import sys
import time
from pathlib import Path

route = sys.argv[1]
condition = sys.argv[2]
run_idx = int(sys.argv[3])
planned_owd = float(sys.argv[4])
probe_csv = Path(sys.argv[5])

fwd, rev, rtt, half_rtt = [], [], [], []
with probe_csv.open(newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        fwd.append(float(row["forward_owd_ms"]))
        rev.append(float(row["reverse_owd_ms"]))
        rtt.append(float(row["rtt_ms"]))
        half_rtt.append(float(row["half_rtt_ms"]))

if not fwd:
    raise RuntimeError(f"No probes received for E15 {route}/{condition} run {run_idx}")

mean_fwd = statistics.mean(fwd)
mean_rev = statistics.mean(rev)
mean_rtt = statistics.mean(rtt)
mean_half = statistics.mean(half_rtt)
rtt_half_err = mean_half - mean_fwd
compliant = 1 if mean_fwd <= 35.0 else 0

out_dir = Path(os.environ.get("E15_RAW_DIR", "experiments/results/raw"))
out_dir.mkdir(parents=True, exist_ok=True)
stamp = time.strftime("%Y%m%d%H%M%S")
prefix = os.environ.get("E15_RESULT_PREFIX", "redfill_e15")
out_path = out_dir / f"{prefix}_{route}_{condition}_{stamp}_{run_idx:02d}.csv"
now_ts = int(time.time())
with out_path.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["run_id", "timestamp", "metric", "value", "unit"])
    w.writerow([run_idx, now_ts, "forward_owd_ms", f"{mean_fwd:.6f}", "ms"])
    w.writerow([run_idx, now_ts, "reverse_owd_ms", f"{mean_rev:.6f}", "ms"])
    w.writerow([run_idx, now_ts, "rtt_ms", f"{mean_rtt:.6f}", "ms"])
    w.writerow([run_idx, now_ts, "half_rtt_ms", f"{mean_half:.6f}", "ms"])
    w.writerow([run_idx, now_ts, "rtt_half_error_ms", f"{rtt_half_err:.6f}", "ms"])
    w.writerow([run_idx, now_ts, "planned_owd_ms", f"{planned_owd:.6f}", "ms"])
    w.writerow([run_idx, now_ts, "owd_compliant_35ms", compliant, "flag"])
    w.writerow([run_idx, now_ts, "probes_received", len(fwd), "count"])

print(
    f"E15 {route}/{condition} run {run_idx}: owd={mean_fwd:.3f} ms, rtt={mean_rtt:.3f} ms, "
    f"rtt/2={mean_half:.3f} ms (planned={planned_owd:.1f}, err={rtt_half_err:+.3f}, "
    f"compliant={compliant}, rx={len(fwd)}/100) -> {out_path}"
)
PY
}

for ((r = 1; r <= RUNS; r++)); do
    echo "=== E15 ${ROUTE} ${CONDITION} run ${r}/${RUNS} ==="
    run_one "${r}"
done
