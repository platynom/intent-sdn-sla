"""Closed-loop response from confirmed SLA violations to path enforcement."""

from __future__ import annotations

import inspect
import os
from typing import Optional, Set

from src.admission.feasibility import reconcile_preempted_intents
from src.admission.residual import residual_graph, tenant_paths
from src.common import db
from src.common.events import Event, EventBus, EventType, Severity
from src.common.models import Consistency, IntentState, OnViolation
from src.enforcement import queues, two_phase
from src.pathing.compute import compute_path


class ControlLoop:
    """Recompute and install a safe alternative after a confirmed violation."""

    def __init__(self, conn, graph, controller, bus: EventBus, audit) -> None:
        self.conn = conn
        self.graph = graph
        self.controller = controller
        self.bus = bus
        self.audit = audit
        self._processed_event_ids: Set[str] = set()
        bus.subscribe(self.on_violation, EventType.SLA_VIOLATED)
        bus.subscribe(self.on_restored, EventType.SLA_RESTORED)

    def _audit(self, event, decision, action, event_type, severity=Severity.INFO):
        metric = event.payload.get("metric")
        observed = event.payload.get("observed")
        threshold = event.payload.get("threshold")
        return self.audit.chain(
            event.intent_id,
            f"{metric}={observed}",
            f"{metric}={threshold}",
            decision,
            action,
            severity=severity,
            event_type=event_type,
        )

    def on_violation(self, event: Event, now: Optional[float] = None):
        """Handle one violation synchronously without letting failures escape."""
        if event.type is not EventType.SLA_VIOLATED or not event.intent_id:
            return None
        if event.id in self._processed_event_ids:
            return None

        intent = db.load_intent(self.conn, event.intent_id)
        if intent is None:
            return None
        current = db.current_path(self.conn, intent.id)
        timestamp = event.at if now is None else now

        required = {"metric", "observed", "threshold"}
        if not required.issubset(event.payload):
            self._processed_event_ids.add(event.id)
            return self._audit(
                event,
                "invalid violation event",
                "network unchanged",
                EventType.PATH_INSTALL_FAILED,
                Severity.ERROR,
            )

        if intent.on_violation is OnViolation.ALERT_ONLY:
            self._processed_event_ids.add(event.id)
            return self._audit(
                event, "alert-only policy", "operator alerted; network unchanged",
                EventType.VIOLATION_SUPPRESSED,
            )

        if intent.on_violation is OnViolation.DEGRADE:
            factor = float(os.environ.get("TEAM16_DEGRADE_FACTOR", "0.5"))
            old_rate = float(intent.guarantee.min_bandwidth_mbps or 0.0)
            new_rate = round(old_rate * factor, 6)
            intent.state = IntentState.DEGRADED
            db.save_intent(self.conn, intent)
            if old_rate > 0:
                db.set_degraded_rate(self.conn, intent.id, old_rate, new_rate)
                queues.update_intent_queue_rates(
                    self.conn, intent.id, new_rate, ignore_errors=True
                )
            reconcile_preempted_intents(self.conn, self.graph, self.bus)
            self._processed_event_ids.add(event.id)
            return self._audit(
                event,
                "degrade policy",
                f"intent marked degraded (min_bandwidth_mbps lowered from {old_rate:g} to {new_rate:g} Mbps); path retained",
                EventType.VIOLATION_SUPPRESSED,
            )

        if not intent.may_replan_at(timestamp):
            self._processed_event_ids.add(event.id)
            return self._audit(
                event, "dwell timer active", "current path retained",
                EventType.VIOLATION_SUPPRESSED,
            )

        candidate_graph = residual_graph(
            self.conn, self.graph, exclude_intent_ids={intent.id}
        )
        if current is not None:
            candidate_graph.remove_edges_from(zip(current.switches, current.switches[1:]))
        t_paths = tenant_paths(self.conn, exclude_intent_ids={intent.id})
        if len(inspect.signature(compute_path).parameters) >= 3:
            new_plan, reasons = compute_path(intent, candidate_graph, t_paths)
        else:
            new_plan, reasons = compute_path(intent, candidate_graph)
        if new_plan is None:
            self._processed_event_ids.add(event.id)
            detail = "; ".join(str(value) for value in reasons.values())
            return self._audit(
                event,
                "no feasible alternative",
                f"current path retained: {detail or 'no path-computation reason'}",
                EventType.PATH_INFEASIBLE,
                Severity.WARNING,
            )

        if intent.consistency is Consistency.STRICT:
            new_plan = two_phase.with_version(
                new_plan, two_phase.next_version(current)
            )

        try:
            installed = self.controller.install_plan(new_plan, intent, self.bus)
            expected = 2 * len(new_plan.switches)
            if installed != expected:
                raise RuntimeError(
                    f"installed {installed} of {expected} expected OpenFlow rules"
                )
        except Exception as exc:  # noqa: BLE001 - event subscribers must be isolated
            self._processed_event_ids.add(event.id)
            return self._audit(
                event,
                "alternative installation failed",
                f"current path retained: {exc}",
                EventType.PATH_INSTALL_FAILED,
                Severity.ERROR,
            )

        db.save_path(self.conn, new_plan)
        intent.current_path = new_plan
        intent.last_replan_at = timestamp
        intent.state = IntentState.ACTIVE
        db.save_intent(self.conn, intent)
        reconcile_preempted_intents(self.conn, self.graph, self.bus)
        self._processed_event_ids.add(event.id)
        return self._audit(
            event,
            "feasible alternative selected",
            f"installed {' -> '.join(new_plan.switches)}",
            EventType.PATH_INSTALLED,
        )

    def on_restored(self, event: Event, now: Optional[float] = None):
        """Restore a degraded intent's full rate on SLA_RESTORED when capacity allows (M1)."""
        if event.type is not EventType.SLA_RESTORED or not event.intent_id:
            return None
        if event.id in self._processed_event_ids:
            return None

        intent = db.load_intent(self.conn, event.intent_id)
        if intent is None or intent.state is not IntentState.DEGRADED:
            return None

        full_rate = float(intent.guarantee.min_bandwidth_mbps or 0.0)
        current = db.current_path(self.conn, intent.id)
        if full_rate > 0 and current is not None:
            rg = residual_graph(self.conn, self.graph, exclude_intent_ids={intent.id})
            for u, v in zip(current.switches, current.switches[1:]):
                if not rg.has_edge(u, v) or float(rg[u][v].get("residual_mbps", 0.0)) < full_rate:
                    self._processed_event_ids.add(event.id)
                    return self.audit.chain(
                        intent.id,
                        f"{event.payload.get('metric')}={event.payload.get('observed')}",
                        f"min_bandwidth_mbps={full_rate:g}",
                        "insufficient residual capacity to restore full rate",
                        "intent remains degraded",
                        severity=Severity.WARNING,
                        event_type=EventType.VIOLATION_SUPPRESSED,
                    )

        rates = db.clear_degraded_rate(self.conn, intent.id)
        old_effective = (
            rates[1]
            if rates is not None
            else round(full_rate * float(os.environ.get("TEAM16_DEGRADE_FACTOR", "0.5")), 6)
        )
        if full_rate > 0:
            queues.update_intent_queue_rates(
                self.conn, intent.id, full_rate, ignore_errors=True
            )
        intent.state = IntentState.ACTIVE
        db.save_intent(self.conn, intent)
        self._processed_event_ids.add(event.id)
        return self.audit.chain(
            intent.id,
            f"{event.payload.get('metric')}={event.payload.get('observed')}",
            f"min_bandwidth_mbps={full_rate:g}",
            "SLA restored and capacity available",
            f"restored min_bandwidth_mbps from {old_effective:g} to {full_rate:g} Mbps",
            severity=Severity.INFO,
            event_type=EventType.SLA_RESTORED,
        )
