#!/usr/bin/env bash
# Inject or clear a fault on one inter-switch link of the running Mininet topology.
# Run inside the SDN container while a live run is in progress.
#
#   bash scripts/inject_fault.sh s4 s5 down        # link failure (both ends down)
#   bash scripts/inject_fault.sh s4 s5 up          # restore the link
#   bash scripts/inject_fault.sh s1 s4 delay 40    # add 40 ms on the s1->s4 egress
#   bash scripts/inject_fault.sh s1 s4 clear       # restore the configured delay
set -euo pipefail

A="${1:?first switch, e.g. s4}"
B="${2:?second switch, e.g. s5}"
ACTION="${3:?down | up | delay MS | clear}"
VALUE="${4:-}"
STATE_DIR="/var/run/team16"
mkdir -p "${STATE_DIR}"

iface_between() {
    ip -o link show | grep -o "${1}-eth[0-9]*@${2}-eth[0-9]*" | head -n1 | cut -d@ -f1
}

IF_A=$(iface_between "${A}" "${B}")
IF_B=$(iface_between "${B}" "${A}")
if [ -z "${IF_A}" ] || [ -z "${IF_B}" ]; then
    echo "FAIL: no link ${A}-${B} found. Is the live run (Mininet) still running?"
    exit 1
fi

netem_parent() {
    tc qdisc show dev "$1" | awk '/netem/ {for (i=1; i<=NF; i++) if ($i == "parent") {print $(i+1); exit}}'
}

case "${ACTION}" in
    down)
        ip link set "${IF_A}" down
        ip link set "${IF_B}" down
        echo "FAULT: link ${A}-${B} DOWN (${IF_A}, ${IF_B})"
        ;;
    up)
        ip link set "${IF_A}" up
        ip link set "${IF_B}" up
        echo "RESTORED: link ${A}-${B} UP"
        ;;
    delay)
        [ -n "${VALUE}" ] || { echo "usage: $0 ${A} ${B} delay MS"; exit 2; }
        TARGET_IF="${IF_A}"
        PARENT=$(netem_parent "${TARGET_IF}")
        if [ -z "${PARENT}" ]; then
            TARGET_IF="${IF_B}"
            PARENT=$(netem_parent "${TARGET_IF}")
        fi
        [ -n "${PARENT}" ] || { echo "FAIL: no netem qdisc on ${IF_A} or ${IF_B}"; exit 1; }
        if [ ! -f "${STATE_DIR}/delay-${TARGET_IF}" ]; then
            tc qdisc show dev "${TARGET_IF}" | grep -o 'delay [0-9.]*[mu]*s' | head -n1 | awk '{print $2}' \
                > "${STATE_DIR}/delay-${TARGET_IF}"
        fi
        tc qdisc change dev "${TARGET_IF}" parent "${PARENT}" netem delay "${VALUE}ms"
        echo "FAULT: ${A}-${B} delay set to ${VALUE} ms on ${TARGET_IF} (was $(cat "${STATE_DIR}/delay-${TARGET_IF}"))"
        ;;
    clear)
        for TARGET_IF in "${IF_A}" "${IF_B}"; do
            PARENT=$(netem_parent "${TARGET_IF}")
            ORIGINAL=$(cat "${STATE_DIR}/delay-${TARGET_IF}" 2>/dev/null || true)
            if [ -n "${PARENT}" ] && [ -n "${ORIGINAL}" ]; then
                tc qdisc change dev "${TARGET_IF}" parent "${PARENT}" netem delay "${ORIGINAL}"
                rm -f "${STATE_DIR}/delay-${TARGET_IF}"
                echo "RESTORED: ${A}-${B} delay back to ${ORIGINAL} on ${TARGET_IF}"
            fi
        done
        ;;
    *)
        echo "usage: $0 A B down|up|delay MS|clear"
        exit 2
        ;;
esac
