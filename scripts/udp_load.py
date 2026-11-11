"""Paced UDP load generator for live dashboard runs.

Run inside a Mininet host namespace (via mnexec). Sends fixed-size datagrams to
DST:PORT at an approximately constant on-wire rate so an intent's bandwidth
guarantee is exercised by real traffic rather than by probes alone.

Usage: python3.9 scripts/udp_load.py DST_IP PORT RATE_MBPS SECONDS
"""

from __future__ import annotations

import socket
import sys
import time

PAYLOAD_BYTES = 1200
# UDP (8) + IPv4 (20) + Ethernet (14) + VLAN tag on tagged hops (4).
ON_WIRE_BYTES = PAYLOAD_BYTES + 46


def main() -> int:
    dst, port, rate_mbps, seconds = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
    pps = rate_mbps * 1_000_000 / 8 / ON_WIRE_BYTES
    payload = b"L" * PAYLOAD_BYTES  # never equals the probe payload b"team16"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
    start = time.perf_counter()
    sent = 0
    while True:
        elapsed = time.perf_counter() - start
        if elapsed >= seconds:
            break
        due = int(elapsed * pps)
        while sent < due:
            try:
                sock.sendto(payload, (dst, port))
            except OSError:
                pass
            sent += 1
        time.sleep(0.001)
    print(f"sent {sent} datagrams to {dst}:{port} over {seconds:.0f}s (~{rate_mbps} Mbit/s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
