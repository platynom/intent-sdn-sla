"""
Audit log. FROZEN at ST-3.

The project plan's definition of done for M6 is: "a viewer with no knowledge of
the code can explain what happened and why." That is this module's job.

An audit entry records the full causal chain for one automated action:

    intent -> measurement -> threshold -> decision -> action

Every automated change to the network writes one. If an action cannot be
explained in that form, it should not be automatic.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from .db import events_for, save_event
from .events import Event, EventBus, EventType, Severity


@dataclass(frozen=True)
class CausalChain:
    """
    One automated action, told as a story.

    All five fields are strings because the audience is a human reading a
    dashboard, not a program. The machine-readable version is the Event payload.
    """

    intent_id: str
    measurement: str   # what we observed
    threshold: str     # what the intent promised
    decision: str      # what we concluded
    action: str        # what we did about it
    at: float

    def render(self) -> str:
        return (
            f"{self.intent_id}\n"
            f"  measured : {self.measurement}\n"
            f"  promised : {self.threshold}\n"
            f"  decided  : {self.decision}\n"
            f"  did      : {self.action}"
        )

    def one_line(self) -> str:
        return (
            f"{self.intent_id}: {self.measurement} vs {self.threshold} "
            f"-> {self.decision} -> {self.action}"
        )


class AuditLog:
    """
    Writes events to SQLite and, optionally, mirrors them onto the event bus.

    Attach one of these to the bus at start-up and the audit log fills itself:

        bus = EventBus()
        audit = AuditLog(conn)
        bus.subscribe(audit.record)

    Persisting is deliberately synchronous. Losing the explanation of an action
    that already happened is worse than a millisecond of latency, and the whole
    reproducibility claim rests on the log matching the run.
    """

    def __init__(self, conn: sqlite3.Connection, bus: Optional[EventBus] = None):
        self._conn = conn
        self._bus = bus

    def record(self, event: Event) -> None:
        """Persist one event. Safe to call twice with the same event."""
        save_event(self._conn, event)

    def emit(self, event: Event) -> None:
        """Persist and publish, in that order."""
        self.record(event)
        if self._bus is not None:
            self._bus.publish(event)

    def chain(
        self,
        intent_id: str,
        measurement: str,
        threshold: str,
        decision: str,
        action: str,
        severity: Severity = Severity.INFO,
        event_type: EventType = EventType.SLA_VIOLATED,
    ) -> CausalChain:
        """
        Record a complete causal chain and return it.

        The Event carries the five parts as separate payload fields so the
        dashboard can lay them out, and as a rendered `message` so anything that
        only reads messages still shows something meaningful.
        """
        entry = Event(
            type=event_type,
            intent_id=intent_id,
            severity=severity,
            message=(
                f"{intent_id}: measured {measurement}, promised {threshold}, "
                f"{decision}, {action}"
            ),
            payload={
                "measurement": measurement,
                "threshold": threshold,
                "decision": decision,
                "action": action,
            },
        )
        self.emit(entry)
        return CausalChain(
            intent_id=intent_id,
            measurement=measurement,
            threshold=threshold,
            decision=decision,
            action=action,
            at=entry.at,
        )

    def history(self, intent_id: Optional[str] = None, limit: int = 200) -> List[Event]:
        return events_for(self._conn, intent_id, limit)

    def explain(self, intent_id: str, limit: int = 50) -> str:
        """
        Plain-text history for one intent, oldest first.

        This is what gets shown in the demo when the examiner asks why the path
        moved, and what gets pasted into the report.
        """
        events = list(reversed(self.history(intent_id, limit)))
        if not events:
            return f"{intent_id}: no recorded events"

        lines = [f"Audit history for {intent_id}", "=" * (18 + len(intent_id))]
        start = events[0].at
        for ev in events:
            lines.append(f"[{ev.at - start:7.2f}s] {ev.severity.value:7s} {ev.message}")
        return "\n".join(lines)
