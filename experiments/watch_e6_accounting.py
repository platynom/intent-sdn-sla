"""Read-only snapshots at E6 run boundaries, preserving causal accounting proof.

Start while the isolated E6 process is active. This observer never changes its
SQLite database or network. Historical files present at startup are not paired
with the current run's database.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path


def find_database() -> Path:
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            command = (process / "cmdline").read_bytes().split(b"\0")
            if b"src.telemetry.runtime" not in command or b"INT-006" not in command:
                continue
            environment = (process / "environ").read_bytes().split(b"\0")
            for item in environment:
                if item.startswith(b"TEAM16_DB_PATH="):
                    return Path(item.split(b"=", 1)[1].decode())
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    raise RuntimeError("No isolated INT-006 collector is active")


def main():
    database = find_database()
    raw = Path("experiments/results/raw")
    pattern = "e6accounting_oscillation_b2_*.csv"
    seen = set(raw.glob(pattern))
    destination = Path("experiments/results/diagnostics")
    destination.mkdir(exist_ok=True)
    print(f"Observing {database}; skipping {len(seen)} already completed files", flush=True)
    deadline = time.monotonic() + 2 * 60 * 60
    while time.monotonic() < deadline:
        paths = set(raw.glob(pattern))
        for path in sorted(paths - seen):
            with path.open(newline="") as stream:
                metrics = {r["metric"]: float(r["value"]) for r in csv.DictReader(stream)}
            if "measurement_count" not in metrics:
                continue
            conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                events = [dict(row) for row in conn.execute(
                    "SELECT rowid AS event_order, * FROM events WHERE intent_id = ? ORDER BY at DESC",
                    ("INT-006",),
                )]
                paths_data = [dict(row) for row in conn.execute(
                    "SELECT * FROM paths WHERE intent_id = ? ORDER BY id", ("INT-006",),
                )]
                measurements = conn.execute(
                    "SELECT COUNT(*) FROM measurements WHERE intent_id = ?", ("INT-006",),
                ).fetchone()[0]
            finally:
                conn.close()
            counts = Counter(row["type"] for row in events)
            limited = Counter(row["type"] for row in events[:200])
            reconciles = (
                len(paths_data) - 1 == metrics["raw_reroute_count"]
                and counts["sla.violated"] == metrics["violations_emitted"]
                and measurements == metrics["measurement_count"]
            )
            payload = {"source_csv": path.name, "captured_at": time.time(),
                       "full_event_counts": dict(counts), "latest_200_counts": dict(limited),
                       "path_count": len(paths_data), "measurement_count": measurements,
                       "reconciles_with_csv": reconciles, "events": events, "paths": paths_data}
            target = destination / f"{path.stem}_accounting.json"
            target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(f"{path.name}: full={counts['sla.violated']}, latest200={limited['sla.violated']}, "
                  f"paths={len(paths_data)-1}, samples={measurements}, reconciles={reconciles}", flush=True)
            seen.add(path)
        if len(paths) >= 10:
            return 0
        time.sleep(0.1)
    raise RuntimeError("E6 observer timed out before ten files were present")


if __name__ == "__main__":
    raise SystemExit(main())
