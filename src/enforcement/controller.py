"""
M4 Ryu Enforcement Controller.

Ryu OpenFlow 1.3 application that installs table-miss flow rules, discovers
topology port mappings, installs flow rules for computed PathPlans, and configures
OVS QoS/HTB queues.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

try:
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
    from ryu.ofproto import ofproto_v1_3
    from ryu.lib import hub
    from ryu.topology import event as topo_event
    from ryu.topology.api import get_link, get_switch
    RYU_AVAILABLE = True
    BaseApp = app_manager.RyuApp
except ImportError:  # pragma: no cover
    RYU_AVAILABLE = False
    BaseApp = object
    CONFIG_DISPATCHER = "CONFIG_DISPATCHER"
    MAIN_DISPATCHER = "MAIN_DISPATCHER"
    ofproto_v1_3 = None
    ofp_event = None
    topo_event = None
    get_link = None
    get_switch = None
    hub = None

    def set_ev_cls(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

from src.common import db as dbm
from src.common.events import EventBus, path_installed
from src.common.models import IntentRecord, IntentState, PathPlan
from src.enforcement.flowmod import cookie_for_intent, install, remove, rules_for_path
from src.enforcement.queues import ensure_queue
from topology.topology_spec import HOSTS, SWITCHES


class Team16Controller(BaseApp):
    """
    Ryu controller managing OpenFlow 1.3 switches for the Team16 5G transport topology.
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION if RYU_AVAILABLE else 0x04]

    def __init__(self, *args, **kwargs):
        if RYU_AVAILABLE:
            super().__init__(*args, **kwargs)
        self.logger = logging.getLogger("Team16Controller")
        self.datapaths: Dict[str, Any] = {}
        self.dpid_to_name: Dict[int, str] = {}
        self.name_to_dpid: Dict[str, int] = {}
        # (sw_a, sw_b) -> out_port or (sw_a, host_name) -> out_port
        self.port_map: Dict[Tuple[str, str], int] = {}
        self.event_bus: Optional[EventBus] = None
        # SQLite is the cross-process handoff between M1/M3 and this Ryu app.
        # The value records the path revision already installed for each intent.
        self._installed_plans: Dict[str, Tuple[Optional[int], float]] = {}
        self._sync_thread = hub.spawn(self._enforcement_loop) if RYU_AVAILABLE else None

    def _enforcement_loop(self) -> None:
        """Install paths persisted by the API as their switches become ready."""
        while True:
            try:
                self._sync_intents_from_db()
            except Exception:
                self.logger.exception("Failed to synchronize persisted intents")
            hub.sleep(0.5)

    def _sync_intents_from_db(self) -> None:
        """Apply new paths and withdrawals found in the shared SQLite database."""
        conn = dbm.connect()
        try:
            dbm.init_db(conn)
            rows = conn.execute(
                "SELECT id, state FROM intents "
                "WHERE state IN ('pending', 'admitted', 'active', 'withdrawn')"
            ).fetchall()

            for row in rows:
                intent_id = str(row["id"])
                if row["state"] == IntentState.WITHDRAWN.value:
                    if intent_id in self._installed_plans:
                        self.remove_intent(intent_id)
                        self._installed_plans.pop(intent_id, None)
                    continue

                intent = dbm.load_intent(conn, intent_id)
                plan = dbm.current_path(conn, intent_id)
                if intent is None or plan is None:
                    continue

                # Never partially install a path while its switches are still connecting.
                if any(switch not in self.datapaths for switch in plan.switches):
                    continue

                revision = (plan.version, plan.computed_at)
                if self._installed_plans.get(intent_id) == revision:
                    continue

                if intent_id in self._installed_plans:
                    self.remove_intent(intent_id)

                installed = self.install_plan(plan, intent)
                expected = 2 * len(plan.switches)
                if installed != expected:
                    self.logger.error(
                        "Installed %s of %s expected rules for intent %s",
                        installed,
                        expected,
                        intent_id,
                    )
                    continue

                intent.state = IntentState.ACTIVE
                intent.updated_at = time.time()
                dbm.save_intent(conn, intent)
                self._installed_plans[intent_id] = revision
                self.logger.info(
                    "Activated intent %s with %s rules on path %s",
                    intent_id,
                    installed,
                    " -> ".join(plan.switches),
                )
        finally:
            conn.close()

    def _dpid_to_sw_name(self, dpid: int) -> str:
        """Convert integer DPID (e.g. 1, 7) to switch name ('s1', 's7')."""
        return f"s{dpid}"

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER) if RYU_AVAILABLE else lambda fn: fn
    def switch_features_handler(self, ev):
        """
        Install table-miss flow entry upon switch connection.

        Priority 0 with no match (matches all) and output to OFPP_CONTROLLER so unmatched
        packets are forwarded to the controller rather than silently dropped by OVS.
        """
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        sw_name = self._dpid_to_sw_name(dpid)

        self.datapaths[sw_name] = datapath
        self.dpid_to_name[dpid] = sw_name
        self.name_to_dpid[sw_name] = dpid

        # Install table-miss flow: match all, send to controller
        match = parser.OFPMatch()
        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER
            )
        ]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=0,
            match=match,
            instructions=inst,
        )
        datapath.send_msg(mod)
        self.logger.info("Installed table-miss flow entry on switch %s (dpid=%s)", sw_name, dpid)

        # Trigger topology / port discovery
        self._discover_ports(datapath)

    def _discover_ports(self, datapath: Any):
        """Discover port mappings using topology API or port descriptions."""
        if not RYU_AVAILABLE:
            return

        try:
            # Query switch links
            links = get_link(self, datapath.id) if get_link else []
            for link in links:
                src_sw = self._dpid_to_sw_name(link.src.dpid)
                dst_sw = self._dpid_to_sw_name(link.dst.dpid)
                self.port_map[(src_sw, dst_sw)] = link.src.port_no
                self.port_map[(dst_sw, src_sw)] = link.dst.port_no
        except Exception:
            pass

        # Build fallback / deterministic port map based on known host-switch attachments if not already present
        # In Team16Topo:
        # Switch interfaces are allocated in order:
        # First all hosts attached to that switch, then switch-to-switch links in order.
        # We also discover dynamically via packet_in or LLDP events when available.
        self._init_default_port_map()
        self.logger.info("Current port map: %s", self.port_map)

    def _init_default_port_map(self):
        """
        Initialize the deterministic port map according to Team16Topo interface allocations.

        In Team16Topo:
          Each switch adds host access links first, then switch-to-switch links in LINKS order.
          s1: h1 (eth1), s2 (eth2), s4 (eth3), s6 (eth4)
          s2: h5 (eth1), s1 (eth2), s3 (eth3)
          s3: h7 (eth1), s2 (eth2), s7 (eth3)
          s4: h3 (eth1), s1 (eth2), s5 (eth3)
          s5: h4 (eth1), s4 (eth2), s7 (eth3)
          s6: h6 (eth1), s1 (eth2), s7 (eth3)
          s7: h2 (eth1), h8 (eth2), s3 (eth3), s5 (eth4), s6 (eth5)
        """
        from topology.topology_spec import LINKS

        port_counts: Dict[str, int] = {sw: 0 for sw in SWITCHES}

        # 1. Host links
        for host in HOSTS:
            port_counts[host.switch] += 1
            self.port_map.setdefault((host.switch, host.name), port_counts[host.switch])

        # 2. Switch links
        for link in LINKS:
            port_counts[link.a] += 1
            self.port_map.setdefault((link.a, link.b), port_counts[link.a])
            port_counts[link.b] += 1
            self.port_map.setdefault((link.b, link.a), port_counts[link.b])

    def get_datapath(self, switch_name: str) -> Any:
        return self.datapaths.get(switch_name)

    def get_all_datapaths(self) -> list[Any]:
        return list(self.datapaths.values())

    def install_plan(
        self,
        plan: PathPlan,
        intent: IntentRecord,
        event_bus: Optional[EventBus] = None,
    ) -> int:
        """
        Install OpenFlow rules and configure QoS queues for a computed PathPlan.

        Generates flow rules using rules_for_path, installs them to datapaths,
        configures HTB queues if min_bandwidth_mbps is requested, and emits
        events.path_installed(...) on success.
        """
        self._init_default_port_map()

        # Configure HTB queues along the path if min_bandwidth_mbps is specified
        if intent.guarantee.min_bandwidth_mbps:
            min_bw = intent.guarantee.min_bandwidth_mbps
            switches = list(plan.switches)
            for idx, sw in enumerate(switches[:-1]):
                next_sw = switches[idx + 1]
                out_port_num = self.port_map.get((sw, next_sw))
                if out_port_num is not None:
                    # In OVS, port name is typically f"{sw}-eth{out_port_num}"
                    port_name = f"{sw}-eth{out_port_num}"
                    ensure_queue(switch=sw, port=port_name, min_mbps=min_bw)

        # Generate OpenFlow 1.3 rules
        rules = rules_for_path(plan=plan, intent=intent, port_map=self.port_map)
        installed_count = install(self, rules)

        # Emit path_installed event
        bus = event_bus or self.event_bus
        if bus is not None:
            ev = path_installed(
                intent_id=intent.id,
                switches=list(plan.switches),
                mode="direct",
                rules=installed_count,
            )
            bus.publish(ev)

        return installed_count

    def remove_intent(
        self,
        intent_id: str,
        event_bus: Optional[EventBus] = None,
    ) -> int:
        """
        Remove all flow rules associated with an intent by its deterministic cookie.
        """
        cookie = cookie_for_intent(intent_id)
        return remove(self, cookie)
