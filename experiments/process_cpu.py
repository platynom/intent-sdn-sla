#!/usr/bin/env python3
"""Snapshot inclusive CPU ticks for named Linux process trees."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Dict, Mapping, Optional


def _read_stat(path: Path) -> Optional[dict[str, int]]:
    """Read the fields needed from one ``/proc/<pid>/stat`` file."""
    try:
        fields = path.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError):
        return None
    return {
        "ppid": int(fields[1]),
        "self_ticks": int(fields[11]) + int(fields[12]),
        "child_ticks": int(fields[13]) + int(fields[14]),
    }


def read_process_table(proc_root: Path = Path("/proc")) -> Dict[int, dict[str, int]]:
    """Return the process table entries that remain readable during the scan."""
    stats: Dict[int, dict[str, int]] = {}
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        stat = _read_stat(entry / "stat")
        if stat is not None:
            stats[int(entry.name)] = stat
    return stats


def inclusive_ticks(root_pid: int, stats: Mapping[int, Mapping[str, int]]) -> int:
    """Count a root's own, reaped-child, and live-descendant CPU ticks."""
    if root_pid <= 0 or root_pid not in stats:
        return 0
    descendants = []
    frontier = [root_pid]
    while frontier:
        parent = frontier.pop()
        children = [pid for pid, stat in stats.items() if stat["ppid"] == parent]
        descendants.extend(children)
        frontier.extend(children)
    all_live = [root_pid, *descendants]
    return sum(
        stats[pid]["self_ticks"] + stats[pid]["child_ticks"]
        for pid in all_live
    )


def snapshot_components(
    component_pids: Mapping[str, int],
    proc_root: Path = Path("/proc"),
) -> dict:
    """Capture inclusive CPU ticks for each named process tree."""
    stats = read_process_table(proc_root)
    return {
        "clock_ticks_per_s": os.sysconf(os.sysconf_names["SC_CLK_TCK"]),
        "monotonic_s": time.perf_counter(),
        "components": {
            label: inclusive_ticks(pid, stats)
            for label, pid in component_pids.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--component",
        action="append",
        default=[],
        metavar="NAME=PID",
        help="named root process; repeat for each component",
    )
    args = parser.parse_args()
    component_pids: dict[str, int] = {}
    for value in args.component:
        label, pid_s = value.split("=", 1)
        component_pids[label] = int(pid_s or 0)
    print(json.dumps(snapshot_components(component_pids), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
