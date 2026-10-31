#!/usr/bin/env python3
"""Sequence-numbered UDP sender, receiver, and window analyzer for E4 packet loss."""

from __future__ import annotations

import argparse
import csv
import json
import socket
import struct
import time
from pathlib import Path
from typing import Dict, List

HEADER_STRUCT = struct.Struct("!Qd")  # uint64 seq, float64 tx_timestamp


def run_receiver(bind_ip: str, port: int, duration: float, out_path: Path) -> int:
    """Receive sequence-numbered UDP packets and record rx timestamps."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind_ip, port))
    sock.settimeout(0.2)
    deadline = time.time() + duration
    received: List[tuple[int, float, float]] = []
    while time.time() < deadline:
        try:
            data, _ = sock.recvfrom(2048)
        except socket.timeout:
            continue
        rx_time = time.time()
        if len(data) >= HEADER_STRUCT.size:
            seq, tx_time = HEADER_STRUCT.unpack_from(data, 0)
            received.append((seq, tx_time, rx_time))
    sock.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["seq", "tx_time", "rx_time"])
        writer.writerows(received)
    return 0


def run_sender(
    dst_ip: str,
    port: int,
    rate_pps: int,
    payload_bytes: int,
    duration: float,
    out_path: Path,
) -> int:
    """Send sequence-numbered UDP packets at a fixed rate using a deadline loop."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    padding = b"x" * max(0, payload_bytes - HEADER_STRUCT.size)
    interval = 1.0 / float(rate_pps)
    start_wall = time.time()
    start_mono = time.perf_counter()
    total_packets = int(round(duration * rate_pps))
    sent: List[tuple[int, float]] = []
    for seq in range(1, total_packets + 1):
        target_mono = start_mono + (seq - 1) * interval
        while True:
            now_mono = time.perf_counter()
            rem = target_mono - now_mono
            if rem <= 0:
                break
            if rem > 0.002:
                time.sleep(rem * 0.5)
        tx_time = start_wall + (time.perf_counter() - start_mono)
        pkt = HEADER_STRUCT.pack(seq, tx_time) + padding
        try:
            sock.sendto(pkt, (dst_ip, port))
            sent.append((seq, tx_time))
        except OSError:
            pass
    sock.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["seq", "tx_time"])
        writer.writerows(sent)
    return 0


def analyze_window(
    tx_log: Path,
    rx_log: Path,
    window_start: float,
    window_end: float,
) -> Dict[str, int]:
    """Count sent, lost, duplicated, and reordered packets in [window_start, window_end]."""
    tx_in_window: set[int] = set()
    with tx_log.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            seq = int(row["seq"])
            tx_t = float(row["tx_time"])
            if window_start <= tx_t <= window_end:
                tx_in_window.add(seq)

    rx_Order: List[int] = []
    rx_counts: Dict[int, int] = {}
    with rx_log.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            seq = int(row["seq"])
            if seq in tx_in_window:
                rx_Order.append(seq)
                rx_counts[seq] = rx_counts.get(seq, 0) + 1

    sent_count = len(tx_in_window)
    unique_received = len(rx_counts)
    lost_count = max(0, sent_count - unique_received)
    duplicated_count = sum(c - 1 for c in rx_counts.values() if c > 1)

    reordered_count = 0
    max_seen = -1
    seen_once: set[int] = set()
    for seq in rx_Order:
        if seq in seen_once:
            continue
        seen_once.add(seq)
        if seq < max_seen:
            reordered_count += 1
        else:
            max_seen = seq

    return {
        "packets_sent": sent_count,
        "packets_received": unique_received,
        "packets_lost": lost_count,
        "packets_duplicated": duplicated_count,
        "packets_reordered": reordered_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)

    rx_p = sub.add_parser("recv")
    rx_p.add_argument("--bind", default="10.0.0.2")
    rx_p.add_argument("--port", type=int, default=5001)
    rx_p.add_argument("--duration", type=float, required=True)
    rx_p.add_argument("--out", type=Path, required=True)

    tx_p = sub.add_parser("send")
    tx_p.add_argument("--dst", default="10.0.0.2")
    tx_p.add_argument("--port", type=int, default=5001)
    tx_p.add_argument("--rate", type=int, default=1000)
    tx_p.add_argument("--size", type=int, default=64)
    tx_p.add_argument("--duration", type=float, required=True)
    tx_p.add_argument("--out", type=Path, required=True)

    an_p = sub.add_parser("analyze")
    an_p.add_argument("--tx", type=Path, required=True)
    an_p.add_argument("--rx", type=Path, required=True)
    an_p.add_argument("--window-start", type=float, required=True)
    an_p.add_argument("--window-end", type=float, required=True)
    an_p.add_argument("--json-out", type=Path)

    args = parser.parse_args()
    if args.mode == "recv":
        return run_receiver(args.bind, args.port, args.duration, args.out)
    if args.mode == "send":
        return run_sender(args.dst, args.port, args.rate, args.size, args.duration, args.out)
    stats = analyze_window(args.tx, args.rx, args.window_start, args.window_end)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
