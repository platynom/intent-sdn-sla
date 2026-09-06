"""Pure SLA violation detection with noise damping.

The detector deliberately knows nothing about switches or clocks. A caller
pushes measurements in and receives transition events out, which lets an entire
experiment be replayed deterministically without a live network.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, Iterable, List, Optional, Tuple

from src.common.events import (
    Event,
    EventBus,
    sla_restored,
    sla_violated,
    violation_suppressed,
)
from src.common.models import IntentRecord, Measurement, SLAStatus


# measurement field, guarantee field, violation direction
_METRICS: Tuple[Tuple[str, str, str], ...] = (
    ("delay_ms", "max_latency_ms", "above"),
    ("loss_pct", "max_loss_pct", "above"),
    ("throughput_mbps", "min_bandwidth_mbps", "below"),
)


class ViolationDetector:
    """Turn a stream of measurements into stable SLA transition events."""

    def __init__(
        self,
        intent: IntentRecord,
        bus: Optional[EventBus] = None,
        ewma_alpha: float = 0.3,
        hysteresis_pct: float = 0.1,
        consecutive_required: int = 3,
    ) -> None:
        if not 0.0 < ewma_alpha <= 1.0:
            raise ValueError("ewma_alpha must be in (0, 1]")
        if hysteresis_pct < 0.0:
            raise ValueError("hysteresis_pct must be non-negative")
        if consecutive_required < 1:
            raise ValueError("consecutive_required must be at least 1")

        self.intent = intent
        self.bus = bus
        self.ewma_alpha = float(ewma_alpha)
        self.hysteresis_pct = float(hysteresis_pct)
        self.consecutive_required = int(consecutive_required)
        self.status = SLAStatus.GREEN
        self.smoothed: Dict[str, float] = {}

        self._consecutive: Dict[str, int] = {name: 0 for name, _, _ in _METRICS}
        self._red_metric: Optional[str] = None
        self._violation_announced = False
        self._suppression_announced = False

    def observe(self, m: Measurement, now: Optional[float] = None) -> Optional[Event]:
        """Consume one sample and return at most one state-transition event."""
        if m.intent_id != self.intent.id:
            raise ValueError("measurement intent_id does not match detector intent_id")
        current_time = m.at if now is None else now
        present = self._smooth_present_values(m)
        if not present:
            return None

        states = self._metric_states(present)
        if not states:
            # A measured metric with no corresponding guarantee is information,
            # not a breach; treating it as one would invent an SLA requirement.
            return None

        if self.status is SLAStatus.RED:
            return self._observe_while_red(states, current_time)

        entering = []
        for metric, state in states.items():
            if state == "breach":
                self._consecutive[metric] += 1
                entering.append(metric)
            else:
                # Consecutive confirmation rejects isolated spikes; a band or
                # healthy sample breaks the run of genuinely bad readings.
                self._consecutive[metric] = 0

        confirmed = next(
            (
                metric
                for metric in entering
                if self._consecutive[metric] >= self.consecutive_required
            ),
            None,
        )
        if confirmed is not None:
            self.status = SLAStatus.RED
            self._red_metric = confirmed
            self._violation_announced = False
            return self._announce_or_suppress(confirmed, current_time)

        # Hysteresis leaves an intentional amber gap between breach and recovery,
        # stopping samples on the exact SLA boundary from flipping state.
        self.status = (
            SLAStatus.AMBER
            if any(state in ("band", "breach") for state in states.values())
            else SLAStatus.GREEN
        )
        return None

    def _smooth_present_values(self, m: Measurement) -> List[str]:
        present: List[str] = []
        for metric, _, _ in _METRICS:
            sample = getattr(m, metric)
            if sample is None:
                continue
            value = float(sample)
            previous = self.smoothed.get(metric)
            # Seeding from the first real sample avoids manufacturing an early
            # low-throughput violation by averaging the sample with zero.
            self.smoothed[metric] = (
                value
                if previous is None
                else self.ewma_alpha * value + (1.0 - self.ewma_alpha) * previous
            )
            present.append(metric)
        return present

    def _metric_states(self, present: Iterable[str]) -> Dict[str, str]:
        states: Dict[str, str] = {}
        present_set = set(present)
        for metric, guarantee_name, direction in _METRICS:
            threshold = getattr(self.intent.guarantee, guarantee_name)
            if threshold is None or metric not in present_set:
                continue
            value = self.smoothed[metric]
            if direction == "above":
                enter = threshold * (1.0 + self.hysteresis_pct)
                recover = threshold * (1.0 - self.hysteresis_pct)
                if value > enter:
                    states[metric] = "breach"
                elif value <= recover:
                    states[metric] = "healthy"
                else:
                    states[metric] = "band"
            else:
                enter = threshold * (1.0 - self.hysteresis_pct)
                recover = threshold * (1.0 + self.hysteresis_pct)
                if value < enter:
                    states[metric] = "breach"
                elif value >= recover:
                    states[metric] = "healthy"
                else:
                    states[metric] = "band"
        return states

    def _observe_while_red(
        self, states: Dict[str, str], now: float
    ) -> Optional[Event]:
        # Missing data cannot prove recovery. When values are present, every
        # guaranteed metric in this sample must clear its recovery boundary.
        if states and all(state == "healthy" for state in states.values()):
            metric = self._red_metric or next(iter(states))
            observed = self.smoothed[metric]
            self.status = SLAStatus.GREEN
            self._red_metric = None
            self._violation_announced = False
            self._suppression_announced = False
            for name in self._consecutive:
                self._consecutive[name] = 0
            return self._emit(sla_restored(self.intent.id, metric, observed), now)

        if not self._violation_announced and self._red_metric is not None:
            return self._announce_or_suppress(self._red_metric, now)
        return None

    def _announce_or_suppress(self, metric: str, now: float) -> Optional[Event]:
        # Dwell is checked only after smoothing, hysteresis and consecutive
        # confirmation so suppressed real breaches remain visible in the audit.
        if not self.intent.may_replan_at(now):
            if self._suppression_announced:
                return None
            assert self.intent.last_replan_at is not None
            remaining = max(
                0.0,
                self.intent.last_replan_at + self.intent.dwell_seconds - now,
            )
            self._suppression_announced = True
            return self._emit(
                violation_suppressed(self.intent.id, "dwell timer", remaining), now
            )

        self._violation_announced = True
        self._suppression_announced = False
        threshold = self._threshold_for(metric)
        return self._emit(
            sla_violated(self.intent.id, metric, self.smoothed[metric], threshold), now
        )

    def _threshold_for(self, metric: str) -> float:
        for name, guarantee_name, _ in _METRICS:
            if name == metric:
                threshold = getattr(self.intent.guarantee, guarantee_name)
                assert threshold is not None
                return float(threshold)
        raise KeyError(metric)

    def _emit(self, event: Event, now: float) -> Event:
        timestamped = replace(event, at=now)
        if self.bus is not None:
            self.bus.publish(timestamped)
        return timestamped


def replay(
    detector: ViolationDetector,
    samples: Iterable[Measurement],
    start: float = 0.0,
    interval: float = 1.0,
) -> List[Event]:
    """Replay samples against a simulated clock and return emitted events."""
    events: List[Event] = []
    for index, sample in enumerate(samples):
        event = detector.observe(sample, now=start + index * interval)
        if event is not None:
            events.append(event)
    return events
