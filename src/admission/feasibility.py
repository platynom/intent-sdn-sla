"""M2's explainable admission feasibility check (preemption is a later stage)."""

from __future__ import annotations

import sqlite3
import time
from typing import List, Optional, Tuple

import networkx as nx

from src.admission.residual import residual_graph, tenant_paths
from src.common import db as dbm
from src.common.events import Event, EventBus, EventType, Severity
from src.common.models import (
    AdmissionDecision,
    Consistency,
    IntentRecord,
    IntentState,
    PathPlan,
    Verdict,
)
from src.enforcement import two_phase
from src.pathing.compute import compute_path


def assess(
    conn: sqlite3.Connection, intent: IntentRecord, graph: Optional[nx.Graph] = None
) -> Tuple[AdmissionDecision, Optional[PathPlan]]:
    """Return ADMIT plus a feasible plan, or REJECT with specific reasons."""
    available = residual_graph(conn, graph, exclude_intent_ids={intent.id})
    plan, reasons = compute_path(
        intent, available, tenant_paths(conn, exclude_intent_ids={intent.id})
    )
    if plan is not None:
        return AdmissionDecision(
            intent.id, Verdict.ADMIT,
            f"Admitted: a feasible path is available with residual capacity for tenant {intent.tenant}.",
        ), plan

    # Priority 1 is highest. A lower-priority active intent may be displaced
    # only when removing its reservation alone makes the request feasible.
    # This keeps the decision explainable and aligns with the existing
    # AdmissionDecision interface, which records one preempted intent.
    victims = sorted(
        (candidate for candidate in dbm.active_intents(conn)
         if candidate.id != intent.id and candidate.priority > intent.priority),
        key=lambda candidate: (-candidate.priority, -candidate.created_at, candidate.id),
    )
    for victim in victims:
        candidate_graph = residual_graph(
            conn, graph, exclude_intent_ids={intent.id, victim.id}
        )
        candidate_plan, _ = compute_path(
            intent,
            candidate_graph,
            tenant_paths(conn, exclude_intent_ids={intent.id, victim.id}),
        )
        if candidate_plan is not None:
            return AdmissionDecision(
                intent.id,
                Verdict.PREEMPT,
                f"Admitted by preempting lower-priority intent {victim.id} "
                f"(priority {victim.priority}) to free residual capacity.",
                preempted_intent_id=victim.id,
            ), candidate_plan
    detail = "; ".join(f"{path}: {reason}" for path, reason in sorted(reasons.items()))
    return AdmissionDecision(
        intent.id, Verdict.REJECT,
        f"Rejected: no path satisfies the requested guarantees. {detail}".strip(),
    ), None


def reconcile_preempted_intents(
    conn: sqlite3.Connection,
    graph: Optional[nx.Graph] = None,
    event_bus: Optional[EventBus] = None,
) -> List[Tuple[IntentRecord, AdmissionDecision, Optional[PathPlan]]]:
    """Re-run admission for preempted intents in priority order when capacity frees up (M2)."""
    rows = conn.execute(
        "SELECT * FROM intents WHERE state = 'preempted' "
        "ORDER BY priority ASC, created_at ASC, id ASC"
    ).fetchall()
    outcomes: List[Tuple[IntentRecord, AdmissionDecision, Optional[PathPlan]]] = []
    for row in rows:
        rec = dbm._row_to_intent(row)
        available = residual_graph(conn, graph, exclude_intent_ids={rec.id})
        plan, reasons = compute_path(
            rec, available, tenant_paths(conn, exclude_intent_ids={rec.id})
        )
        if plan is not None:
            decision = AdmissionDecision(
                rec.id,
                Verdict.ADMIT,
                f"Re-admitted preempted intent {rec.id} after capacity became available.",
            )
            if rec.consistency is Consistency.STRICT:
                old_plan = dbm.current_path(conn, rec.id)
                plan = two_phase.with_version(plan, two_phase.next_version(old_plan))
            rec.state = IntentState.ADMITTED
            rec.updated_at = time.time()
            rec.current_path = plan
            dbm.save_intent(conn, rec)
            dbm.save_path(conn, plan)
            ev = Event(
                type=EventType.ADMISSION_DECIDED,
                intent_id=rec.id,
                message=decision.reason,
                payload={"verdict": decision.verdict.value, "reason": decision.reason, "readmitted": True},
            )
            dbm.save_event(conn, ev)
            if event_bus is not None:
                event_bus.publish(ev)
            outcomes.append((rec, decision, plan))
        else:
            detail = "; ".join(f"{p}: {r}" for p, r in sorted(reasons.items()))
            decision = AdmissionDecision(
                rec.id,
                Verdict.REJECT,
                f"Re-admission deferred for preempted intent {rec.id}: {detail}".strip(),
            )
            ev = Event(
                type=EventType.ADMISSION_DECIDED,
                intent_id=rec.id,
                severity=Severity.WARNING,
                message=decision.reason,
                payload={"verdict": decision.verdict.value, "reason": decision.reason, "readmitted": False},
            )
            dbm.save_event(conn, ev)
            if event_bus is not None:
                event_bus.publish(ev)
            outcomes.append((rec, decision, None))
    return outcomes
