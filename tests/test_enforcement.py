"""ST-5 contract tests for OpenFlow enforcement without privileged dependencies."""

from __future__ import annotations

import builtins
import importlib.util
import inspect
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.common import db as dbm
from src.common.models import Guarantee, IntentRecord, IntentState, Match, PathPlan
from src.enforcement import controller, flowmod, queues


REPO = Path(__file__).resolve().parents[1]
SCENARIO = REPO / "experiments" / "scenarios" / "s1_single_intent.sh"


def make_intent(
    intent_id: str = "INT-ST5-001",
    proto: str = "udp",
    dport: int | None = 5001,
) -> IntentRecord:
    """Build the smallest valid intent used by the enforcement contracts."""
    return IntentRecord(
        id=intent_id,
        tenant="st5-tests",
        priority=3,
        match=Match(
            src="10.0.0.1/32",
            dst="10.0.0.2/32",
            proto=proto,
            dport=dport,
        ),
        guarantee=Guarantee(min_bandwidth_mbps=20),
    )


def make_plan(switches: tuple[str, ...]) -> PathPlan:
    """Build a path plan whose links agree with its ordered switch sequence."""
    return PathPlan(
        intent_id="INT-ST5-001",
        switches=switches,
        links=PathPlan.links_for(list(switches)),
        est_latency_ms=5,
        bottleneck_mbps=100,
    )


def make_port_map(switches: tuple[str, ...]) -> dict[tuple[str, str], int]:
    """Build explicit bidirectional links plus both endpoint host ports."""
    port_map: dict[tuple[str, str], int] = {
        (switches[0], "h1"): 101,
        (switches[-1], "h2"): 202,
    }
    for index, (left, right) in enumerate(zip(switches, switches[1:]), start=1):
        port_map[(left, right)] = index * 10 + 1
        port_map[(right, left)] = index * 10 + 2
    return port_map


class FakeParser:
    """Record OpenFlow constructor arguments without importing Ryu."""

    def OFPMatch(self, **kwargs):
        """Return match fields so assertions can inspect the generated contract."""
        return kwargs

    def OFPActionOutput(self, port, max_len=None):
        """Return output action fields without constructing a Ryu object."""
        return {"port": port, "max_len": max_len}

    def OFPInstructionActions(self, instruction_type, actions):
        """Return instruction fields without constructing a Ryu object."""
        return {"type": instruction_type, "actions": actions}

    def OFPFlowMod(self, **kwargs):
        """Return flow-mod fields so table-miss semantics remain observable."""
        return kwargs


class FakeDatapath:
    """Provide the subset of a datapath needed by match and controller tests."""

    id = 1
    ofproto_parser = FakeParser()
    ofproto = SimpleNamespace(
        OFPP_CONTROLLER=0xFFFFFFFD,
        OFPCML_NO_BUFFER=0xFFFF,
        OFPIT_APPLY_ACTIONS=4,
    )

    def __init__(self):
        self.sent: list[dict] = []

    def send_msg(self, message):
        """Capture a controller message instead of contacting a switch."""
        self.sent.append(message)


@pytest.fixture()
def fake_ryu_match(monkeypatch):
    """Exercise Ryu match-building logic with constants and a fake parser."""
    monkeypatch.setattr(flowmod, "RYU_AVAILABLE", True)
    monkeypatch.setattr(flowmod, "ether", SimpleNamespace(ETH_TYPE_IP=0x0800))
    monkeypatch.setattr(
        flowmod,
        "inet",
        SimpleNamespace(IPPROTO_TCP=6, IPPROTO_UDP=17, IPPROTO_ICMP=1),
    )
    return FakeDatapath()


def test_cookie_is_deterministic_across_repeated_calls():
    """Nondeterministic cookies would make installed intent rules impossible to remove."""
    first = flowmod.cookie_for_intent("INT-COOKIE-001")
    assert first == flowmod.cookie_for_intent("INT-COOKIE-001")
    assert first == flowmod.cookie_for_intent("INT-COOKIE-001")


def test_different_intents_receive_different_cookies():
    """Cookie collisions would delete or audit another tenant's flow rules."""
    assert flowmod.cookie_for_intent("INT-A") != flowmod.cookie_for_intent("INT-B")


@pytest.mark.parametrize("intent_id", ["INT-ASCII", "intent-with-unicode-λ", ""])
def test_cookie_fits_unsigned_openflow_64_bits(intent_id):
    """An out-of-range cookie would be rejected by OpenFlow serialization."""
    cookie = flowmod.cookie_for_intent(intent_id)
    assert 0 <= cookie < 2**64


@pytest.mark.parametrize(
    "switches",
    [("s1", "s7"), ("s1", "s2", "s3", "s7")],
)
def test_rules_have_one_rule_per_switch_in_each_direction(switches):
    """A missing hop rule would black-hole one direction of production traffic."""
    rules = flowmod.rules_for_path(make_plan(switches), make_intent(), make_port_map(switches))
    assert len(rules) == 2 * len(switches)
    assert sum(rule["direction"] == "forward" for rule in rules) == len(switches)
    assert sum(rule["direction"] == "reverse" for rule in rules) == len(switches)


def test_every_rule_carries_the_intent_cookie():
    """A rule without the intent cookie would survive intent withdrawal."""
    switches = ("s1", "s2", "s3", "s7")
    intent = make_intent()
    rules = flowmod.rules_for_path(make_plan(switches), intent, make_port_map(switches))
    assert {rule["cookie"] for rule in rules} == {flowmod.cookie_for_intent(intent.id)}


def test_rules_only_name_switches_in_the_plan():
    """Programming an off-path switch would leak policy into unrelated traffic."""
    switches = ("s1", "s6", "s7")
    rules = flowmod.rules_for_path(make_plan(switches), make_intent(), make_port_map(switches))
    assert {rule["switch"] for rule in rules} <= set(switches)


def test_output_ports_all_come_from_the_supplied_port_map():
    """Invented port numbers would send packets to the wrong host or link."""
    switches = ("s1", "s4", "s5", "s7")
    port_map = make_port_map(switches)
    rules = flowmod.rules_for_path(make_plan(switches), make_intent(), port_map)
    assert {rule["actions"][0]["port"] for rule in rules} <= set(port_map.values())


def test_missing_endpoint_port_is_not_silently_invented():
    """Defaulting an absent host port to one can redirect customer traffic silently."""
    switches = ("s1", "s7")
    port_map = make_port_map(switches)
    del port_map[("s7", "h2")]
    with pytest.raises(KeyError):
        flowmod.rules_for_path(make_plan(switches), make_intent(), port_map)


def test_reverse_rules_use_mirrored_link_and_host_ports():
    """Unmirrored reverse ports would make TCP replies and acknowledgements fail."""
    switches = ("s1", "s2", "s3", "s7")
    port_map = make_port_map(switches)
    rules = flowmod.rules_for_path(make_plan(switches), make_intent(), port_map)
    reverse = {rule["switch"]: rule for rule in rules if rule["direction"] == "reverse"}
    assert reverse["s1"]["actions"] == [{"type": "OUTPUT", "port": port_map[("s1", "h1")]}]
    assert reverse["s2"]["actions"] == [{"type": "OUTPUT", "port": port_map[("s2", "s1")]}]
    assert reverse["s3"]["actions"] == [{"type": "OUTPUT", "port": port_map[("s3", "s2")]}]
    assert reverse["s7"]["actions"] == [{"type": "OUTPUT", "port": port_map[("s7", "s3")]}]


def test_reverse_rules_swap_source_and_destination():
    """Unswapped reverse matches would install duplicate forward-only rules."""
    switches = ("s1", "s7")
    rules = flowmod.rules_for_path(make_plan(switches), make_intent(), make_port_map(switches))
    reverse = [rule for rule in rules if rule["direction"] == "reverse"]
    assert all(rule["match"]["src"] == "10.0.0.2/32" for rule in reverse)
    assert all(rule["match"]["dst"] == "10.0.0.1/32" for rule in reverse)


def test_build_match_always_sets_ipv4_eth_type(fake_ryu_match):
    """OVS will never match IP protocol fields unless eth_type explicitly selects IPv4."""
    match = flowmod.build_match(fake_ryu_match, make_intent(proto="any", dport=None))
    assert match["eth_type"] == 0x0800


@pytest.mark.parametrize("proto,expected", [("udp", 17), ("tcp", 6), ("icmp", 1)])
def test_build_match_sets_openflow_ip_protocol(fake_ryu_match, proto, expected):
    """A wrong IP protocol number would apply policy to the wrong packet class."""
    match = flowmod.build_match(fake_ryu_match, make_intent(proto=proto, dport=5001))
    assert match["ip_proto"] == expected


def test_build_match_omits_protocol_for_any(fake_ryu_match):
    """Adding a protocol to an any-intent would unexpectedly exclude valid traffic."""
    match = flowmod.build_match(fake_ryu_match, make_intent(proto="any", dport=None))
    assert "ip_proto" not in match


@pytest.mark.parametrize("proto,field", [("tcp", "tcp_dst"), ("udp", "udp_dst")])
def test_build_match_adds_dport_only_to_transport_protocol(fake_ryu_match, proto, field):
    """Dropping a requested transport port would over-broaden the production policy."""
    match = flowmod.build_match(fake_ryu_match, make_intent(proto=proto, dport=8443))
    assert match[field] == 8443


@pytest.mark.parametrize("proto", ["icmp", "any"])
def test_build_match_never_adds_dport_to_non_transport_protocol(fake_ryu_match, proto):
    """An ICMP or wildcard L4 port field creates an invalid or permanently dead match."""
    match = flowmod.build_match(fake_ryu_match, make_intent(proto=proto, dport=8443))
    assert "tcp_dst" not in match
    assert "udp_dst" not in match


def test_build_match_uses_ipv4_fields_and_normalizes_host_prefixes(fake_ryu_match):
    """Wrong field names or retained /32 syntax can break switch match encoding."""
    match = flowmod.build_match(fake_ryu_match, make_intent())
    assert match["ipv4_src"] == "10.0.0.1"
    assert match["ipv4_dst"] == "10.0.0.2"
    assert "src" not in match and "dst" not in match


def test_build_match_fallback_retains_openflow_semantics(monkeypatch):
    """Dry-run enforcement must not hide match defects on machines without Ryu."""
    monkeypatch.setattr(flowmod, "RYU_AVAILABLE", False)
    match = flowmod.build_match(FakeDatapath(), make_intent(proto="udp", dport=5001))
    assert match == {
        "eth_type": 0x0800,
        "ipv4_src": "10.0.0.1",
        "ipv4_dst": "10.0.0.2",
        "ip_proto": 17,
        "udp_dst": 5001,
    }


def test_queue_minimum_mbps_is_converted_to_bits_per_second(monkeypatch):
    """Treating Mbps as bps would throttle a 20 Mbps customer SLA to unusable speed."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        stdout = "[]\n" if "get" in argv else ""
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(queues.subprocess, "run", fake_run)
    queues.ensure_queue("s1", "s1-eth2", 20)
    assert any("other-config:min-rate=20000000" in argv for argv in calls)


def test_ensure_queue_reuses_existing_qos_record(monkeypatch):
    """Creating a second QoS record can silently disable the newly configured queue."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        stdout = '"qos-existing"\n' if "get" in argv else ""
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(queues.subprocess, "run", fake_run)
    queues.ensure_queue("s1", "s1-eth2", 20)
    assert calls[1][calls[1].index("qos") + 1] == "qos-existing"
    assert not any(
        left == "create" and right == "qos"
        for left, right in zip(calls[1], calls[1][1:])
    )
    assert "qos=@newqos" not in calls[1]


def test_ensure_queue_creates_qos_when_port_has_none(monkeypatch):
    """Failing to create QoS on an unconfigured port leaves bandwidth unenforced."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout="[]\n" if "get" in argv else "")

    monkeypatch.setattr(queues.subprocess, "run", fake_run)
    queues.ensure_queue("s1", "s1-eth2", 20)
    assert "qos=@newqos" in calls[1]
    assert "type=linux-htb" in calls[1]


def test_clear_queues_is_safe_when_nothing_is_configured(monkeypatch):
    """Cleanup on a fresh switch must not issue destructive commands for empty UUIDs."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout="[]\n")

    monkeypatch.setattr(queues.subprocess, "run", fake_run)
    queues.clear_queues("s1", "s1-eth2")
    assert calls == [["ovs-vsctl", "--if-exists", "get", "port", "s1-eth2", "qos"]]


def test_clear_queues_removes_attached_qos_and_queues(monkeypatch):
    """Leaked QoS records accumulate stale shaping state across scenario runs."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[-1] == "qos":
            return SimpleNamespace(stdout='"qos-1"\n')
        if argv[-1] == "queues":
            return SimpleNamespace(stdout="{1=queue-1, 2=queue-2}\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(queues.subprocess, "run", fake_run)
    queues.clear_queues("s1", "s1-eth2")
    assert ["ovs-vsctl", "clear", "port", "s1-eth2", "qos"] in calls
    assert ["ovs-vsctl", "--if-exists", "destroy", "qos", "qos-1"] in calls
    assert ["ovs-vsctl", "--if-exists", "destroy", "queue", "queue-1"] in calls
    assert ["ovs-vsctl", "--if-exists", "destroy", "queue", "queue-2"] in calls


def test_controller_module_imports_when_ryu_is_unavailable(monkeypatch):
    """Operators must be able to run unit tests and tooling without installing Ryu."""
    original_import = builtins.__import__

    def import_without_ryu(name, *args, **kwargs):
        if name == "ryu" or name.startswith("ryu."):
            raise ImportError("Ryu deliberately unavailable in ST-5 test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_ryu)
    spec = importlib.util.spec_from_file_location("controller_without_ryu", controller.__file__)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.RYU_AVAILABLE is False
    assert module.Team16Controller is not None


def test_controller_declares_openflow_13_even_without_ryu():
    """An absent version declaration lets switches negotiate an incompatible protocol."""
    assert controller.Team16Controller.OFP_VERSIONS == [0x04]


def test_install_plan_has_the_public_st5_signature():
    """Signature drift would break the path planner-to-enforcer integration."""
    assert list(inspect.signature(controller.Team16Controller.install_plan).parameters) == [
        "self",
        "plan",
        "intent",
        "event_bus",
    ]


def test_remove_intent_has_the_public_st5_signature():
    """Signature drift would prevent intent withdrawal from removing stale flows."""
    assert list(inspect.signature(controller.Team16Controller.remove_intent).parameters) == [
        "self",
        "intent_id",
        "event_bus",
    ]


def _controller_for_db_sync(switches):
    """Construct the controller state needed by database synchronization tests."""
    instance = object.__new__(controller.Team16Controller)
    instance.datapaths = {switch: object() for switch in switches}
    instance._installed_plans = {}
    instance.logger = SimpleNamespace(
        info=lambda *args: None,
        error=lambda *args: None,
        exception=lambda *args: None,
    )
    return instance


def test_controller_installs_persisted_path_and_activates_intent(tmp_path, monkeypatch):
    """Without the database handoff, accepted API intents never reach live switches."""
    db_path = tmp_path / "state.db"
    real_connect = dbm.connect
    conn = real_connect(db_path)
    dbm.init_db(conn)
    intent = make_intent()
    plan = make_plan(("s1", "s2", "s3", "s7"))
    dbm.save_intent(conn, intent)
    dbm.save_path(conn, plan)
    conn.close()

    instance = _controller_for_db_sync(plan.switches)
    installed = []
    monkeypatch.setattr(controller.dbm, "connect", lambda: real_connect(db_path))
    monkeypatch.setattr(instance, "install_plan", lambda found_plan, found_intent: installed.append((found_plan, found_intent)) or 8)

    instance._sync_intents_from_db()

    assert len(installed) == 1
    check = real_connect(db_path)
    assert dbm.load_intent(check, intent.id).state is IntentState.ACTIVE
    check.close()


def test_controller_waits_for_every_path_switch(tmp_path, monkeypatch):
    """Partial rule installation can black-hole production traffic mid-path."""
    db_path = tmp_path / "state.db"
    real_connect = dbm.connect
    conn = real_connect(db_path)
    dbm.init_db(conn)
    intent = make_intent()
    plan = make_plan(("s1", "s2", "s3", "s7"))
    dbm.save_intent(conn, intent)
    dbm.save_path(conn, plan)
    conn.close()

    instance = _controller_for_db_sync(("s1", "s2", "s3"))
    monkeypatch.setattr(controller.dbm, "connect", lambda: real_connect(db_path))
    monkeypatch.setattr(instance, "install_plan", lambda *args: pytest.fail("partial path installed"))

    instance._sync_intents_from_db()

    check = real_connect(db_path)
    assert dbm.load_intent(check, intent.id).state is IntentState.PENDING
    check.close()


def test_controller_removes_withdrawn_persisted_intent(tmp_path, monkeypatch):
    """Ignoring API withdrawals leaves stale customer policy active in switches."""
    db_path = tmp_path / "state.db"
    real_connect = dbm.connect
    conn = real_connect(db_path)
    dbm.init_db(conn)
    intent = make_intent()
    intent.state = IntentState.WITHDRAWN
    dbm.save_intent(conn, intent)
    conn.close()

    instance = _controller_for_db_sync(())
    instance._installed_plans[intent.id] = (None, 1.0)
    removed = []
    monkeypatch.setattr(controller.dbm, "connect", lambda: real_connect(db_path))
    monkeypatch.setattr(instance, "remove_intent", lambda intent_id: removed.append(intent_id) or 1)

    instance._sync_intents_from_db()

    assert removed == [intent.id]
    assert intent.id not in instance._installed_plans


def test_switch_features_installs_priority_zero_controller_table_miss(monkeypatch):
    """Without an explicit priority-zero controller rule, unmatched packets are dropped."""
    instance = object.__new__(controller.Team16Controller)
    instance.datapaths = {}
    instance.dpid_to_name = {}
    instance.name_to_dpid = {}
    instance.logger = SimpleNamespace(info=lambda *args: None)
    monkeypatch.setattr(instance, "_discover_ports", lambda datapath: None)
    datapath = FakeDatapath()
    event = SimpleNamespace(msg=SimpleNamespace(datapath=datapath))

    instance.switch_features_handler(event)

    assert len(datapath.sent) == 1
    flow = datapath.sent[0]
    assert flow["priority"] == 0
    action = flow["instructions"][0]["actions"][0]
    assert action["port"] == datapath.ofproto.OFPP_CONTROLLER
    assert action["max_len"] == datapath.ofproto.OFPCML_NO_BUFFER


def test_single_intent_scenario_exists():
    """A missing baseline scenario prevents end-to-end enforcement validation."""
    assert SCENARIO.is_file()


def test_single_intent_scenario_is_tracked_executable():
    """A non-executable scenario fails immediately in Linux CI and demo automation."""
    result = subprocess.run(
        ["git", "ls-files", "--stage", "experiments/scenarios/s1_single_intent.sh"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.startswith("100755 ")


def test_single_intent_scenario_passes_bash_syntax_check():
    """A shell syntax error would abort the live SDN demonstration before cleanup."""
    git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
    bash = str(git_bash) if git_bash.exists() else shutil.which("bash")
    assert bash is not None, "bash is required to validate the shipped scenario"
    subprocess.run([bash, "-n", str(SCENARIO)], check=True)


def test_single_intent_scenario_enables_strict_shell_mode():
    """Without strict mode, failed controller or API commands can produce false passes."""
    assert "set -euo pipefail" in SCENARIO.read_text(encoding="utf-8")


def test_single_intent_scenario_registers_cleanup_trap():
    """Without a trap, failed runs leave Mininet and controller processes behind."""
    script = SCENARIO.read_text(encoding="utf-8")
    assert "trap " in script
    assert "cleanup" in script
