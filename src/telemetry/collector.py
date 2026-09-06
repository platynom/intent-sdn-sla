"""Replaceable telemetry sources and counter-delta collection.

Live dependencies are optional. The calculation path accepts ordinary numbers
and hand-written measurements, so tests and offline experiments need neither a
controller nor a privileged Mininet process.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Protocol

from src.common import db
from src.common.events import Event
from src.common.models import Measurement
from src.telemetry.detector import ViolationDetector

try:
    from ryu.ofproto import ofproto_v1_3 as _ryu_ofproto_v1_3

    RYU_AVAILABLE = _ryu_ofproto_v1_3 is not None
except ImportError:  # pragma: no cover - exercised on installations with Ryu
    RYU_AVAILABLE = False

try:
    from mininet.net import Mininet as _Mininet

    MININET_AVAILABLE = _Mininet is not None
except ImportError:  # pragma: no cover - exercised inside the project container
    MININET_AVAILABLE = False

AVAILABLE = RYU_AVAILABLE and MININET_AVAILABLE
POLL_INTERVAL_SECONDS = 1.0


class MeasurementSource(Protocol):
    """Interface shared by live and fake measurement sources."""

    def collect(self) -> Iterable[Measurement]:
        """Yield measurements produced by this source."""


@dataclass(frozen=True)
class CounterSnapshot:
    """Counters needed to derive one interval's rate and packet loss."""

    at: float
    tx_bytes: int
    rx_bytes: int
    tx_packets: int
    rx_packets: int


class _Consumer:
    def __init__(
        self,
        detector: Optional[ViolationDetector] = None,
        conn=None,
    ) -> None:
        self.detector = detector
        self.conn = conn

    def consume(self, measurement: Measurement) -> Optional[Event]:
        if self.conn is not None:
            db.save_measurement(
                self.conn,
                measurement.intent_id,
                measurement.at,
                delay_ms=measurement.delay_ms,
                jitter_ms=measurement.jitter_ms,
                loss_pct=measurement.loss_pct,
                throughput_mbps=measurement.throughput_mbps,
            )
        if self.detector is None:
            return None
        return self.detector.observe(measurement, now=measurement.at)


class StatsCollector(_Consumer):
    """Request OpenFlow stats and derive samples from successive counters."""

    poll_interval = POLL_INTERVAL_SECONDS

    def __init__(
        self,
        detector: Optional[ViolationDetector] = None,
        conn=None,
    ) -> None:
        super().__init__(detector=detector, conn=conn)
        self._previous: Dict[str, CounterSnapshot] = {}

    def request_stats(self, datapath) -> None:
        """Request one port and flow snapshot; scheduling remains external."""
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        datapath.send_msg(
            parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        )
        datapath.send_msg(parser.OFPFlowStatsRequest(datapath))

    def observe_counters(
        self,
        intent_id: str,
        at: float,
        tx_bytes: int,
        rx_bytes: int,
        tx_packets: int,
        rx_packets: int,
    ) -> Optional[Measurement]:
        """Convert cumulative counters to one interval measurement."""
        current = CounterSnapshot(
            at=float(at),
            tx_bytes=int(tx_bytes),
            rx_bytes=int(rx_bytes),
            tx_packets=int(tx_packets),
            rx_packets=int(rx_packets),
        )
        previous = self._previous.get(intent_id)
        self._previous[intent_id] = current
        if previous is None:
            return None

        fields = ("tx_bytes", "rx_bytes", "tx_packets", "rx_packets")
        # Switch restarts reset cumulative counters. Skipping the interval avoids
        # turning that reset into an impossible negative traffic rate.
        if current.at <= previous.at or any(
            getattr(current, field) < getattr(previous, field) for field in fields
        ):
            return None

        elapsed = current.at - previous.at
        rx_byte_delta = current.rx_bytes - previous.rx_bytes
        tx_packet_delta = current.tx_packets - previous.tx_packets
        rx_packet_delta = current.rx_packets - previous.rx_packets
        throughput = rx_byte_delta * 8.0 / elapsed / 1_000_000.0
        if tx_packet_delta > 0:
            lost = max(0, tx_packet_delta - rx_packet_delta)
            loss = lost * 100.0 / tx_packet_delta
        else:
            loss = 0.0

        measurement = Measurement(
            intent_id=intent_id,
            at=current.at,
            loss_pct=loss,
            throughput_mbps=throughput,
        )
        self.consume(measurement)
        return measurement

    # A descriptive alias keeps event-handler code readable without duplicating
    # the counter arithmetic.
    process_counters = observe_counters


class ProbeSource(_Consumer):
    """Convert timestamped probe replies and timeouts into delay samples."""

    def __init__(
        self,
        detector: Optional[ViolationDetector] = None,
        conn=None,
    ) -> None:
        super().__init__(detector=detector, conn=conn)
        self._delays: Dict[str, List[float]] = defaultdict(list)

    def record_probe(
        self,
        intent_id: str,
        sent_at: float,
        received_at: Optional[float],
        at: Optional[float] = None,
    ) -> Measurement:
        """Record a probe reply, using ``None`` delay for a timeout."""
        timestamp = sent_at if at is None else at
        delay: Optional[float] = None
        jitter: Optional[float] = None
        if received_at is not None:
            timestamp = received_at if at is None else at
            delay = max(0.0, (received_at - sent_at) * 1000.0)
            history = self._delays[intent_id]
            history.append(delay)
            if len(history) >= 2:
                differences = [
                    abs(right - left) for left, right in zip(history, history[1:])
                ]
                jitter = sum(differences) / len(differences)

        # A timeout is unknown data, not synthetic extreme latency; inventing a
        # value here could cause the later control loop to reroute good traffic.
        measurement = Measurement(
            intent_id=intent_id,
            at=float(timestamp),
            delay_ms=delay,
            jitter_ms=jitter,
        )
        self.consume(measurement)
        return measurement


class FakeSource(_Consumer):
    """Replay supplied Measurement objects through the production interface."""

    def __init__(
        self,
        samples: Iterable[Measurement],
        detector: Optional[ViolationDetector] = None,
        conn=None,
    ) -> None:
        super().__init__(detector=detector, conn=conn)
        self.samples = list(samples)

    def collect(self) -> Iterator[Measurement]:
        yield from self.samples

    def run(self) -> List[Event]:
        events: List[Event] = []
        for measurement in self.collect():
            event = self.consume(measurement)
            if event is not None:
                events.append(event)
        return events

    replay = run
