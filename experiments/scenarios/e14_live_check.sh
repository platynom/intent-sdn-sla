#!/usr/bin/env bash
# Step 7b secondary live check: N=4 intents x 20 Mbit/s (80 Mbit/s total), 40 ms
# fault on s1-eth2, B3 detector, measuring 20 s post-recovery throughput and loss.
set -euo pipefail

REPO_PATH="/app"
TAG="new"
DURATION=20
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo) REPO_PATH="$2"; shift 2 ;;
        --tag) TAG="$2"; shift 2 ;;
        --duration) DURATION="$2"; shift 2 ;;
        *) echo "Usage: $0 [--repo PATH] [--tag old|new] [--duration S]" >&2; exit 2 ;;
    esac
done

export TEAM16_DB_PATH="$(mktemp -d /tmp/team16-e14live.XXXXXX)/state.db"
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

RYU_PID="" API_PID="" TOPO_PID=""
RX_PIDS=() LOAD_PIDS=() TEL_PIDS=()
cleanup() {
    for pid in "${TEL_PIDS[@]:-}" "${LOAD_PIDS[@]:-}" "${RX_PIDS[@]:-}" "${TOPO_PID:-}" "${API_PID:-}" "${RYU_PID:-}"; do
        if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
            kill "${pid}" 2>/dev/null || true
            wait "${pid}" 2>/dev/null || true
        fi
    done
    clean_mininet
}
trap cleanup EXIT INT TERM

clean_mininet
PYTHONPATH="${REPO_PATH}:/app" python3.9 -c "
from src.common import db
conn = db.connect()
db.init_db(conn)
conn.close()
"

PYTHONPATH="${REPO_PATH}:/usr/lib/python3/dist-packages" \
    ryu-manager --ofp-tcp-listen-port 6653 \
    "${REPO_PATH}/src/enforcement/controller.py" >"${LOG_DIR}/ryu-e14live.log" 2>&1 &
RYU_PID=$!
sleep 2

PYTHONPATH="${REPO_PATH}:/app" \
    python3.9 -m uvicorn src.intent_manager.api:app \
    --host 127.0.0.1 --port 8000 >"${LOG_DIR}/api-e14live.log" 2>&1 &
API_PID=$!
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
" >"${LOG_DIR}/topo-e14live.log" 2>&1 &
TOPO_PID=$!
sleep 4

for sw in s1 s2 s3 s4 s5 s6 s7; do
    ok=0
    for _ in $(seq 1 60); do
        if sudo ovs-ofctl -O OpenFlow13 dump-flows "${sw}" 2>/dev/null | grep -q "CONTROLLER"; then
            ok=1; break
        fi
        sleep 0.2
    done
    [ "${ok}" = "1" ] || { echo "FAIL: switch ${sw} not ready"; exit 1; }
done

for i in 1 2 3 4; do
    dport=$((5100 + i))
    yaml_body=$(cat <<EOF
intent:
  id: INT-10${i}
  tenant: t${i}
  priority: 2
  match:
    src: 10.0.0.1/32
    dst: 10.0.0.2/32
    proto: udp
    dport: ${dport}
  guarantee:
    min_bandwidth_mbps: 20
    max_latency_ms: 35
  consistency: relaxed
  on_violation: reroute
  dwell_seconds: 0
EOF
)
    code=$(curl -s -o "/tmp/e14live_post_${i}.json" -w "%{http_code}" -X POST \
        http://127.0.0.1:8000/intent -H "Content-Type: text/plain" \
        --data-binary "${yaml_body}")
    [ "${code}" = "201" ] || { echo "FAIL: INT-10${i} HTTP ${code}"; cat "/tmp/e14live_post_${i}.json"; exit 1; }
done

for _ in $(seq 1 40); do
    cnt=$(PYTHONPATH="${REPO_PATH}" python3.9 -c "
from src.common import db
c = db.connect()
print(c.execute(\"SELECT COUNT(*) FROM intents WHERE state='active'\").fetchone()[0])
c.close()")
    [ "${cnt}" = "4" ] && break
    sleep 0.2
done

H1_PID=$(cat /var/run/team16/h1.pid)
H2_PID=$(cat /var/run/team16/h2.pid)

# Start 4 probe+load servers on h2 ports 5101..5104
for i in 1 2 3 4; do
    dport=$((5100 + i))
    rm -f "/tmp/e14live_rx_${TAG}_${dport}.json" "/tmp/e14live_tx_${TAG}_${dport}.log"
    mnexec -da "${H2_PID}" python3.9 -u -c "
import json, socket
from pathlib import Path
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
s.bind(('10.0.0.2', ${dport}))
cnt = 0
nbytes = 0
while True:
    data, addr = s.recvfrom(4096)
    if data == b'team16':
        s.sendto(data, addr)
    elif data == b'RESET':
        cnt = 0
        nbytes = 0
    elif data == b'DUMP':
        Path('/tmp/e14live_rx_${TAG}_${dport}.json').write_text(json.dumps({'count': cnt, 'payload_bytes': nbytes}))
        break
    else:
        cnt += 1
        nbytes += len(data)
" >"${LOG_DIR}/e14live-rx-${dport}.log" 2>&1 &
    RX_PIDS+=("$!")
done
sleep 0.5

# Inject 40 ms fault on the north primary link s1-eth2. Bandwidth intents put an
# OVS HTB queue on this port; queues.restore_netem keeps one netem per HTB class,
# so the fault is applied to every netem on the port.
FAULT_IF="s1-eth2"
NETEM_PARENTS=$(sudo tc qdisc show dev "${FAULT_IF}" | awk '/netem/ {for (i=1; i<=NF; i++) if ($i == "parent") print $(i+1)}')
[ -n "${NETEM_PARENTS}" ] || { echo "FAIL: no netem on ${FAULT_IF}"; sudo tc qdisc show dev "${FAULT_IF}"; exit 1; }
echo "E14-LIVE qdiscs on ${FAULT_IF} before fault:"
sudo tc qdisc show dev "${FAULT_IF}"
for np in ${NETEM_PARENTS}; do
    sudo tc qdisc change dev "${FAULT_IF}" parent "${np}" netem delay 40ms
done

# Keep each intent's 20 Mbit/s load running while the detector samples, so the
# throughput guarantee is judged on real traffic (probe-only traffic reads as
# ~0 Mbit/s and caused a spurious throughput "violation" in the first live run).
WARM_PIDS=()
for i in 1 2 3 4; do
    dport=$((5100 + i))
    mnexec -da "${H1_PID}" python3.9 /app/scripts/udp_load.py 10.0.0.2 "${dport}" 20.0 16 \
        >"/tmp/e14live_warm_${TAG}_${dport}.log" 2>&1 &
    WARM_PIDS+=("$!")
done
sleep 1

# Trigger B3 detection across all 4 flows
for i in 1 2 3 4; do
    dport=$((5100 + i))
    PYTHONPATH="${REPO_PATH}" python3.9 -m src.telemetry.runtime \
        --intent "INT-10${i}" --source-pid "${H1_PID}" --target 10.0.0.2 --port "${dport}" \
        --switch s1 --samples 8 --interval 1.0 \
        --ewma-alpha 0.3 --hysteresis-pct 0.1 --consecutive-required 3 \
        >"${LOG_DIR}/e14live-tel-${i}.log" 2>&1 &
    TEL_PIDS+=("$!")
done
for pid in "${TEL_PIDS[@]}"; do
    wait "${pid}" || true
done
TEL_PIDS=()
for pid in "${WARM_PIDS[@]}"; do
    wait "${pid}" || true
done
sleep 2

# Reset receiver counters from h1 and send 4 x 20 Mbps flows for 20 s
mnexec -da "${H1_PID}" python3.9 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for p in (5101, 5102, 5103, 5104):
    s.sendto(b'RESET', ('10.0.0.2', p))
"
sleep 0.2

for i in 1 2 3 4; do
    dport=$((5100 + i))
    mnexec -da "${H1_PID}" python3.9 /app/scripts/udp_load.py 10.0.0.2 "${dport}" 20.0 "${DURATION}" \
        >"/tmp/e14live_tx_${TAG}_${dport}.log" 2>&1 &
    LOAD_PIDS+=("$!")
done
for pid in "${LOAD_PIDS[@]}"; do
    wait "${pid}" || true
done
LOAD_PIDS=()
sleep 0.5

mnexec -da "${H1_PID}" python3.9 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
for p in (5101, 5102, 5103, 5104):
    s.sendto(b'DUMP', ('10.0.0.2', p))
"
sleep 0.3
for pid in "${RX_PIDS[@]}"; do
    wait "${pid}" 2>/dev/null || true
done
RX_PIDS=()

PYTHONPATH="${REPO_PATH}" python3.9 - "${TAG}" "${DURATION}" <<'PY'
import csv
import json
import re
import sys
import time
from pathlib import Path
from src.common import db

tag = sys.argv[1]
dur = float(sys.argv[2])
conn = db.connect()

out_dir = Path("experiments/results/redfill_2026-11/E14_LIVE/raw")
out_dir.mkdir(parents=True, exist_ok=True)
stamp = time.strftime("%Y%m%d%H%M%S")
out_path = out_dir / f"redfill_e14_live_{tag}_{stamp}.csv"

rows_out = []
for i in range(1, 5):
    iid = f"INT-10{i}"
    dport = 5100 + i
    tx_text = Path(f"/tmp/e14live_tx_{tag}_{dport}.log").read_text(encoding="utf-8")
    m = re.search(r"sent\s+(\d+)\s+datagrams", tx_text)
    tx_cnt = int(m.group(1)) if m else 0
    rx_data = json.loads(Path(f"/tmp/e14live_rx_{tag}_{dport}.json").read_text(encoding="utf-8"))
    rx_cnt = int(rx_data["count"])
    # Match udp_load.py ON_WIRE_BYTES = 1246
    wire_mbps = (rx_cnt * 1246 * 8) / dur / 1e6
    payload_mbps = (rx_data["payload_bytes"] * 8) / dur / 1e6
    loss_pct = (100.0 * max(0, tx_cnt - rx_cnt) / tx_cnt) if tx_cnt > 0 else 100.0
    plan = db.current_path(conn, iid)
    route = "-".join(plan.switches) if plan else "none"
    rows_out.append((iid, dport, route, tx_cnt, rx_cnt, wire_mbps, payload_mbps, loss_pct))
    print(f"E14-LIVE {tag} {iid} (udp/{dport}) path={route}: tx={tx_cnt} rx={rx_cnt} wire={wire_mbps:.3f} Mbps loss={loss_pct:.2f}%")

conn.close()
with out_path.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["run_id", "timestamp", "metric", "value", "unit"])
    now_ts = int(time.time())
    for idx, (iid, _, _, tx_c, rx_c, w_mbps, p_mbps, l_pct) in enumerate(rows_out, 1):
        w.writerow([1, now_ts, f"flow{idx}_wire_mbps", f"{w_mbps:.6f}", "Mbps"])
        w.writerow([1, now_ts, f"flow{idx}_payload_mbps", f"{p_mbps:.6f}", "Mbps"])
        w.writerow([1, now_ts, f"flow{idx}_loss_pct", f"{l_pct:.6f}", "pct"])
    mean_mbps = sum(r[5] for r in rows_out) / 4.0
    mean_loss = sum(r[7] for r in rows_out) / 4.0
    total_mbps = sum(r[5] for r in rows_out)
    w.writerow([1, now_ts, "mean_flow_wire_mbps", f"{mean_mbps:.6f}", "Mbps"])
    w.writerow([1, now_ts, "total_delivered_wire_mbps", f"{total_mbps:.6f}", "Mbps"])
    w.writerow([1, now_ts, "mean_flow_loss_pct", f"{mean_loss:.6f}", "pct"])
PY
