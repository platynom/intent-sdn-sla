#!/usr/bin/env python3
"""E14: Contention-safe recovery evaluation (Proposition 6) across commits."""

from __future__ import annotations

import argparse
import csv
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List


class _FakeController:
    def __init__(self) -> None:
        self.port_map: dict = {}
        self.calls: list = []

    def install_plan(self, plan, intent, bus=None):
        self.calls.append((plan, intent))
        return 2 * len(plan.switches)


class _AsgiResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        import json

        self.status_code = status_code
        self.content = body
        self.text = body.decode("utf-8", errors="replace")
        self._json = json

    def json(self):
        return self._json.loads(self.text)


class _AsgiClient:
    """Fallback ASGI caller if TestClient/httpx is unavailable or incompatible."""

    def __init__(self, app) -> None:
        self.app = app

    def post(self, path: str, *, json=None, content=None, headers=None):
        import asyncio
        import json as _json

        raw_headers = []
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        if json is not None:
            body = _json.dumps(json).encode("utf-8")
            hdrs.setdefault("content-type", "application/json")
        elif isinstance(content, bytes):
            body = content
        elif isinstance(content, str):
            body = content.encode("utf-8")
        else:
            body = b""
        for k, v in hdrs.items():
            raw_headers.append((k.encode("latin-1"), str(v).encode("latin-1")))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": raw_headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        sent = False
        status_code = 500
        chunks: List[bytes] = []

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        asyncio.run(self.app(scope, receive, send))
        return _AsgiResponse(status_code, b"".join(chunks))


def _make_client(app):
    try:
        from fastapi.testclient import TestClient

        return TestClient(app)
    except Exception:
        return _AsgiClient(app)


def _route_label(switches: tuple[str, ...]) -> str:
    if switches == ("s1", "s2", "s3", "s7"):
        return "north"
    if switches == ("s1", "s4", "s5", "s7"):
        return "middle"
    if switches == ("s1", "s6", "s7"):
        return "south"
    return "-".join(switches)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--tag", default=None, help="Override raw prefix tag (e.g. old or new)")
    parser.add_argument("--raw-dir", type=Path, default=Path("experiments/results/raw"))
    parser.add_argument("--runs", type=int, default=10)
    args = parser.parse_args()

    repo_abs = str(args.repo.resolve())
    tag = args.tag or ("old" if "cf25af2" in repo_abs else "new")

    # Set TEAM16_DB_PATH BEFORE importing anything from src.
    tmp_root = Path(tempfile.mkdtemp(prefix=f"team16-e14-{tag}-"))
    os.environ["TEAM16_DB_PATH"] = str(tmp_root / "init.db")

    # Prioritize --repo on sys.path before any src/topology import.
    sys.path = [p for p in sys.path if p not in ("", "/app", str(Path(__file__).resolve().parents[1]))]
    sys.path.insert(0, repo_abs)

    import src  # noqa: E402
    assert Path(src.__file__).resolve().is_relative_to(Path(repo_abs)), (
        f"Expected src under {repo_abs}, got {src.__file__}"
    )

    from src.common import db as dbm  # noqa: E402
    from src.common.audit import AuditLog  # noqa: E402
    from src.common.events import EventBus, sla_violated  # noqa: E402
    from src.intent_manager.api import app as api_app  # noqa: E402
    from src.telemetry.loop import ControlLoop  # noqa: E402
    from topology.topology_spec import build_graph  # noqa: E402

    args.raw_dir.mkdir(parents=True, exist_ok=True)
    base_graph = build_graph()
    link_caps: Dict[str, float] = {}
    for u, v, data in base_graph.edges(data=True):
        lo, hi = sorted((u, v), key=lambda s: int(s[1:]))
        link_caps[f"{lo}-{hi}"] = float(data["bw_mbps"])

    try:
        for n_intents in (4, 8, 12, 16):
            bw_floor = 80.0 / float(n_intents)
            for seed in range(1, args.runs + 1):
                db_file = tmp_root / f"e14_{tag}_n{n_intents}_s{seed}.db"
                if db_file.exists():
                    db_file.unlink()
                os.environ["TEAM16_DB_PATH"] = str(db_file)

                conn = dbm.connect()
                dbm.init_db(conn)
                client = _make_client(api_app)

                intent_ids: List[str] = []
                for idx in range(1, n_intents + 1):
                    iid = f"INT-{100 + idx:03d}"
                    intent_ids.append(iid)
                    yaml_body = f"""intent:
  id: {iid}
  tenant: t{idx}
  priority: 2
  match:
    src: 10.0.0.1/32
    dst: 10.0.0.2/32
    proto: udp
    dport: {5100 + idx}
  guarantee:
    min_bandwidth_mbps: {bw_floor:.6f}
    max_latency_ms: 35
  consistency: relaxed
  on_violation: reroute
  dwell_seconds: 0
"""
                    resp = client.post(
                        "/intent",
                        content=yaml_body,
                        headers={"Content-Type": "text/plain"},
                    )
                    assert resp.status_code == 201, f"{tag} N={n_intents} {iid}: {resp.status_code} {resp.text}"
                    payload = resp.json()
                    assert payload["switches"] in (
                        ["s1", "s2", "s3", "s7"],
                        ["s1", "s4", "s5", "s7"],
                        ["s1", "s6", "s7"],
                    ), payload

                init_counts = {"north": 0, "middle": 0, "south": 0, "other": 0}
                for iid in intent_ids:
                    init_plan = dbm.current_path(conn, iid)
                    assert init_plan is not None
                    lbl = _route_label(tuple(init_plan.switches))
                    init_counts[lbl if lbl in init_counts else "other"] += 1

                # Pass 1: fault all intents in random order
                loop = ControlLoop(
                    conn, build_graph(), _FakeController(), EventBus(), AuditLog(conn)
                )
                order = list(intent_ids)
                random.Random(seed).shuffle(order)
                t_trigger = time.time() + 1000.0
                for step_idx, iid in enumerate(order):
                    loop.on_violation(
                        sla_violated(iid, "delay_ms", 99.0, 35.0),
                        now=t_trigger + step_idx * 0.001,
                    )

                reserved: Dict[str, float] = {k: 0.0 for k in link_caps}
                route_counts = {"north": 0, "middle": 0, "south": 0, "other": 0}
                for iid in intent_ids:
                    rec = dbm.load_intent(conn, iid)
                    plan = dbm.current_path(conn, iid)
                    assert rec is not None and plan is not None
                    lbl = _route_label(tuple(plan.switches))
                    if lbl in route_counts:
                        route_counts[lbl] += 1
                    else:
                        route_counts["other"] += 1
                    floor = float(rec.guarantee.min_bandwidth_mbps or 0.0)
                    for link in plan.links:
                        reserved[link] = reserved.get(link, 0.0) + floor

                conn.close()

                overcommitted = sum(
                    1 for link, cap in link_caps.items() if reserved.get(link, 0.0) > cap + 1e-6
                )
                max_ratio = max(
                    reserved.get(link, 0.0) / cap for link, cap in link_caps.items()
                )
                north_reserved = max(reserved["s1-s2"], reserved["s2-s3"], reserved["s3-s7"])
                mid_reserved = max(reserved["s1-s4"], reserved["s4-s5"], reserved["s5-s7"])
                south_reserved = max(reserved["s1-s6"], reserved["s6-s7"])

                # Pass 2: fault only intents initially on North (s1-eth2 fault model)
                db_file_nf = tmp_root / f"e14_{tag}_n{n_intents}_s{seed}_nf.db"
                if db_file_nf.exists():
                    db_file_nf.unlink()
                os.environ["TEAM16_DB_PATH"] = str(db_file_nf)

                conn_nf = dbm.connect()
                dbm.init_db(conn_nf)
                client_nf = _make_client(api_app)
                for idx in range(1, n_intents + 1):
                    iid = f"INT-{100 + idx:03d}"
                    yaml_body = f"""intent:
  id: {iid}
  tenant: t{idx}
  priority: 2
  match:
    src: 10.0.0.1/32
    dst: 10.0.0.2/32
    proto: udp
    dport: {5100 + idx}
  guarantee:
    min_bandwidth_mbps: {bw_floor:.6f}
    max_latency_ms: 35
  consistency: relaxed
  on_violation: reroute
  dwell_seconds: 0
"""
                    resp = client_nf.post(
                        "/intent",
                        content=yaml_body,
                        headers={"Content-Type": "text/plain"},
                    )
                    assert resp.status_code == 201, f"{tag} NF N={n_intents} {iid}: {resp.status_code} {resp.text}"

                north_iids = []
                for iid in intent_ids:
                    init_plan = dbm.current_path(conn_nf, iid)
                    assert init_plan is not None
                    if tuple(init_plan.switches) == ("s1", "s2", "s3", "s7"):
                        north_iids.append(iid)

                loop_nf = ControlLoop(
                    conn_nf, build_graph(), _FakeController(), EventBus(), AuditLog(conn_nf)
                )
                order_nf = list(north_iids)
                random.Random(seed).shuffle(order_nf)
                t_trigger_nf = time.time() + 1000.0
                for step_idx, iid in enumerate(order_nf):
                    loop_nf.on_violation(
                        sla_violated(iid, "delay_ms", 99.0, 35.0),
                        now=t_trigger_nf + step_idx * 0.001,
                    )

                nf_reserved: Dict[str, float] = {k: 0.0 for k in link_caps}
                nf_counts = {"north": 0, "middle": 0, "south": 0, "other": 0}
                for iid in intent_ids:
                    rec = dbm.load_intent(conn_nf, iid)
                    plan = dbm.current_path(conn_nf, iid)
                    assert rec is not None and plan is not None
                    lbl = _route_label(tuple(plan.switches))
                    nf_counts[lbl if lbl in nf_counts else "other"] += 1
                    floor = float(rec.guarantee.min_bandwidth_mbps or 0.0)
                    for link in plan.links:
                        nf_reserved[link] = nf_reserved.get(link, 0.0) + floor

                conn_nf.close()

                nf_overcommitted = sum(
                    1 for link, cap in link_caps.items() if nf_reserved.get(link, 0.0) > cap + 1e-6
                )
                nf_max_ratio = max(
                    nf_reserved.get(link, 0.0) / cap for link, cap in link_caps.items()
                )
                nf_mid_reserved = max(nf_reserved["s1-s4"], nf_reserved["s4-s5"], nf_reserved["s5-s7"])
                nf_south_reserved = max(nf_reserved["s1-s6"], nf_reserved["s6-s7"])

                out_path = args.raw_dir / f"redfill_e14_{tag}_N{n_intents:02d}_seed{seed:02d}.csv"
                now_ts = int(time.time())
                with out_path.open("w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["run_id", "timestamp", "metric", "value", "unit"])
                    w.writerow([seed, now_ts, "n_intents", n_intents, "count"])
                    w.writerow([seed, now_ts, "initial_on_north", init_counts["north"], "count"])
                    w.writerow([seed, now_ts, "initial_on_middle", init_counts["middle"], "count"])
                    w.writerow([seed, now_ts, "initial_on_south", init_counts["south"], "count"])
                    w.writerow([seed, now_ts, "overcommitted_links", overcommitted, "count"])
                    w.writerow([seed, now_ts, "max_reserved_capacity_ratio", f"{max_ratio:.6f}", "ratio"])
                    w.writerow([seed, now_ts, "intents_on_north", route_counts["north"], "count"])
                    w.writerow([seed, now_ts, "intents_on_middle", route_counts["middle"], "count"])
                    w.writerow([seed, now_ts, "intents_on_south", route_counts["south"], "count"])
                    w.writerow([seed, now_ts, "north_reserved_mbps", f"{north_reserved:.6f}", "Mbps"])
                    w.writerow([seed, now_ts, "middle_reserved_mbps", f"{mid_reserved:.6f}", "Mbps"])
                    w.writerow([seed, now_ts, "south_reserved_mbps", f"{south_reserved:.6f}", "Mbps"])
                    w.writerow([seed, now_ts, "northfault_overcommitted_links", nf_overcommitted, "count"])
                    w.writerow([seed, now_ts, "northfault_max_reserved_capacity_ratio", f"{nf_max_ratio:.6f}", "ratio"])
                    w.writerow([seed, now_ts, "northfault_intents_on_north", nf_counts["north"], "count"])
                    w.writerow([seed, now_ts, "northfault_intents_on_middle", nf_counts["middle"], "count"])
                    w.writerow([seed, now_ts, "northfault_intents_on_south", nf_counts["south"], "count"])
                    w.writerow([seed, now_ts, "northfault_middle_reserved_mbps", f"{nf_mid_reserved:.6f}", "Mbps"])
                    w.writerow([seed, now_ts, "northfault_south_reserved_mbps", f"{nf_south_reserved:.6f}", "Mbps"])

                print(
                    f"E14 {tag} N={n_intents:2d} seed={seed:2d}: "
                    f"overcommitted={overcommitted} max_ratio={max_ratio:.3f} "
                    f"routes(N/M/S)={route_counts['north']}/{route_counts['middle']}/{route_counts['south']} "
                    f"-> {out_path}"
                )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
