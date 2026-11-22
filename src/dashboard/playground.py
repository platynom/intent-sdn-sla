"""Hands-on intent playground for the M6 dashboard.

Lets a person type an intent, see how the controller would decide (dry run),
and submit or withdraw it through the real M1 intent API.

* ``POST /api/try/plan`` is a pure dry run. It reuses the production validator,
  admission (M2) and pruning (M3) code on the current database state and never
  writes to the database. Optional "what-if" faults (a link down, or extra delay
  on a link) are applied to a copy of the topology graph only; they do not touch
  Mininet or Open vSwitch.
* ``POST /api/try/submit`` and ``POST /api/try/withdraw/{id}`` forward to the
  intent API (``TEAM16_INTENT_API_URL``), so every API safeguard (64 KiB body
  limit, bearer auth, duplicate-ID and overlap 409s) still applies.
* ``TEAM16_DASHBOARD_READONLY=1`` disables submit and withdraw.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.admission.feasibility import assess
from src.admission.residual import residual_graph, tenant_paths
from src.common import db
from src.common.models import IntentRecord, PathPlan
from src.intent_manager.validator import matches_overlap, validate
from src.pathing.compute import _resolve_ip_to_switch
from src.pathing.prune import prune
from src.pathing.yen_ksp import k_shortest_paths
from topology.topology_spec import HOSTS, LINKS, SWITCHES, build_graph

router = APIRouter()

MAX_YAML_BYTES = 64 * 1024
MAX_FAULTS = len(LINKS)
_INTENT_ID = re.compile(r"^INT-[0-9]{3,}$")
_LIVE_STATES = ("pending", "admitted", "active", "degraded")
_LINK_NAMES = {link.name for link in LINKS}


class Fault(BaseModel):
    link: str
    mode: str = "down"          # "down" or "delay"
    extra_delay_ms: float = 40.0


class PlanRequest(BaseModel):
    yaml: str
    faults: List[Fault] = []


class SubmitRequest(BaseModel):
    yaml: str


def _api_url() -> str:
    return os.environ.get("TEAM16_INTENT_API_URL", "http://intent-api:8000").rstrip("/")


def _read_only() -> bool:
    return os.environ.get("TEAM16_DASHBOARD_READONLY", "").strip().lower() in ("1", "true", "yes")


def _check_size(text: str) -> None:
    if len(text.encode("utf-8")) > MAX_YAML_BYTES:
        raise HTTPException(status_code=413, detail="Intent text exceeds the 64 KiB limit.")


def _link_name(u: str, v: str) -> str:
    return PathPlan.links_for([u, v])[0]


def _apply_faults(graph: Any, faults: List[Fault]) -> List[Dict[str, Any]]:
    """Apply what-if faults to a graph copy. Returns the faults actually applied."""
    if len(faults) > MAX_FAULTS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_FAULTS} faults.")
    applied: List[Dict[str, Any]] = []
    for fault in faults:
        if fault.link not in _LINK_NAMES:
            raise HTTPException(status_code=422, detail=f"Unknown link {fault.link!r}.")
        a, b = fault.link.split("-")
        if fault.mode == "down":
            if graph.has_edge(a, b):
                graph.remove_edge(a, b)
            applied.append({"link": fault.link, "mode": "down"})
        elif fault.mode == "delay":
            if not 0 < fault.extra_delay_ms <= 1000:
                raise HTTPException(status_code=422, detail="extra_delay_ms must be in (0, 1000].")
            if graph.has_edge(a, b):
                graph[a][b]["delay_ms"] = float(graph[a][b]["delay_ms"]) + fault.extra_delay_ms
            applied.append({"link": fault.link, "mode": "delay",
                            "extra_delay_ms": fault.extra_delay_ms})
        else:
            raise HTTPException(status_code=422, detail="Fault mode must be 'down' or 'delay'.")
    return applied


@router.get("/api/try/topology")
def try_topology() -> Dict[str, Any]:
    """Topology with live reservations: what the admission controller sees now."""
    conn = db.connect()
    try:
        db.init_db(conn)
        residual = residual_graph(conn)
        down = db.down_links(conn)
        links = []
        for link in LINKS:
            data = residual.get_edge_data(link.a, link.b)
            reserved = float(data["reserved_mbps"]) if data else 0.0
            links.append({
                "name": link.name, "a": link.a, "b": link.b,
                "capacity_mbps": link.bw_mbps, "delay_ms": link.delay_ms,
                "reserved_mbps": reserved,
                "residual_mbps": max(0.0, link.bw_mbps - reserved),
                "down": link.name in down or data is None,
            })
        intents = []
        for rec in db.active_intents(conn):
            plan = db.current_path(conn, rec.id)
            intents.append({
                "id": rec.id, "tenant": rec.tenant, "priority": rec.priority,
                "state": rec.state.value,
                "min_bandwidth_mbps": rec.guarantee.min_bandwidth_mbps,
                "switches": list(plan.switches) if plan else [],
            })
        return {
            "switches": list(SWITCHES),
            "hosts": [{"name": h.name, "ip": h.ip, "switch": h.switch, "role": h.role}
                      for h in HOSTS],
            "links": links,
            "intents": intents,
            "read_only": _read_only(),
        }
    finally:
        conn.close()


@router.post("/api/try/plan")
def try_plan(req: PlanRequest) -> Dict[str, Any]:
    """Dry run: how would the controller decide on this intent? Never writes."""
    _check_size(req.yaml)
    try:
        doc = yaml.safe_load(req.yaml)
    except yaml.YAMLError as exc:
        return {"ok": False, "stage": "parse", "would_be_status": 422,
                "errors": [{"path": "(root)", "message": f"Malformed YAML: {exc}"}]}
    result = validate(doc)
    if not result.ok:
        return {"ok": False, "stage": "validation", "would_be_status": 422,
                "errors": [{"path": e.path, "message": e.message} for e in result.errors]}

    rec = IntentRecord.from_document({"intent": result.intent})
    base = build_graph()
    applied = _apply_faults(base, req.faults)

    conn = db.connect()
    try:
        db.init_db(conn)
        warnings: List[str] = []
        would_be_status = 201
        existing = db.load_intent(conn, rec.id)
        if existing is not None and existing.state.value in _LIVE_STATES:
            would_be_status = 409
            warnings.append(f"{rec.id} already exists in state '{existing.state.value}'. "
                            "Submitting would be refused (409); withdraw it first or use a new ID.")
        decision, plan = assess(conn, rec, base)

        # Same overlap rule as the API (audit fix D5): an overlapping live intent
        # is refused unless it is the single lower-priority intent being preempted.
        overlapping = [other for other in db.active_intents(conn)
                       if other.id != rec.id and matches_overlap(rec.match, other.match)]
        victim = decision.preempted_intent_id if len(overlapping) == 1 else None
        for other in overlapping:
            if other.id == victim:
                continue
            would_be_status = 409
            warnings.append(f"Traffic match overlaps live intent {other.id} "
                            f"(tenant {other.tenant}). Submitting would be refused (409); "
                            "change the source, destination, protocol or port.")

        # Per-candidate explanation on the same residual graph M2 uses.
        available = residual_graph(conn, base, exclude_intent_ids={rec.id})
        isolation = tenant_paths(conn, exclude_intent_ids={rec.id})
        src_sw = _resolve_ip_to_switch(rec.match.src)
        dst_sw = _resolve_ip_to_switch(rec.match.dst)
        candidates: List[Dict[str, Any]] = []
        if src_sw and dst_sw:
            if src_sw == dst_sw:
                paths = [[src_sw]]
            else:
                try:
                    paths = k_shortest_paths(available, source=src_sw, target=dst_sw,
                                             k=3, weight="delay_ms")
                except Exception:
                    paths = []
            for path in paths:
                delay = sum(float(available[u][v]["delay_ms"]) for u, v in zip(path, path[1:]))
                residual = min((float(available[u][v]["residual_mbps"])
                                for u, v in zip(path, path[1:])), default=None)
                _, reasons = prune([path], rec.guarantee, available, isolation, rec.tenant)
                reason = reasons.get("-".join(path))
                candidates.append({
                    "switches": path,
                    "links": list(PathPlan.links_for(path)) if len(path) > 1 else [],
                    "delay_ms": round(delay, 3),
                    "residual_mbps": residual,
                    "feasible": reason is None,
                    "reason": reason or "meets every requested guarantee",
                    "chosen": plan is not None and list(plan.switches) == path,
                })

        return {
            "ok": True,
            "intent": {
                "id": rec.id, "tenant": rec.tenant, "priority": rec.priority,
                "src": rec.match.src, "dst": rec.match.dst,
                "src_switch": src_sw, "dst_switch": dst_sw,
                "consistency": rec.consistency.value,
                "on_violation": rec.on_violation.value,
                "guarantee": {
                    "min_bandwidth_mbps": rec.guarantee.min_bandwidth_mbps,
                    "max_latency_ms": rec.guarantee.max_latency_ms,
                    "max_loss_pct": rec.guarantee.max_loss_pct,
                    "avoid_links": list(rec.guarantee.avoid_links or []),
                    "isolate_from": list(rec.guarantee.isolate_from or []),
                },
            },
            "decision": {
                "verdict": decision.verdict.value,
                "reason": decision.reason,
                "preempted_intent_id": decision.preempted_intent_id,
            },
            "chosen": None if plan is None else {
                "switches": list(plan.switches), "links": list(plan.links),
                "est_latency_ms": plan.est_latency_ms,
                "bottleneck_mbps": plan.bottleneck_mbps,
            },
            "candidates": candidates,
            "faults_applied": applied,
            "warnings": warnings,
            "would_be_status": would_be_status,
        }
    finally:
        conn.close()


def _forward(method: str, path: str, body: Optional[bytes] = None) -> Dict[str, Any]:
    headers = {"Content-Type": "text/plain"}
    token = os.environ.get("TEAM16_DASHBOARD_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(_api_url() + path, data=body, method=method,
                                     headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        raise HTTPException(status_code=502,
                            detail=f"Intent API at {_api_url()} is unreachable: {exc}")
    text = raw.decode("utf-8", errors="replace")
    try:
        parsed: Any = json.loads(text) if text else None
    except ValueError:
        parsed = text
    return {"status": status, "body": parsed}


@router.post("/api/try/submit")
def try_submit(req: SubmitRequest) -> Dict[str, Any]:
    """Send the intent to the real M1 API and return its HTTP status and body."""
    if _read_only():
        raise HTTPException(status_code=403, detail="Dashboard is in read-only mode.")
    _check_size(req.yaml)
    return _forward("POST", "/intent", req.yaml.encode("utf-8"))


@router.post("/api/try/withdraw/{intent_id}")
def try_withdraw(intent_id: str) -> Dict[str, Any]:
    """Withdraw an intent through the real M1 API (DELETE /intent/{id})."""
    if _read_only():
        raise HTTPException(status_code=403, detail="Dashboard is in read-only mode.")
    if not _INTENT_ID.match(intent_id):
        raise HTTPException(status_code=422, detail="Intent ID must look like INT-123.")
    return _forward("DELETE", f"/intent/{intent_id}")


@router.get("/try", response_class=HTMLResponse)
def try_page() -> str:
    """Serve the hands-on page."""
    from src.dashboard.playground_page import PLAYGROUND_HTML
    return PLAYGROUND_HTML
