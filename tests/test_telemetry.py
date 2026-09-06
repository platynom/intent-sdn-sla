"""ST-6 telemetry tests that require no Ryu, Mininet, root, or waiting."""

from __future__ import annotations

import sqlite3

import pytest

from src.common import db
from src.common.events import EventBus, EventType
from src.common.models import Guarantee, IntentRecord, Match, Measurement, SLAStatus
from src.telemetry import collector
from src.telemetry.collector import FakeSource, ProbeSource, StatsCollector
from src.telemetry.detector import ViolationDetector, replay
from src.telemetry.probes import ActiveProbeSource, parse_ping


def make_intent(**guarantee_values):
    """Build a small intent while keeping thresholds explicit in each test."""
    return IntentRecord(
        id="INT-600",
        tenant="telemetry-test",
        priority=2,
        match=Match("10.0.0.1/32", "10.0.0.2/32"),
        guarantee=Guarantee(**guarantee_values),
    )


def sample(at=0.0, **values):
    """Build a measurement for the shared test intent."""
    return Measurement(intent_id="INT-600", at=at, **values)


def test_detector_starts_green_with_no_smoothed_values():
    """A new intent must not appear degraded before any evidence exists."""
    detector = ViolationDetector(make_intent(max_latency_ms=10))
    assert detector.status is SLAStatus.GREEN
    assert detector.smoothed == {}


@pytest.mark.parametrize("alpha", [0.0, -0.1, 1.1])
def test_invalid_ewma_alpha_is_rejected(alpha):
    """Invalid EWMA weights would make smoothing mathematically meaningless."""
    with pytest.raises(ValueError):
        ViolationDetector(make_intent(max_latency_ms=10), ewma_alpha=alpha)


def test_negative_hysteresis_is_rejected():
    """A reversed hysteresis band would encourage rather than prevent flapping."""
    with pytest.raises(ValueError):
        ViolationDetector(make_intent(max_latency_ms=10), hysteresis_pct=-0.1)


def test_zero_consecutive_requirement_is_rejected():
    """A zero-length confirmation window would declare breaches without samples."""
    with pytest.raises(ValueError):
        ViolationDetector(make_intent(max_latency_ms=10), consecutive_required=0)


def test_measurement_for_another_intent_is_rejected():
    """Mixing tenant streams could reroute the wrong customer's traffic."""
    detector = ViolationDetector(make_intent(max_latency_ms=10))
    wrong = Measurement("INT-OTHER", at=0, delay_ms=20)
    with pytest.raises(ValueError):
        detector.observe(wrong, now=0)


def test_one_bad_sample_among_good_samples_does_not_trigger():
    """One latency spike must not cause an unnecessary route change."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, consecutive_required=3
    )
    events = [
        detector.observe(sample(at=0, delay_ms=5), now=0),
        detector.observe(sample(at=1, delay_ms=20), now=1),
        detector.observe(sample(at=2, delay_ms=5), now=2),
    ]
    assert events == [None, None, None]
    assert detector.status is SLAStatus.GREEN


def test_n_consecutive_bad_samples_trigger_exactly_one_violation():
    """A sustained breach must be reported once without flooding the controller."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, consecutive_required=3
    )
    events = [
        detector.observe(sample(at=i, delay_ms=20), now=i) for i in range(5)
    ]
    actual = [event for event in events if event is not None]
    assert [event.type for event in actual] == [EventType.SLA_VIOLATED]


def test_violation_is_published_to_the_bus():
    """A detected breach must reach subscribers such as audit and future control."""
    bus = EventBus()
    received = []
    bus.subscribe(received.append)
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), bus=bus, ewma_alpha=1,
        consecutive_required=1
    )
    returned = detector.observe(sample(delay_ms=20), now=7)
    assert received == [returned]


def test_value_inside_latency_hysteresis_band_is_amber():
    """Boundary noise must be visible without being treated as a real breach."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, hysteresis_pct=0.1
    )
    assert detector.observe(sample(delay_ms=10.5), now=0) is None
    assert detector.status is SLAStatus.AMBER


def test_latency_recovery_requires_lower_hysteresis_boundary():
    """Returning merely to the SLA limit must not prematurely clear a breach."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, hysteresis_pct=0.1,
        consecutive_required=1
    )
    detector.observe(sample(delay_ms=12), now=0)
    assert detector.observe(sample(delay_ms=10), now=1) is None
    assert detector.status is SLAStatus.RED
    restored = detector.observe(sample(delay_ms=9), now=2)
    assert restored is not None
    assert restored.type is EventType.SLA_RESTORED


def test_chattering_at_latency_boundary_emits_nothing():
    """Values hovering around the threshold must not alternate violation events."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, hysteresis_pct=0.1,
        consecutive_required=1
    )
    first = detector.observe(sample(delay_ms=12), now=0)
    chatter = [
        detector.observe(sample(delay_ms=value), now=index)
        for index, value in enumerate([10, 10.4, 9.5, 10.2], start=1)
    ]
    assert first is not None
    assert chatter == [None, None, None, None]


def test_throughput_below_minimum_violates():
    """Bandwidth direction must be inverted relative to delay and loss."""
    detector = ViolationDetector(
        make_intent(min_bandwidth_mbps=20), ewma_alpha=1,
        consecutive_required=1
    )
    event = detector.observe(sample(throughput_mbps=17), now=0)
    assert event is not None
    assert event.payload["metric"] == "throughput_mbps"


def test_throughput_above_minimum_does_not_violate():
    """Good high throughput must never be mistaken for an SLA breach."""
    detector = ViolationDetector(
        make_intent(min_bandwidth_mbps=20), ewma_alpha=1,
        consecutive_required=1
    )
    assert detector.observe(sample(throughput_mbps=50), now=0) is None
    assert detector.status is SLAStatus.GREEN


def test_loss_above_maximum_violates():
    """Sustained excessive loss must be identified using the correct direction."""
    detector = ViolationDetector(
        make_intent(max_loss_pct=1), ewma_alpha=1, consecutive_required=1
    )
    event = detector.observe(sample(loss_pct=1.2), now=0)
    assert event is not None
    assert event.payload["metric"] == "loss_pct"


def test_metric_without_guarantee_never_violates():
    """Telemetry must not invent SLA promises the operator never requested."""
    detector = ViolationDetector(
        make_intent(min_bandwidth_mbps=20), ewma_alpha=1,
        consecutive_required=1
    )
    assert detector.observe(sample(delay_ms=10000), now=0) is None
    assert detector.status is SLAStatus.GREEN


def test_none_measurement_never_violates():
    """A missing reading must remain unknown rather than become a fake failure."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, consecutive_required=1
    )
    assert detector.observe(sample(delay_ms=None), now=0) is None
    assert detector.status is SLAStatus.GREEN


def test_ewma_is_seeded_from_first_sample():
    """Seeding throughput at zero would produce a false initial breach."""
    detector = ViolationDetector(make_intent(min_bandwidth_mbps=20))
    detector.observe(sample(throughput_mbps=30), now=0)
    assert detector.smoothed["throughput_mbps"] == 30


def test_ewma_uses_previous_smoothed_value():
    """Incorrect smoothing would distort both breach and recovery timing."""
    detector = ViolationDetector(make_intent(max_latency_ms=100), ewma_alpha=0.25)
    detector.observe(sample(delay_ms=20), now=0)
    detector.observe(sample(delay_ms=40), now=1)
    assert detector.smoothed["delay_ms"] == pytest.approx(25)


def test_dwell_suppresses_confirmed_breach_with_remaining_seconds():
    """A real breach during dwell must be audited without triggering replanning."""
    intent = make_intent(max_latency_ms=10)
    intent.last_replan_at = 100
    intent.dwell_seconds = 10
    detector = ViolationDetector(intent, ewma_alpha=1, consecutive_required=1)
    event = detector.observe(sample(delay_ms=20), now=104)
    assert event is not None
    assert event.type is EventType.VIOLATION_SUPPRESSED
    assert event.payload["seconds_remaining"] == 6


def test_same_breach_emits_violation_after_dwell_expires():
    """Dwell must postpone action rather than permanently hide a persistent breach."""
    intent = make_intent(max_latency_ms=10)
    intent.last_replan_at = 100
    intent.dwell_seconds = 10
    detector = ViolationDetector(intent, ewma_alpha=1, consecutive_required=1)
    suppressed = detector.observe(sample(delay_ms=20), now=104)
    violated = detector.observe(sample(delay_ms=20), now=110)
    assert suppressed is not None
    assert violated is not None
    assert violated.type is EventType.SLA_VIOLATED


def test_repeated_suppressed_samples_do_not_duplicate_event():
    """A dwell period must not flood the audit log at the polling frequency."""
    intent = make_intent(max_latency_ms=10)
    intent.last_replan_at = 100
    detector = ViolationDetector(intent, ewma_alpha=1, consecutive_required=1)
    assert detector.observe(sample(delay_ms=20), now=101) is not None
    assert detector.observe(sample(delay_ms=20), now=102) is None


def test_red_to_green_emits_exactly_one_restored_event():
    """Recovery must be announced once so downstream state can return to healthy."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, consecutive_required=1
    )
    violated = detector.observe(sample(delay_ms=20), now=0)
    restored = detector.observe(sample(delay_ms=5), now=1)
    duplicate = detector.observe(sample(delay_ms=5), now=2)
    assert violated is not None
    assert restored is not None
    assert restored.type is EventType.SLA_RESTORED
    assert duplicate is None


def test_repeated_red_samples_do_not_duplicate_violation():
    """One continuing incident must not look like many separate incidents."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, consecutive_required=1
    )
    first = detector.observe(sample(delay_ms=20), now=0)
    second = detector.observe(sample(delay_ms=30), now=1)
    assert first is not None
    assert second is None


def test_event_timestamp_uses_injected_now():
    """Offline replay must not leak the machine's wall clock into results."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, consecutive_required=1
    )
    event = detector.observe(sample(at=999, delay_ms=20), now=42)
    assert event is not None
    assert event.at == 42


def test_observe_defaults_to_measurement_timestamp():
    """Callers omitting now still need deterministic event timestamps."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, consecutive_required=1
    )
    event = detector.observe(sample(at=55, delay_ms=20))
    assert event is not None
    assert event.at == 55


def test_replay_uses_simulated_schedule():
    """Long scenarios must run immediately while preserving simulated timing."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, consecutive_required=1
    )
    samples = [sample(delay_ms=20), sample(delay_ms=5)]
    events = replay(detector, samples, start=100, interval=60)
    assert [event.at for event in events] == [100, 160]


def test_fake_source_yields_the_original_measurement_objects():
    """A test source must not alter evidence before the detector consumes it."""
    samples = [sample(at=1, delay_ms=5), sample(at=2, delay_ms=20)]
    assert list(FakeSource(samples).collect()) == samples
    assert list(FakeSource(samples).collect())[0] is samples[0]


def test_fake_source_drives_detector_without_sleeping():
    """Software-only tests must exercise the real detector without live timing."""
    detector = ViolationDetector(
        make_intent(max_latency_ms=10), ewma_alpha=1, consecutive_required=1
    )
    source = FakeSource(
        [sample(at=1, delay_ms=20), sample(at=2, delay_ms=5)], detector
    )
    assert [event.type for event in source.run()] == [
        EventType.SLA_VIOLATED,
        EventType.SLA_RESTORED,
    ]


def test_live_dependency_availability_flags_are_booleans():
    """Importing telemetry must clearly report absent live-network dependencies."""
    assert isinstance(collector.RYU_AVAILABLE, bool)
    assert isinstance(collector.MININET_AVAILABLE, bool)
    assert isinstance(collector.AVAILABLE, bool)


def test_collector_declares_one_hertz_polling():
    """Changing the sampling rate silently would invalidate experiment timings."""
    assert StatsCollector.poll_interval == 1.0


def test_first_counter_snapshot_only_seeds_baseline():
    """Absolute counters must never be misreported as a one-second traffic rate."""
    stats = StatsCollector()
    result = stats.observe_counters("INT-600", 1, 100, 80, 10, 8)
    assert result is None


def test_throughput_is_computed_from_counter_delta():
    """Using absolute byte counters would make throughput grow forever."""
    stats = StatsCollector()
    stats.observe_counters("INT-600", 1, 100, 100, 10, 10)
    result = stats.observe_counters("INT-600", 2, 1_000_100, 1_000_100, 20, 20)
    assert result is not None
    assert result.throughput_mbps == pytest.approx(8.0)


def test_loss_is_computed_from_packet_deltas():
    """Loss must describe the latest interval rather than the switch's lifetime."""
    stats = StatsCollector()
    stats.observe_counters("INT-600", 1, 0, 0, 100, 100)
    result = stats.observe_counters("INT-600", 2, 100, 100, 200, 190)
    assert result is not None
    assert result.loss_pct == pytest.approx(10.0)


def test_counter_reset_skips_interval():
    """A restarted switch must not generate a negative rate or false recovery."""
    stats = StatsCollector()
    stats.observe_counters("INT-600", 1, 1_000, 1_000, 100, 100)
    assert stats.observe_counters("INT-600", 2, 5, 5, 1, 1) is None


def test_collection_resumes_after_counter_reset():
    """Skipping a reset must not permanently disable later measurements."""
    stats = StatsCollector()
    stats.observe_counters("INT-600", 1, 1_000, 1_000, 100, 100)
    stats.observe_counters("INT-600", 2, 5, 5, 1, 1)
    result = stats.observe_counters("INT-600", 3, 1_000_005, 1_000_005, 11, 11)
    assert result is not None
    assert result.throughput_mbps >= 0


def test_stats_sample_is_saved_to_database():
    """Dropping collected samples would leave no evidence for evaluation."""
    conn = db.connect(":memory:")
    db.init_db(conn)
    db.save_intent(conn, make_intent(min_bandwidth_mbps=1))
    stats = StatsCollector(conn=conn)
    stats.observe_counters("INT-600", 1, 0, 0, 0, 0)
    stats.observe_counters("INT-600", 2, 100, 100, 1, 1)
    count = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    assert count == 1


def test_request_stats_sends_port_and_flow_requests():
    """A live collector must request both counter sources needed by ST-6."""
    class Parser:
        @staticmethod
        def OFPPortStatsRequest(datapath, flags, port):
            return ("port", datapath, flags, port)

        @staticmethod
        def OFPFlowStatsRequest(datapath):
            return ("flow", datapath)

    class Ofproto:
        OFPP_ANY = 99

    class Datapath:
        ofproto_parser = Parser()
        ofproto = Ofproto()

        def __init__(self):
            self.sent = []

        def send_msg(self, message):
            self.sent.append(message)

    datapath = Datapath()
    StatsCollector().request_stats(datapath)
    assert [message[0] for message in datapath.sent] == ["port", "flow"]


def test_probe_timeout_records_none_delay():
    """A timeout must not fabricate high latency that could cause a reroute."""
    measurement = ProbeSource().record_probe("INT-600", 10, None, at=11)
    assert measurement.delay_ms is None
    assert measurement.jitter_ms is None


def test_probe_reply_converts_seconds_to_milliseconds():
    """A unit error would compare seconds directly against millisecond promises."""
    measurement = ProbeSource().record_probe("INT-600", 10, 10.025)
    assert measurement.delay_ms == pytest.approx(25)


def test_probe_jitter_is_mean_absolute_consecutive_difference():
    """Jitter must use the documented repeatable calculation."""
    probes = ProbeSource()
    probes.record_probe("INT-600", 0, 0.010)
    probes.record_probe("INT-600", 1, 1.030)
    third = probes.record_probe("INT-600", 2, 2.020)
    assert third.jitter_ms == pytest.approx(15)


def test_probe_measurement_is_passed_to_detector_unchanged():
    """Collection and detection must remain separable behind the source interface."""
    class RecordingDetector:
        def __init__(self):
            self.seen = []

        def observe(self, measurement, now=None):
            self.seen.append((measurement, now))
            return None

    detector = RecordingDetector()
    probes = ProbeSource(detector=detector)
    measurement = probes.record_probe("INT-600", 1, 1.005)
    assert detector.seen == [(measurement, measurement.at)]


def test_fake_source_can_persist_supplied_samples():
    """Offline replay evidence must be storable through the production DB path."""
    conn = db.connect(":memory:")
    db.init_db(conn)
    db.save_intent(conn, make_intent(max_latency_ms=10))
    supplied = sample(at=3, delay_ms=7)
    FakeSource([supplied], conn=conn).run()
    row = conn.execute("SELECT delay_ms, at FROM measurements").fetchone()
    assert tuple(row) == (7, 3)


def test_database_connection_type_is_ordinary_sqlite():
    """Telemetry persistence must not introduce an unapproved database dependency."""
    conn = db.connect(":memory:")
    assert isinstance(conn, sqlite3.Connection)


def test_live_ping_parser_extracts_numeric_rtt_and_loss():
    """Malformed live values would make persisted SLA evidence unusable."""
    output = (
        "3 packets transmitted, 3 received, 0% packet loss\n"
        "rtt min/avg/max/mdev = 12.1/13.2/15.0/1.1 ms\n"
    )
    assert parse_ping(output) == (13.2, 0.0)


def test_live_ping_timeout_is_loss_not_fake_latency():
    """A timeout must record loss while leaving latency unknown."""
    delay, loss = parse_ping("1 packets transmitted, 0 received, 100% packet loss")
    assert delay is None and loss == 100.0


def test_active_probe_derives_consecutive_jitter():
    """Live jitter must describe actual consecutive RTT variation."""
    source = ActiveProbeSource()
    first = "1 packets transmitted, 1 received, 0% packet loss\nrtt min/avg/max/mdev = 10/10/10/0 ms"
    second = "1 packets transmitted, 1 received, 0% packet loss\nrtt min/avg/max/mdev = 13/13/13/0 ms"
    assert source.measurement("INT-600", 1, first).jitter_ms is None
    assert source.measurement("INT-600", 2, second).jitter_ms == 3
