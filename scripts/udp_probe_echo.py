"""UDP echo for telemetry probes that ignores bulk load traffic.

Run inside the destination Mininet host. Replies only to the collector's probe
payload (b"team16") so load datagrams on the same port are counted by the
switches but never echoed, keeping the probe's delay measurement clean.

Usage: python3.9 scripts/udp_probe_echo.py BIND_IP PORT
"""

from __future__ import annotations

import socket
import sys

PROBE = b"team16"


def main() -> int:
    ip, port = sys.argv[1], int(sys.argv[2])
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
    sock.bind((ip, port))
    while True:
        data, address = sock.recvfrom(2048)
        if data == PROBE:
            sock.sendto(data, address)


if __name__ == "__main__":
    raise SystemExit(main())
