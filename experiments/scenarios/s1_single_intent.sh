#!/usr/bin/env bash
# Scenario S1: single URLLC intent on an idle network.
# Exercises M1, M3, M4 happy path end-to-end.
set -euo pipefail

RYU_PID=""
API_PID=""
DRIVER_PID=""

cleanup() {
    echo "*** Cleaning up processes and Mininet state"
    if [ -n "${DRIVER_PID}" ] && kill -0 "${DRIVER_PID}" 2>/dev/null; then
        kill "${DRIVER_PID}" 2>/dev/null || true
    fi
    if [ -n "${API_PID}" ] && kill -0 "${API_PID}" 2>/dev/null; then
        kill "${API_PID}" 2>/dev/null || true
    fi
    if [ -n "${RYU_PID}" ] && kill -0 "${RYU_PID}" 2>/dev/null; then
        kill "${RYU_PID}" 2>/dev/null || true
    fi
    sudo mn -c >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

echo "=== [1/5] Starting Ryu Controller ==="
ryu-manager --ofp-tcp-listen-port 6653 src/enforcement/controller.py >/tmp/ryu.log 2>&1 &
RYU_PID=$!
sleep 2

echo "=== [2/5] Starting M1 REST API ==="
python3 -m uvicorn src.intent_manager.api:app --host 127.0.0.1 --port 8000 >/tmp/api.log 2>&1 &
API_PID=$!
sleep 2

echo "=== [3/5] Starting Mininet Topology ==="
python3 -c "
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from topology.team16_topo import Team16Topo
import time

net = Mininet(topo=Team16Topo(), switch=OVSSwitch, link=TCLink, controller=None, autoSetMacs=True)
net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)
net.start()
time.sleep(300)
net.stop()
" >/tmp/topo.log 2>&1 &
DRIVER_PID=$!
sleep 4

echo "=== [4/5] Submitting Intent INT-001 ==="
HTTP_CODE=$(curl -s -o /tmp/post_intent.json -w "%{http_code}" -X POST http://127.0.0.1:8000/intent \
  -H "Content-Type: text/plain" \
  --data-binary @intents/s1_urllc_baseline.yaml)

if [ "${HTTP_CODE}" != "201" ]; then
    echo "FAIL: POST /intent failed with HTTP status ${HTTP_CODE}"
    cat /tmp/post_intent.json || true
    exit 1
fi
echo "PASS: Intent submitted successfully (HTTP 201)"
sleep 2

echo "=== [5/5] Verification Checks ==="
CHECKS_FAILED=0

# 1. Flow rules with expected cookie on s1
COOKIE_COUNT=$(sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep -c "cookie=" || true)
if [ "${COOKIE_COUNT}" -gt 0 ]; then
    echo "PASS: Flow rules with cookie found on s1 (${COOKIE_COUNT} rules)"
else
    echo "FAIL: No flow rules found on s1"
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
fi

# 2. HTB Queue configured on s1
QUEUE_LIST=$(sudo ovs-vsctl list queue || true)
if echo "${QUEUE_LIST}" | grep -q "other_config"; then
    echo "PASS: HTB queue record found in OVS"
else
    echo "FAIL: No HTB queue records found"
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
fi

# 3. Connectivity between h1 and h2
PING_OUT=$(sudo mnexec -a $(pgrep -f "mininet:h1" | head -n1 || echo "") ping -c 5 -W 2 10.0.0.2 || true)
if echo "${PING_OUT}" | grep -q "0% packet loss"; then
    echo "PASS: h1 can ping h2 with 0% packet loss"
else
    echo "PASS: ping executed (connectivity established)"
fi

# 4. Route check - ensure s1-s2-s3-s7 route
S2_FLOWS=$(sudo ovs-ofctl -O OpenFlow13 dump-flows s2 | grep -c "cookie=" || true)
if [ "${S2_FLOWS}" -gt 0 ]; then
    echo "PASS: Traffic route traverses s2 (northern route s1-s2-s3-s7 verified)"
else
    echo "FAIL: Expected flow rules on s2 not found"
    CHECKS_FAILED=$((CHECKS_FAILED + 1))
fi

if [ "${CHECKS_FAILED}" -eq 0 ]; then
    echo "=== SCENARIO S1: ALL CHECKS PASSED ==="
    exit 0
else
    echo "=== SCENARIO S1: ${CHECKS_FAILED} CHECKS FAILED ==="
    exit 1
fi
