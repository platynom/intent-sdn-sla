"""E14b finding: an OVS linux-htb QoS record must not erase Mininet's netem link delay.

These tests model one switch port's tc state.  Before OVS attaches QoS the port has
Mininet's TCLink tree (root htb 5: -> class 5:1 -> netem 10:).  When ovs-vsctl
creates or extends the QoS record, the fake replaces the root with OVS's tree
(root htb 1:, class 1:fffe, one leaf class 1:(q+1) per queue q) exactly as
ovs-vswitchd does, dropping the netem.  ensure_queue must put the netem back
under every leaf class.
"""
from types import SimpleNamespace

import pytest

from src.common import db as dbm
from src.enforcement import queues

MININET_QDISCS = (
    "qdisc htb 5: root refcnt 2 r2q 10 default 0x1 direct_packets_stat 0 direct_qlen 1000\n"
    "qdisc netem 10: parent 5:1 limit 1000 delay 2ms\n"
)


class FakePort:
    """Minimal model of ovs-vsctl + tc on a single port."""

    def __init__(self, mininet=True, classes_appear=True):
        self.ovs_qos = None  # set of queue ids once OVS QoS exists
        self.netem = {}  # parent -> netem args
        self.mininet = mininet
        self.classes_appear = classes_appear
        self.calls = []

    # -- tc views ---------------------------------------------------------
    def qdisc_show(self):
        if self.ovs_qos is None:
            return MININET_QDISCS if self.mininet else "qdisc noqueue 0: root refcnt 2\n"
        lines = ["qdisc htb 1: root refcnt 2 r2q 10 default 0x1 direct_packets_stat 0"]
        for i, (parent, args) in enumerate(sorted(self.netem.items()), start=1):
            lines.append(f"qdisc netem 80{i:02x}: parent {parent} " + " ".join(args))
        return "\n".join(lines) + "\n"

    def class_show(self):
        if self.ovs_qos is None or not self.classes_appear:
            return ""
        lines = ["class htb 1:fffe root rate 100Mbit ceil 100Mbit burst 1500b cburst 1500b"]
        for q in sorted(self.ovs_qos):
            lines.append(f"class htb {queues.queue_class_id(q)} parent 1:fffe prio 0 rate 12000bit ceil 100Mbit")
        return "\n".join(lines) + "\n"

    # -- subprocess.run replacement -------------------------------------
    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[0] == "tc":
            if argv[1:3] == ["qdisc", "show"]:
                return SimpleNamespace(stdout=self.qdisc_show())
            if argv[1:3] == ["class", "show"]:
                return SimpleNamespace(stdout=self.class_show())
            if argv[1:3] == ["qdisc", "replace"]:
                parent = argv[argv.index("parent") + 1]
                self.netem[parent] = argv[argv.index("netem") + 1:]
                return SimpleNamespace(stdout="")
            raise AssertionError(f"unexpected tc call {argv}")
        # ovs-vsctl
        if "get" in argv:
            return SimpleNamespace(stdout='"qos-1"\n' if self.ovs_qos is not None else "[]\n")
        new_q = {int(a.split(":")[1].split("=")[0]) for a in argv if a.startswith("queues:")}
        if self.ovs_qos is None:
            # Creating the QoS replaces the root qdisc: Mininet's netem is gone.
            self.ovs_qos = set()
            self.netem = {}
        self.ovs_qos |= new_q
        return SimpleNamespace(stdout="")


@pytest.fixture
def conn():
    c = dbm.connect(":memory:")
    dbm.init_db(c)
    yield c
    c.close()


@pytest.fixture
def port(monkeypatch):
    fake = FakePort()
    monkeypatch.setattr(queues.subprocess, "run", fake.run)
    monkeypatch.setattr(queues.time, "sleep", lambda s: None)
    return fake


def test_parse_netem_args_reads_mininet_tclink_line():
    assert queues.parse_netem_args("qdisc netem 10: parent 5:1 limit 1000 delay 2ms") == [
        "limit", "1000", "delay", "2ms",
    ]
    assert queues.parse_netem_args("qdisc netem 10: parent 5:1 limit 1000 delay 40ms  5ms loss 1%") == [
        "limit", "1000", "delay", "40ms", "5ms", "loss", "1%",
    ]
    assert queues.parse_netem_args("qdisc htb 5: root refcnt 2") is None


def test_queue_class_id_uses_hex_minor():
    assert queues.queue_class_id(0) == "1:1"
    assert queues.queue_class_id(1) == "1:2"
    assert queues.queue_class_id(10) == "1:b"


def test_new_qos_keeps_link_delay_on_default_and_intent_queue(port):
    qid = queues.ensure_queue("s1", "s1-eth2", 20, egress_peer="s2")
    assert qid == 1
    # Default queue 0 is created so unqueued traffic stays shaped and delayed.
    create = next(c for c in port.calls if "qos=@newqos" in c)
    assert "queues:0=@q0" in create
    # Mininet's 2 ms netem is restored under both HTB leaf classes.
    assert port.netem == {
        "1:1": ["limit", "1000", "delay", "2ms"],
        "1:2": ["limit", "1000", "delay", "2ms"],
    }


def test_second_intent_on_same_port_gets_netem_without_touching_existing(conn, port):
    q1 = queues.ensure_queue("s1", "s1-eth2", 20, egress_peer="s2", intent_id="INT-A", conn=conn)
    before = [c for c in port.calls if c[:3] == ["tc", "qdisc", "replace"]]
    q2 = queues.ensure_queue("s1", "s1-eth2", 30, egress_peer="s2", intent_id="INT-B", conn=conn)
    after = [c for c in port.calls if c[:3] == ["tc", "qdisc", "replace"]]
    assert q1 != q2
    new = after[len(before):]
    assert [c[c.index("parent") + 1] for c in new] == [queues.queue_class_id(q2)]
    assert set(port.netem) == {"1:1", queues.queue_class_id(q1), queues.queue_class_id(q2)}


def test_injected_fault_is_carried_to_new_queue_classes(conn, port):
    queues.ensure_queue("s1", "s1-eth2", 20, egress_peer="s2", intent_id="INT-A", conn=conn)
    # A fault script raises every netem on the port to 40 ms ...
    for parent in list(port.netem):
        port.netem[parent] = ["limit", "1000", "delay", "40ms"]
    # ... and a new queue added afterwards inherits the live (faulted) delay.
    q2 = queues.ensure_queue("s1", "s1-eth2", 10, egress_peer="s2", intent_id="INT-B", conn=conn)
    assert port.netem[queues.queue_class_id(q2)][-1] == "40ms"


def test_port_without_netem_is_left_alone(monkeypatch):
    fake = FakePort(mininet=False)
    monkeypatch.setattr(queues.subprocess, "run", fake.run)
    queues.ensure_queue("s1", "s1-eth2", 20, egress_peer="s2")
    assert not any(c[:3] == ["tc", "qdisc", "replace"] for c in fake.calls)
    assert fake.netem == {}


def test_missing_htb_class_fails_loudly_and_frees_queue_row(conn, monkeypatch):
    fake = FakePort(classes_appear=False)
    monkeypatch.setattr(queues.subprocess, "run", fake.run)
    monkeypatch.setattr(queues.time, "sleep", lambda s: None)
    ticks = iter(range(100))
    monkeypatch.setattr(queues.time, "monotonic", lambda: next(ticks))
    with pytest.raises(queues.QueueConfigurationError, match="did not appear"):
        queues.ensure_queue("s1", "s1-eth2", 20, egress_peer="s2", intent_id="INT-X", conn=conn)
    assert dbm.intent_queues_for(conn, "INT-X") == []


def test_preservation_can_be_disabled_for_historic_reruns(monkeypatch, port):
    monkeypatch.setenv("TEAM16_PRESERVE_NETEM", "0")
    queues.ensure_queue("s1", "s1-eth2", 20, egress_peer="s2")
    assert not any(c[0] == "tc" for c in port.calls)
    assert port.netem == {}
