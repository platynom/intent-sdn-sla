"""
M1 REST API: POST /intent, DELETE /intent/{id}, GET /intents.

Provides HTTP interface for intent ingestion, path computation trigger,
intent state inspection, and withdrawal.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from src.common import db as dbm
from src.common.events import Event, EventBus, EventType
from src.common.models import (
    AdmissionDecision, Consistency, IntentRecord, IntentState, Verdict, to_dict,
)
from src.enforcement import queues, two_phase
from src.admission.feasibility import assess, reconcile_preempted_intents
from src.intent_manager.validator import matches_overlap, validate
from src.intent_manager.profiles import build_intent, check_against_profile, list_profiles
from src.pathing.compute import compute_path
from topology.topology_spec import build_graph

app = FastAPI(title="M1 Intent Manager API")

# Shared event bus for publishing lifecycle events
event_bus = EventBus()


def _admission_for_request(conn, intent, graph):
    """Apply production admission, or the explicit ST-12 B2 ablation profile."""
    if os.environ.get("TEAM16_EXPERIMENT_MODE", "").lower() != "b2":
        return assess(conn, intent, graph)

    # B2 ignores existing tenant reservations and conflicting admissions, but
    # still requires this intent's own guarantees to have a feasible topology path.
    plan, reasons = compute_path(intent, graph)
    if plan is not None:
        return AdmissionDecision(
            intent.id,
            Verdict.ADMIT,
            "B2 experiment profile: reservation/conflict checks bypassed; "
            "the intent has an individually feasible path.",
        ), plan
    detail = "; ".join(f"{path}: {reason}" for path, reason in sorted(reasons.items()))
    return AdmissionDecision(
        intent.id,
        Verdict.REJECT,
        f"B2 experiment profile: no individually feasible path. {detail}".strip(),
    ), None


def get_db():
    """Dependency that supplies a database connection per request."""
    conn = dbm.connect()
    try:
        yield conn
    finally:
        conn.close()


@app.post("/intent", status_code=status.HTTP_201_CREATED)
async def create_intent(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    """
    Ingest a new intent document as YAML (text/plain) or JSON.

    Validates schema and semantics. On success, persists intent, emits INTENT_RECEIVED,
    computes path, updates/saves path, and returns 201 with intent details and path/reasons.
    """
    content_type = request.headers.get("content-type", "")
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")

    doc: Any = None
    if "application/json" in content_type:
        try:
            doc = await request.json()
        except Exception:
            try:
                doc = yaml.safe_load(body_str)
            except Exception:
                doc = body_str
    else:
        # Default to yaml parsing (covers text/plain, text/yaml, application/x-yaml, etc.)
        try:
            doc = yaml.safe_load(body_str)
        except Exception as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=[{"path": "(root)", "message": f"Malformed YAML: {exc}"}],
            )

    result = validate(doc)
    if not result.ok:
        error_payload = [{"path": e.path, "message": e.message} for e in result.errors]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_payload,
        )

    # Document is valid: construct IntentRecord
    # result.intent is the validated dict
    rec = IntentRecord.from_document({"intent": result.intent})
    rec.state = IntentState.PENDING
    dbm.save_intent(conn, rec)

    # Emit INTENT_RECEIVED event
    event_bus.publish(
        Event(
            type=EventType.INTENT_RECEIVED,
            intent_id=rec.id,
            message=f"Intent {rec.id} received from tenant {rec.tenant}",
            payload={"intent_id": rec.id, "tenant": rec.tenant, "priority": rec.priority},
        )
    )

    # M2 admission uses the persisted active paths to account for reservations.
    graph = build_graph()
    decision, plan = _admission_for_request(conn, rec, graph)
    if plan is not None and rec.consistency is Consistency.STRICT:
        plan = two_phase.with_version(plan, two_phase.next_version())
    rec.state = IntentState.ADMITTED if decision.admitted else IntentState.REJECTED
    dbm.save_intent(conn, rec)
    decision_event = Event(
        type=EventType.ADMISSION_DECIDED,
        intent_id=rec.id,
        message=decision.reason,
        payload={
            "verdict": decision.verdict.value,
            "reason": decision.reason,
            "preempted_intent_id": decision.preempted_intent_id,
        },
    )
    dbm.save_event(conn, decision_event)
    event_bus.publish(decision_event)

    if decision.verdict.value == "preempt" and decision.preempted_intent_id:
        victim = dbm.load_intent(conn, decision.preempted_intent_id)
        if victim is not None:
            victim.state = IntentState.PREEMPTED
            dbm.save_intent(conn, victim)
            preempted_event = Event(
                type=EventType.INTENT_PREEMPTED,
                intent_id=victim.id,
                message=(f"Intent {victim.id} was preempted by higher-priority "
                         f"intent {rec.id}: {decision.reason}"),
                payload={"by_intent_id": rec.id, "reason": decision.reason},
            )
            dbm.save_event(conn, preempted_event)
            event_bus.publish(preempted_event)

    response_data: Dict[str, Any] = {
        "id": rec.id,
        "tenant": rec.tenant,
        "priority": rec.priority,
        "state": rec.state.value,
    }
    if decision.preempted_intent_id:
        response_data["preempted_intent_id"] = decision.preempted_intent_id

    if plan is not None:
        dbm.save_path(conn, plan)
        rec.current_path = plan
        response_data["path"] = list(plan.links)
        response_data["switches"] = list(plan.switches)
        response_data["est_latency_ms"] = plan.est_latency_ms
        response_data["bottleneck_mbps"] = plan.bottleneck_mbps
        event_bus.publish(
            Event(
                type=EventType.PATH_COMPUTED,
                intent_id=rec.id,
                message=f"Path computed for {rec.id}: {' -> '.join(plan.switches)}",
                payload={"links": list(plan.links), "switches": list(plan.switches)},
            )
        )
    else:
        response_data["reasons"] = {"admission": decision.reason}
        event_bus.publish(
            Event(
                type=EventType.PATH_INFEASIBLE,
                intent_id=rec.id,
                message=f"No feasible path for {rec.id}",
                payload={"reasons": response_data["reasons"]},
            )
        )

    return JSONResponse(status_code=status.HTTP_201_CREATED, content=response_data)


_baseline_create_intent = create_intent
_MAX_POST_BODY_BYTES = 64 * 1024
_LIVE_CONFLICT_STATES = (
    IntentState.PENDING.value,
    IntentState.ADMITTED.value,
    IntentState.ACTIVE.value,
    IntentState.DEGRADED.value,
)


def _configured_api_tokens() -> Dict[str, str]:
    """Parse TEAM16_API_TOKENS ('tenant=token,...') into a token -> tenant lookup."""
    raw = os.environ.get("TEAM16_API_TOKENS", "").strip()
    if not raw:
        return {}
    token_to_tenant: Dict[str, str] = {}
    for entry in raw.replace(";", ",").split(","):
        item = entry.strip()
        if not item or "=" not in item:
            continue
        tenant, token = item.split("=", 1)
        tenant = tenant.strip()
        token = token.strip()
        if tenant and token:
            token_to_tenant[token] = tenant
    return token_to_tenant


def _authenticate_bearer(request: Request) -> str | None:
    """Return authenticated tenant when TEAM16_API_TOKENS is set, or raise/return None."""
    tokens = _configured_api_tokens()
    if not tokens:
        return None
    auth = request.headers.get("authorization", "") if hasattr(request, "headers") else ""
    if not auth.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization Bearer token.",
        )
    token = auth[7:].strip()
    tenant = tokens.get(token)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization Bearer token.",
        )
    return tenant


async def _guarded_create_intent(
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Enforce body size (P8), Bearer auth (M3), duplicate-ID (D6), and match overlap (D5)."""
    body_bytes = await request.body()
    if len(body_bytes) > _MAX_POST_BODY_BYTES:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": f"Request body exceeds {_MAX_POST_BODY_BYTES} byte (64 KiB) limit."},
        )

    try:
        authed_tenant = _authenticate_bearer(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    content_type = request.headers.get("content-type", "")
    try:
        body_str = body_bytes.decode("utf-8")
    except Exception:
        return await _baseline_create_intent(request, conn)

    doc: Any = None
    if "application/json" in content_type:
        try:
            doc = await request.json()
        except Exception:
            try:
                doc = yaml.safe_load(body_str)
            except Exception:
                doc = body_str
    else:
        try:
            doc = yaml.safe_load(body_str)
        except Exception:
            return await _baseline_create_intent(request, conn)

    result = validate(doc)
    if not result.ok:
        return await _baseline_create_intent(request, conn)

    rec = IntentRecord.from_document({"intent": result.intent})
    if authed_tenant is not None and rec.tenant != authed_tenant:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "detail": (
                    f"Authenticated tenant '{authed_tenant}' is not permitted "
                    f"to create intents for tenant '{rec.tenant}'."
                )
            },
        )

    # D6: Reject overwriting any existing intent unless it is withdrawn or rejected.
    existing = dbm.load_intent(conn, rec.id)
    if existing is not None:
        if existing.state not in (IntentState.WITHDRAWN, IntentState.REJECTED):
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": (
                        f"Intent {rec.id} already exists in state '{existing.state.value}'; "
                        "updating a live intent is not supported."
                    )
                },
            )
        # Clear any old path rows so a re-created withdrawn/rejected intent never self-conflicts.
        conn.execute("DELETE FROM paths WHERE intent_id = ?", (rec.id,))
        conn.commit()

    # D5: Reject identical or overlapping forward/reverse flow match with live intents.
    if os.environ.get("TEAM16_EXPERIMENT_MODE", "").lower() != "b2":
        placeholders = ",".join("?" for _ in _LIVE_CONFLICT_STATES)
        rows = conn.execute(
            f"SELECT * FROM intents WHERE id != ? AND state IN ({placeholders}) ORDER BY created_at ASC",
            (rec.id, *_LIVE_CONFLICT_STATES),
        ).fetchall()
        overlapping = [
            dbm._row_to_intent(row)
            for row in rows
            if matches_overlap(rec.match, dbm._row_to_intent(row).match)
        ]
        if overlapping:
            preempted_id = None
            if len(overlapping) == 1 and overlapping[0].priority > rec.priority:
                decision, _ = assess(conn, rec, build_graph())
                if decision.verdict is Verdict.PREEMPT:
                    preempted_id = decision.preempted_intent_id
            conflict = next((item for item in overlapping if item.id != preempted_id), None)
            if conflict is not None:
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={
                        "detail": (
                            f"Intent {rec.id} match overlaps with existing intent {conflict.id} "
                            f"(state={conflict.state.value})."
                        )
                    },
                )

    resp = await _baseline_create_intent(request, conn)
    try:
        payload = json.loads(resp.body)
        preempted_victim = payload.get("preempted_intent_id")
        if preempted_victim:
            queues.remove_intent_queues(conn, str(preempted_victim), ignore_errors=True)
    except Exception:
        pass
    return resp


create_intent = _guarded_create_intent
for _route in app.router.routes:
    if getattr(_route, "path", None) == "/intent" and "POST" in getattr(_route, "methods", set()):
        _route.endpoint = _guarded_create_intent
        _route.dependant.call = _guarded_create_intent


@app.get("/intents")
def list_intents(conn: sqlite3.Connection = Depends(get_db)) -> List[Dict[str, Any]]:
    """Return all intents, newest first."""
    rows = conn.execute("SELECT * FROM intents ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        rec = dbm._row_to_intent(r)
        plan = dbm.current_path(conn, rec.id)
        d = to_dict(rec)
        d["current_path"] = to_dict(plan) if plan else None
        out.append(d)
    return out


@app.get("/intent/{intent_id}")
def get_intent(intent_id: str, conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    """Retrieve one intent and its current path. Returns 404 if unknown."""
    rec = dbm.load_intent(conn, intent_id)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Intent {intent_id} not found")
    plan = dbm.current_path(conn, intent_id)
    d = to_dict(rec)
    d["current_path"] = to_dict(plan) if plan else None
    return d


@app.delete("/intent/{intent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_intent(
    intent_id: str,
    request: Request = None,  # type: ignore[assignment]
    conn: sqlite3.Connection = Depends(get_db),
):
    """Withdraw an intent. Sets state to WITHDRAWN, emits INTENT_WITHDRAWN, and triggers M2 re-admission."""
    authed_tenant = _authenticate_bearer(request) if request is not None else None
    rec = dbm.load_intent(conn, intent_id)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Intent {intent_id} not found")
    if authed_tenant is not None and rec.tenant != authed_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Authenticated tenant '{authed_tenant}' cannot withdraw intent owned by '{rec.tenant}'.",
        )

    rec.state = IntentState.WITHDRAWN
    dbm.save_intent(conn, rec)
    dbm.clear_degraded_rate(conn, intent_id)
    queues.remove_intent_queues(conn, intent_id, ignore_errors=True)

    withdrawn_event = Event(
        type=EventType.INTENT_WITHDRAWN,
        intent_id=intent_id,
        message=f"Intent {intent_id} withdrawn",
        payload={"intent_id": intent_id},
    )
    dbm.save_event(conn, withdrawn_event)
    event_bus.publish(withdrawn_event)
    reconcile_preempted_intents(conn, build_graph(), event_bus)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/health")
def health(conn: sqlite3.Connection = Depends(get_db)) -> Dict[str, Any]:
    """Health check returning intent count."""
    row = conn.execute("SELECT COUNT(*) AS count FROM intents").fetchone()
    count = int(row["count"]) if row else 0
    return {"status": "ok", "intents": count}


@app.get("/profiles")
def service_profiles() -> List[dict]:
    """Expose pinned source values, assumptions, and transport-budget derivations."""
    return list_profiles()


@app.post("/intent/from-profile", status_code=status.HTTP_201_CREATED)
async def create_from_profile(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Generate a normal intent, then use the unchanged POST /intent handler."""
    try:
        parameters = await request.json()
        if not isinstance(parameters, dict):
            raise ValueError("Expected a JSON object containing service_class and intent fields")
        document = build_intent(**parameters)
        warnings = check_against_profile(document, parameters["service_class"])
    except (ValueError, TypeError) as exc:
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            content=[{"path": "profile", "message": str(exc)}])

    async def receive():
        return {"type": "http.request", "body": json.dumps(document).encode("utf-8"),
                "more_body": False}

    scope = dict(request.scope)
    preserved_headers = [
        (k, v)
        for k, v in request.scope.get("headers", [])
        if k.lower() not in (b"content-type", b"content-length")
    ]
    scope["headers"] = [(b"content-type", b"application/json"), *preserved_headers]
    generated_request = Request(scope, receive)
    response = await create_intent(generated_request, conn)
    decision = json.loads(response.body)
    if response.status_code != status.HTTP_201_CREATED:
        return response
    return JSONResponse(status_code=response.status_code,
                        content={**decision, "intent": document["intent"],
                                 "service_class": parameters["service_class"], "warnings": warnings})
