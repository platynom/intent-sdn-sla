#!/usr/bin/env python3
"""TWAMP-Light-style one-way and round-trip UDP probe using shared kernel clock.

Valid only across Mininet network namespaces on the same Linux kernel host where
``time.time_ns()`` shares a single clock across sender and responder. This is
NOT an RFC 5357 TWAMP implementation.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import socket
import statistics
import struct
import threading
import time
from pathlib import Path
from typing import Dict, Optional

REQ_STRUCT = struct.Struct("!QQQ")    # session_id, seq, t1_ns
RESP_STRUCT = struct.Struct("!QQQQ")  # session_id, seq, t1_ns, t2_ns
PAD = b"\x00" * 32


def run_receiver(
    bind_ip: str,
    port: int,
    duration: float,
    out_path: Optional[Path] = None,
) -> int:
    """Receive sequenced probes, record shared-clock forward OWD, and echo t2_ns."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind_ip, port))
    sock.settimeout(0.2)
    deadline = time.monotonic() + duration
    rows = []
    try:
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            t2_ns = time.time_ns()
            if len(data) < REQ_STRUCT.size:
                continue
            session_id, seq, t1_ns = REQ_STRUCT.unpack_from(data, 0)
            reply = RESP_STRUCT.pack(session_id, seq, t1_ns, t2_ns) + PAD
            sock.sendto(reply, addr)
            fwd_ms = (t2_ns - t1_ns) / 1_000_000.0
            rows.append((seq, t1_ns, t2_ns, fwd_ms))
    finally:
        sock.close()

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["seq", "t1_ns", "t2_ns", "forward_owd_ms"])
            for seq, t1_ns, t2_ns, fwd_ms in rows:
                writer.writerow([seq, t1_ns, t2_ns, f"{fwd_ms:.6f}"])
    return 0


def run_sender(
    dst_ip: str,
    port: int,
    count: int,
    interval: float,
    out_path: Path,
    drain_s: float = 1.0,
) -> int:
    """Send sequenced probes at 1/interval Hz and compute OWD and RTT per probe."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(0.2)

    session_id = random.SystemRandom().getrandbits(64)
    sent_times: Dict[int, int] = {}
    received: Dict[int, tuple[int, int, int]] = {}
    stop_rx = threading.Event()

    def _rx_loop() -> None:
        while not stop_rx.is_set():
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            t3_ns = time.time_ns()
            if len(data) < RESP_STRUCT.size:
                continue
            r_sid, seq, t1_ns, t2_ns = RESP_STRUCT.unpack_from(data, 0)
            if r_sid != session_id:
                continue
            if seq not in sent_times or sent_times[seq] != t1_ns:
                continue
            if seq not in received:
                received[seq] = (t1_ns, t2_ns, t3_ns)

    rx_thread = threading.Thread(target=_rx_loop, daemon=True)
    rx_thread.start()

    start_mono = time.perf_counter()
    try:
        for seq in range(1, count + 1):
            target_mono = start_mono + (seq - 1) * interval
            while True:
                rem = target_mono - time.perf_counter()
                if rem <= 0:
                    break
                if rem > 0.002:
                    time.sleep(rem * 0.5)
            t1_ns = time.time_ns()
            sent_times[seq] = t1_ns
            pkt = REQ_STRUCT.pack(session_id, seq, t1_ns) + PAD
            sock.sendto(pkt, (dst_ip, port))
        time.sleep(drain_s)
    finally:
        stop_rx.set()
        sock.close()
        rx_thread.join(timeout=2.0)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fwd_list = []
    rev_list = []
    rtt_list = []
    with out_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "seq", "t1_ns", "t2_ns", "t3_ns",
            "forward_owd_ms", "reverse_owd_ms", "rtt_ms", "half_rtt_ms",
        ])
        for seq in range(1, count + 1):
            if seq not in received:
                continue
            t1_ns, t2_ns, t3_ns = received[seq]
            fwd_ms = (t2_ns - t1_ns) / 1_000_000.0
            rev_ms = (t3_ns - t2_ns) / 1_000_000.0
            rtt_ms = (t3_ns - t1_ns) / 1_000_000.0
            half_rtt_ms = rtt_ms / 2.0
            fwd_list.append(fwd_ms)
            rev_list.append(rev_ms)
            rtt_list.append(rtt_ms)
            writer.writerow([
                seq, t1_ns, t2_ns, t3_ns,
                f"{fwd_ms:.6f}", f"{rev_ms:.6f}", f"{rtt_ms:.6f}", f"{half_rtt_ms:.6f}",
            ])

    summary = {
        "session_id": session_id,
        "probes_sent": count,
        "probes_received": len(rtt_list),
        "forward_owd_ms": statistics.mean(fwd_list) if fwd_list else None,
        "reverse_owd_ms": statistics.mean(rev_list) if rev_list else None,
        "rtt_ms": statistics.mean(rtt_list) if rtt_list else None,
        "half_rtt_ms": (statistics.mean(rtt_list) / 2.0) if rtt_list else None,
        "max_rtt_ms": max(rtt_list) if rtt_list else None,
    }
    print(json.dumps(summary))
    if not rtt_list or max(rtt_list) > 1000.0:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    rx_p = sub.add_parser("recv")
    rx_p.add_argument("--bind", default="10.0.0.2")
    rx_p.add_argument("--port", type=int, default=5001)
    rx_p.add_argument("--duration", type=float, required=True)
    rx_p.add_argument("--out", type=Path, default=None)

    tx_p = sub.add_parser("send")
    tx_p.add_argument("--dst", default="10.0.0.2")
    tx_p.add_argument("--port", type=int, default=5001)
    tx_p.add_argument("--count", type=int, default=100)
    tx_p.add_argument("--interval", type=float, default=0.1)
    tx_p.add_argument("--drain", type=float, default=1.0)
    tx_p.add_argument("--out", type=Path, required=True)

    args = parser.parse_args()
    if args.mode == "recv":
        return run_receiver(args.bind, args.port, args.duration, args.out)
    return run_sender(args.dst, args.port, args.count, args.interval, args.out, drain_s=args.drain)


if __name__ == "__main__":
    raise SystemExit(main())
