"""
Event envelope. FROZEN at ST-3.

One shape for everything that flows between modules and into the audit log. The
feedback edge M5 -> M3 that closes the loop carries an `Event`, and so does every
line the dashboard displays.

Design rule: an event records *what happened and why*, never *what to do next*.
M5 emits SLA_VIOLATED; it does not emit "reroute now". Deciding what to do is the
receiver's job. Keeping that separation is what lets us run the same telemetry
against baseline B1 (open loop) simply by not subscribing anything to the events.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class EventType(str, Enum):
    """
    Every event the system can emit. Adding one is an interface change and needs
    a note in docs/decisions.md.
    """

    # M1
    INTENT_RECEIVED = "intent.received"
    INTENT_REJECTED_INVALID = "intent.rejected_invalid"
    INTENT_WITHDRAWN = "intent.withdrawn"

    # M2
    ADMISSION_DECIDED = "admission.decided"
    INTENT_PREEMPTED = "intent.preempted"

    # M3
    PATH_COMPUTED = "path.computed"
    PATH_INFEASIBLE = "path.infeasible"

    # M4
    PATH_INSTALLED = "path.installed"
    PATH_INSTALL_FAILED = "path.install_failed"

    # M5 - the loop-closing events
    MEASUREMENT_TAKEN = "measurement.taken"
    SLA_VIOLATED = "sla.violated"
    SLA_RESTORED = "sla.restored"
    VIOLATION_SUPPRESSED = "violation.suppressed"   # inside dwell or hysteresis

    # Topology
    LINK_DOWN = "link.down"
    LINK_UP = "link.up"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Event:
    """
    One thing that happened.

    `payload` is deliberately a free-form dict rather than a per-type class. The
    alternative — fifteen event subclasses — buys type safety we do not need and
    costs us a schema migration every time we add a field to one event.

    What is *not* free-form: `type`, `intent_id`, `at` and `message`. Those four
    are what the audit log and the dashboard index on, so they are structural.
    """

    type: EventType
    message: str
    intent_id: Optional[str] = None
    severity: Severity = Severity.INFO
    payload: Dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if not self.message or not self.message.strip():
            raise ValueError(
                f"{self.type.value} has no message; every event must be readable "
                "by a person who has never seen the code"
            )

    def to_json(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "type": self.type.value,
                "severity": self.severity.value,
                "intent_id": self.intent_id,
                "at": self.at,
                "message": self.message,
                "payload": self.payload,
            },
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text: str) -> "Event":
        d = json.loads(text)
        return cls(
            type=EventType(d["type"]),
            message=d["message"],
            intent_id=d.get("intent_id"),
            severity=Severity(d.get("severity", "info")),
            payload=d.get("payload", {}),
            at=d.get("at", time.time()),
            id=d.get("id", uuid.uuid4().hex),
        )


Subscriber = Callable[[Event], None]


class EventBus:
    """
    Minimal synchronous publish/subscribe.

    Synchronous on purpose. An async bus would make the control loop's timing
    depend on scheduler behaviour, and metric E2 (detection latency) measures
    exactly that timing. We want the delay between measurement and re-plan to be
    our logic, not the event system's.

    A subscriber that raises does not stop the others. The failure is recorded
    and delivery continues: one broken dashboard must not break the control loop.
    """

    def __init__(self) -> None:
        self._subs: Dict[Optional[EventType], List[Subscriber]] = {}
        self._errors: List[Exception] = []

    def subscribe(self, fn: Subscriber, event_type: Optional[EventType] = None) -> None:
        """Subscribe to one event type, or to all of them when type is None."""
        self._subs.setdefault(event_type, []).append(fn)

    def publish(self, event: Event) -> None:
        for key in (event.type, None):
            for fn in self._subs.get(key, []):
                try:
                    fn(event)
                except Exception as exc:  # noqa: BLE001 - deliberate isolation
                    self._errors.append(exc)

    @property
    def errors(self) -> List[Exception]:
        """Subscriber failures since construction. Tests assert this is empty."""
        return list(self._errors)


# --------------------------------------------------------------------------- #
# Constructors for the events whose payload shape other modules depend on.
# Using these instead of building Event() by hand keeps payload keys consistent.
# --------------------------------------------------------------------------- #

def sla_violated(intent_id: str, metric: str, observed: float, threshold: float) -> Event:
    return Event(
        type=EventType.SLA_VIOLATED,
        intent_id=intent_id,
        severity=Severity.WARNING,
        message=(
            f"{intent_id}: {metric} is {observed:g}, guarantee is {threshold:g}"
        ),
        payload={"metric": metric, "observed": observed, "threshold": threshold},
    )


def sla_restored(intent_id: str, metric: str, observed: float) -> Event:
    return Event(
        type=EventType.SLA_RESTORED,
        intent_id=intent_id,
        message=f"{intent_id}: {metric} back within guarantee at {observed:g}",
        payload={"metric": metric, "observed": observed},
    )


def violation_suppressed(intent_id: str, reason: str, seconds_remaining: float) -> Event:
    """
    Emitted when a breach was seen but deliberately not acted on.

    This event is why the oscillation graph (metric E6) is explainable rather
    than mysterious: the damped run shows suppressions where the undamped run
    shows reroutes.
    """
    return Event(
        type=EventType.VIOLATION_SUPPRESSED,
        intent_id=intent_id,
        message=f"{intent_id}: violation not acted on ({reason})",
        payload={"reason": reason, "seconds_remaining": seconds_remaining},
    )


def path_installed(intent_id: str, switches: List[str], mode: str, rules: int) -> Event:
    return Event(
        type=EventType.PATH_INSTALLED,
        intent_id=intent_id,
        message=f"{intent_id}: installed {' -> '.join(switches)} ({mode}, {rules} rules)",
        payload={"switches": list(switches), "mode": mode, "rule_count": rules},
    )
