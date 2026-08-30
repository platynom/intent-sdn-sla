"""
Shared data model. FROZEN at ST-3.

Every module exchanges these types and nothing else. M1 does not hand M2 a dict;
it hands it an `IntentRecord`. M3 does not hand M4 a list of strings; it hands it
a `PathPlan`.

Why freeze this: three people are building six interlocking modules in parallel.
The project plan's risk register lists "integration fails late because interfaces
drifted" at likelihood Medium, impact High, and names this file as the mitigation.
Changing a field here requires agreement from both sides of the interface and an
entry in docs/decisions.md.

Everything here is pure Python. No Ryu, no Mininet, no database, no network. That
is deliberate: the data model must be testable on any machine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# --------------------------------------------------------------------------- #
# Enumerations. Values are the strings that appear in YAML, the database and the
# REST API, so they must match the intent grammar exactly.
# --------------------------------------------------------------------------- #

class Consistency(str, Enum):
    """How M4 installs a path change."""

    STRICT = "strict"      # two-phase versioned update: lossless, ~2x flow entries
    RELAXED = "relaxed"    # direct install: cheap, drops packets in flight


class OnViolation(str, Enum):
    """What the loop does when an SLA is breached. The three frozen actions."""

    REROUTE = "reroute"
    DEGRADE = "degrade"
    ALERT_ONLY = "alert_only"


class IntentState(str, Enum):
    """Lifecycle of an intent inside the system."""

    PENDING = "pending"        # accepted by M1, not yet seen by M2
    ADMITTED = "admitted"      # M2 said yes, M3/M4 not finished
    ACTIVE = "active"          # installed and being measured
    REJECTED = "rejected"      # M2 said no; terminal
    PREEMPTED = "preempted"    # displaced by a higher-priority intent; terminal
    DEGRADED = "degraded"      # active, but on a reduced guarantee
    WITHDRAWN = "withdrawn"    # deleted by the operator; terminal


TERMINAL_STATES = frozenset(
    {IntentState.REJECTED, IntentState.PREEMPTED, IntentState.WITHDRAWN}
)


class SLAStatus(str, Enum):
    """Traffic-light status shown on the dashboard and used by the loop."""

    GREEN = "green"    # within guarantee
    AMBER = "amber"    # inside the hysteresis band; not yet a violation
    RED = "red"        # violating


class Verdict(str, Enum):
    """M2's four possible answers. Every one carries a human-readable reason."""

    ADMIT = "admit"
    REJECT = "reject"
    PREEMPT = "preempt"
    DEGRADE = "degrade"


# --------------------------------------------------------------------------- #
# Intent
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Match:
    """The packets an intent applies to."""

    src: str
    dst: str
    proto: str = "any"
    dport: Optional[int] = None


@dataclass(frozen=True)
class Guarantee:
    """
    The five frozen constraint types. All optional individually; the schema
    requires at least one, and the validator rejects a guarantee whose every
    field is empty.
    """

    min_bandwidth_mbps: Optional[float] = None
    max_latency_ms: Optional[float] = None
    max_loss_pct: Optional[float] = None
    isolate_from: Tuple[str, ...] = ()
    avoid_links: Tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not any(
            (
                self.min_bandwidth_mbps is not None,
                self.max_latency_ms is not None,
                self.max_loss_pct is not None,
                self.isolate_from,
                self.avoid_links,
            )
        )


@dataclass
class IntentRecord:
    """
    One intent plus its runtime state. This is the unit M1 stores and every other
    module reads.

    Construct with `from_document()` rather than by hand, so defaults from the
    schema are applied in exactly one place.
    """

    id: str
    tenant: str
    priority: int
    match: Match
    guarantee: Guarantee
    consistency: Consistency = Consistency.STRICT
    on_violation: OnViolation = OnViolation.REROUTE
    dwell_seconds: int = 10

    state: IntentState = IntentState.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Set once M3/M4 have run. None while pending or rejected.
    current_path: Optional["PathPlan"] = None
    # Wall-clock time of the last re-plan, used to enforce dwell_seconds.
    last_replan_at: Optional[float] = None

    @classmethod
    def from_document(cls, doc: Dict[str, Any]) -> "IntentRecord":
        """
        Build from a document that has already passed M1 validation.

        Assumes the shape is valid: schema validation happens in
        src/intent_manager/validator.py and is not repeated here.
        """
        intent = doc["intent"]
        m = intent["match"]
        g = intent["guarantee"]
        return cls(
            id=intent["id"],
            tenant=intent["tenant"],
            priority=intent["priority"],
            match=Match(
                src=m["src"],
                dst=m["dst"],
                proto=m.get("proto", "any"),
                dport=m.get("dport"),
            ),
            guarantee=Guarantee(
                min_bandwidth_mbps=g.get("min_bandwidth_mbps"),
                max_latency_ms=g.get("max_latency_ms"),
                max_loss_pct=g.get("max_loss_pct"),
                isolate_from=tuple(g.get("isolate_from", ())),
                avoid_links=tuple(g.get("avoid_links", ())),
            ),
            consistency=Consistency(intent.get("consistency", "strict")),
            on_violation=OnViolation(intent.get("on_violation", "reroute")),
            dwell_seconds=int(intent.get("dwell_seconds", 10)),
        )

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def may_replan_at(self, now: Optional[float] = None) -> bool:
        """
        Anti-oscillation gate. An intent that re-planned less than dwell_seconds
        ago must be left alone, however bad it looks.

        This is the single place the dwell rule is implemented. M5 and M3 both
        call it rather than each doing their own arithmetic.
        """
        if self.last_replan_at is None:
            return True
        current = time.time() if now is None else now
        return (current - self.last_replan_at) >= self.dwell_seconds

    def touch(self) -> None:
        self.updated_at = time.time()


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PathPlan:
    """
    A concrete route for one intent, as computed by M3 and installed by M4.

    `switches` is the ordered switch hop list, e.g. ["s1", "s2", "s3", "s7"].
    `links` is derived from it and stored so M2 can account for capacity without
    recomputing, and so the audit log can show exactly which links were used.
    """

    intent_id: str
    switches: Tuple[str, ...]
    links: Tuple[str, ...]
    est_latency_ms: float
    bottleneck_mbps: float
    # Version tag used by the two-phase update. None means the path was installed
    # directly (relaxed consistency) and carries no version bit.
    version: Optional[int] = None
    computed_at: float = field(default_factory=time.time)

    @staticmethod
    def links_for(switches: List[str]) -> Tuple[str, ...]:
        """
        Canonical link names for a switch path, lower-numbered switch first.

        Kept here rather than in topology_spec because it is a property of a
        *path*, and because M2, M3, M4 and M6 all need the same answer.
        """
        out = []
        for a, b in zip(switches, switches[1:]):
            lo, hi = sorted((a, b), key=lambda s: int(s[1:]))
            out.append(f"{lo}-{hi}")
        return tuple(out)

    def uses_link(self, link_name: str) -> bool:
        return link_name in self.links

    def is_disjoint_from(self, other: "PathPlan") -> bool:
        return not set(self.links) & set(other.links)


@dataclass
class LinkState:
    """
    Residual capacity on one link, maintained by M2.

    `reserved_mbps` is the sum of admitted `min_bandwidth_mbps` guarantees whose
    path crosses this link. It is a bookkeeping figure, not a measurement: what
    the link is actually carrying comes from M5.
    """

    name: str
    capacity_mbps: float
    base_delay_ms: float
    reserved_mbps: float = 0.0
    up: bool = True

    @property
    def residual_mbps(self) -> float:
        return max(0.0, self.capacity_mbps - self.reserved_mbps)

    def can_admit(self, mbps: float) -> bool:
        return self.up and self.residual_mbps >= mbps

    def reserve(self, mbps: float) -> None:
        if not self.can_admit(mbps):
            raise ValueError(
                f"{self.name}: cannot reserve {mbps} Mbps, only "
                f"{self.residual_mbps} Mbps residual"
            )
        self.reserved_mbps += mbps

    def release(self, mbps: float) -> None:
        # Clamp rather than go negative: a double-release is a bug, but silently
        # corrupting the capacity model makes every later decision wrong too.
        self.reserved_mbps = max(0.0, self.reserved_mbps - mbps)


# --------------------------------------------------------------------------- #
# Measurement and decisions
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Measurement:
    """
    One sample for one intent, produced by M5.

    Fields are Optional because not every source produces every field: counter
    deltas give loss and throughput, active probes give delay and jitter.
    """

    intent_id: str
    at: float
    delay_ms: Optional[float] = None
    jitter_ms: Optional[float] = None
    loss_pct: Optional[float] = None
    throughput_mbps: Optional[float] = None

    def violates(self, guarantee: Guarantee) -> bool:
        """
        Strict comparison against the guarantee, with no smoothing or hysteresis.

        This is the raw predicate. Deciding whether a violation is *real* —
        applying EWMA, the hysteresis band and the dwell timer — belongs to M5's
        detector, not here. Keeping the raw test separate makes both testable.
        """
        if (
            guarantee.max_latency_ms is not None
            and self.delay_ms is not None
            and self.delay_ms > guarantee.max_latency_ms
        ):
            return True
        if (
            guarantee.max_loss_pct is not None
            and self.loss_pct is not None
            and self.loss_pct > guarantee.max_loss_pct
        ):
            return True
        if (
            guarantee.min_bandwidth_mbps is not None
            and self.throughput_mbps is not None
            and self.throughput_mbps < guarantee.min_bandwidth_mbps
        ):
            return True
        return False


@dataclass(frozen=True)
class AdmissionDecision:
    """
    M2's answer. `reason` is mandatory and must be human-readable.

    The project plan's definition of done for M2 is "every decision writes a
    human-readable reason to the audit log". A decision with an empty reason is
    a defect, and the constructor enforces it.
    """

    intent_id: str
    verdict: Verdict
    reason: str
    # Set when verdict is PREEMPT: whose resources were taken.
    preempted_intent_id: Optional[str] = None
    # Set when verdict is DEGRADE: the reduced guarantee being offered.
    offered_guarantee: Optional[Guarantee] = None
    decided_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.reason or not self.reason.strip():
            raise ValueError(
                f"AdmissionDecision for {self.intent_id} has no reason; "
                "every decision must be explainable in the audit log"
            )
        if self.verdict is Verdict.PREEMPT and not self.preempted_intent_id:
            raise ValueError("PREEMPT requires preempted_intent_id")
        if self.verdict is Verdict.DEGRADE and self.offered_guarantee is None:
            raise ValueError("DEGRADE requires offered_guarantee")

    @property
    def admitted(self) -> bool:
        return self.verdict in (Verdict.ADMIT, Verdict.PREEMPT, Verdict.DEGRADE)


def to_dict(obj: Any) -> Dict[str, Any]:
    """Serialise any model dataclass for JSON, the database or the dashboard."""
    return asdict(obj)
