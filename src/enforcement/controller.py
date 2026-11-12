"""
M4 Ryu Enforcement Controller.

Ryu OpenFlow 1.3 application that installs table-miss flow rules, discovers
topology port mappings, installs flow rules for computed PathPlans, and configures
OVS QoS/HTB queues.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import (
        CONFIG_DISPATCHER,
        DEAD_DISPATCHER,
        MAIN_DISPATCHER,
        set_ev_cls,
    )
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
    DEAD_DISPATCHER = "DEAD_DISPATCHER"
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

from src.admission.feasibility import reconcile_preempted_intents
from src.common import db as dbm
from src.common.audit import AuditLog
from src.common.events import (
    Event,
    EventBus,
    EventType,
    Severity,
    path_installed,
    sla_violated,
)
from src.common.models import Consistency, IntentRecord, IntentState, PathPlan
from src.enforcement.flowmod import cookie_for_intent, install, remove, rules_for_path
from src.enforcement.queues import ensure_queue, remove_intent_queues
from src.enforcement import two_phase
from src.telemetry.loop import ControlLoop
from topology.topology_spec import HOSTS, SWITCHES, build_graph


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
        self.event_bus: Optional[EventBus] = EventBus()
        # SQLite is the cross-process handoff between M1/M3 and this Ryu app.
        # The value records the path revision already installed for each intent.
        self._installed_plans: Dict[str, Tuple[Optional[int], float]] = {}
        self._event_conn = None
        self._audit_log = None
        self._control_loop = None
        self._seen_violation_ids = set()
        self._last_dispatched_rowid = 0
        self._unresolved_violations: Dict[str, Tuple[Event, int]] = {}
        self._pending_barriers: Dict[Tuple[int, int], threading.Event] = {}
        self._xid_counter = 1000
        self._active_install_errors: List[Dict[str, Any]] = []
        self._ofp_errors: List[Dict[str, Any]] = []
        self._base_graph = build_graph()
        if RYU_AVAILABLE:
            self._event_conn = dbm.connect()
            dbm.init_db(self._event_conn)
            self._audit_log = AuditLog(self._event_conn)
            self.event_bus.subscribe(self._audit_log.record)
            self._control_loop = ControlLoop(
                self._event_conn, build_graph(), self, self.event_bus, self._audit_log
            )
        self._installed_plan_records: Dict[str, PathPlan] = {}
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
            if not hasattr(self, "_installed_plan_records"):
                self._installed_plan_records = {}
            rows = conn.execute(
                "SELECT id, state FROM intents "
                "WHERE state IN ('pending', 'admitted', 'active', 'withdrawn', 'preempted') "
                "ORDER BY CASE state WHEN 'preempted' THEN 0 "
                "WHEN 'withdrawn' THEN 1 ELSE 2 END, id"
            ).fetchall()

            for row in rows:
                intent_id = str(row["id"])
                if row["state"] in (
                    IntentState.WITHDRAWN.value,
                    IntentState.PREEMPTED.value,
                ):
                    if intent_id in self._installed_plans:
                        self.remove_intent(intent_id)
                        self._installed_plans.pop(intent_id, None)
                        getattr(self, "_installed_plan_records", {}).pop(intent_id, None)
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

                if intent_id in self._installed_plans and intent.consistency is not Consistency.STRICT:
                    self.remove_intent(intent_id)
                    self._installed_plans.pop(intent_id, None)
                    getattr(self, "_installed_plan_records", {}).pop(intent_id, None)

                try:
                    installed = self.install_plan(plan, intent)
                except Exception as exc:
                    self.logger.error(
                        "Failed to install plan for intent %s: %s", intent_id, exc
                    )
                    fail_ev = Event(
                        type=EventType.PATH_INSTALL_FAILED,
                        intent_id=intent_id,
                        severity=Severity.ERROR,
                        message=f"Path installation failed for {intent_id}: {exc}",
                        payload={"intent_id": intent_id, "error": str(exc)},
                    )
                    dbm.save_event(conn, fail_ev)
                    if getattr(self, "event_bus", None) is not None:
                        self.event_bus.publish(fail_ev)
                    continue

                expected = 2 * len(plan.switches)
                if installed != expected:
                    self.logger.error(
                        "Installed %s of %s expected rules for intent %s",
                        installed,
                        expected,
                        intent_id,
                    )
                    fail_ev = Event(
                        type=EventType.PATH_INSTALL_FAILED,
                        intent_id=intent_id,
                        severity=Severity.ERROR,
                        message=f"Installed {installed} of {expected} expected rules for {intent_id}",
                        payload={"intent_id": intent_id, "installed": installed, "expected": expected},
                    )
                    dbm.save_event(conn, fail_ev)
                    continue

                intent.state = IntentState.ACTIVE
                intent.updated_at = time.time()
                dbm.save_intent(conn, intent)
                installed_plan = self._installed_plan_records.get(intent_id, plan)
                self._installed_plans[intent_id] = (
                    installed_plan.version, installed_plan.computed_at
                )
                self._installed_plan_records[intent_id] = installed_plan
                self.logger.info(
                    "Activated intent %s with %s rules on path %s",
                    intent_id,
                    installed,
                    " -> ".join(plan.switches),
                )

            # M5 runs in a separate process. Its durable SQLite event rows are
            # the handoff into this controller process's in-memory event bus.
            self._dispatch_persisted_violations(conn)
        finally:
            conn.close()

    def _dispatch_persisted_violations(self, conn) -> None:
        """Publish each unresolved M5 violation once to this process's bus (P6 bounded scan).

        Tracks the highest processed SQLite rowid so each 0.5 s sync cycle only
        inspects newly appended event rows instead of rescanning the full table.
        """
        if getattr(self, "event_bus", None) is None:
            return
        if not hasattr(self, "_seen_violation_ids"):
            self._seen_violation_ids = set()
        if not hasattr(self, "_last_dispatched_rowid"):
            self._last_dispatched_rowid = 0
        if not hasattr(self, "_unresolved_violations"):
            self._unresolved_violations = {}

        resolution_types = (
            EventType.SLA_RESTORED.value,
            EventType.PATH_INSTALLED.value,
            EventType.PATH_INSTALL_FAILED.value,
            EventType.PATH_INFEASIBLE.value,
            EventType.VIOLATION_SUPPRESSED.value,
        )
        placeholders = ", ".join("?" for _ in resolution_types)
        rows = conn.execute(
            "SELECT rowid AS event_order, id, type, severity, intent_id, at, "
            "message, payload_json "
            "FROM events WHERE rowid > ? AND (type = ? OR type IN (" + placeholders + ")) "
            "ORDER BY rowid ASC",
            (self._last_dispatched_rowid, EventType.SLA_VIOLATED.value) + resolution_types,
        ).fetchall()

        causal_parts = {"measurement", "threshold", "decision", "action"}
        restorations_to_publish: List[Event] = []
        for row in rows:
            event_order = int(row["event_order"])
            if event_order > self._last_dispatched_rowid:
                self._last_dispatched_rowid = event_order
            event = Event(
                id=str(row["id"]),
                type=EventType(row["type"]),
                severity=Severity(row["severity"]),
                intent_id=row["intent_id"],
                at=float(row["at"]),
                message=row["message"],
                payload=json.loads(row["payload_json"]),
            )
            if not event.intent_id:
                continue
            if event.type is EventType.SLA_VIOLATED:
                self._unresolved_violations[event.intent_id] = (event, event_order)
            elif event.type is EventType.SLA_RESTORED or causal_parts.issubset(event.payload):
                prev = self._unresolved_violations.get(event.intent_id)
                if prev is not None and event_order > prev[1]:
                    self._unresolved_violations.pop(event.intent_id, None)
                if event.type is EventType.SLA_RESTORED and event.id not in self._seen_violation_ids:
                    self._seen_violation_ids.add(event.id)
                    restorations_to_publish.append(event)

        actionable = []
        for intent_id, (violation, _violation_order) in list(
            self._unresolved_violations.items()
        ):
            if violation.id in self._seen_violation_ids:
                self._unresolved_violations.pop(intent_id, None)
                continue
            current_path = dbm.current_path(conn, intent_id)
            if current_path is not None and current_path.computed_at > violation.at:
                self._unresolved_violations.pop(intent_id, None)
                continue
            self._seen_violation_ids.add(violation.id)
            self._unresolved_violations.pop(intent_id, None)
            actionable.append(violation)

        to_emit = actionable + restorations_to_publish
        if len(to_emit) <= 1 or not RYU_AVAILABLE or hub is None:
            for ev in to_emit:
                self.event_bus.publish(ev)
        else:
            threads = [hub.spawn(self.event_bus.publish, ev) for ev in to_emit]
            hub.joinall(threads)

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

        # Install table-miss flow (with optional OpenFlow 1.3 packet-in meter for P7)
        match = parser.OFPMatch()
        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER
            )
        ]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        use_meter = (
            hasattr(parser, "OFPMeterMod")
            and hasattr(parser, "OFPInstructionMeter")
            and hasattr(parser, "OFPMeterBandDrop")
            and os.environ.get("TEAM16_TABLE_MISS_METER", "1") == "1"
        )
        if use_meter:
            meter_mod = parser.OFPMeterMod(
                datapath=datapath,
                command=getattr(ofproto, "OFPMC_ADD", 0),
                flags=getattr(ofproto, "OFPMF_PKTPS", 1),
                meter_id=1,
                bands=[parser.OFPMeterBandDrop(rate=50, burst_size=10)],
            )
            datapath.send_msg(meter_mod)
            inst = [
                parser.OFPInstructionMeter(1),
                parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions),
            ]
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
        if not hasattr(self, "_installed_plan_records"):
            self._installed_plan_records = {}
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
        configures per-intent HTB queues if min_bandwidth_mbps is requested,
        and emits events.path_installed(...) on success. Rolls back and audits
        PATH_INSTALL_FAILED on queue, barrier, or OpenFlow error failure.
        """
        self._init_default_port_map()
        if not hasattr(self, "_installed_plans"):
            self._installed_plans = {}
        if not hasattr(self, "_installed_plan_records"):
            self._installed_plan_records = {}
        self._active_install_errors = []

        old_plan = self._installed_plan_records.get(intent.id)
        if old_plan is not None and old_plan.computed_at == plan.computed_at:
            old_plan = None

        conn = dbm.connect()
        try:
            dbm.init_db(conn)
            if old_plan is None:
                stored_plan = dbm.current_path(conn, intent.id)
                if stored_plan is not None and stored_plan.computed_at != plan.computed_at:
                    old_plan = stored_plan

            prior_queues = dbm.intent_queues_for(conn, intent.id)
            old_keep_ports = {(r["switch"], r["port"]) for r in prior_queues}
            queue_ids: Dict[str, int] = {}
            new_keep_ports: set[Tuple[str, str]] = set()

            try:
                # Configure per-intent HTB queues along the path if min_bandwidth_mbps is specified
                if intent.guarantee.min_bandwidth_mbps:
                    min_bw = dbm.effective_min_bandwidth_mbps(conn, intent)
                    switches = list(plan.switches)
                    for idx, sw in enumerate(switches[:-1]):
                        next_sw = switches[idx + 1]
                        out_port_num = self.port_map.get((sw, next_sw))
                        if out_port_num is not None:
                            port_name = f"{sw}-eth{out_port_num}"
                            qid = ensure_queue(
                                switch=sw,
                                port=port_name,
                                min_mbps=min_bw,
                                egress_peer=next_sw,
                                intent_id=intent.id,
                                conn=conn,
                            )
                            queue_ids[sw] = qid
                            new_keep_ports.add((sw, port_name))

                if intent.consistency is Consistency.STRICT:
                    version = plan.version
                    if version not in (0, 1) or (
                        old_plan is not None
                        and old_plan.version in (0, 1)
                        and version == old_plan.version
                    ):
                        version = two_phase.next_version(old_plan)
                        plan = two_phase.with_version(plan, version)
                    installed_count = two_phase.install(
                        self, plan, intent, old_plan, queue_ids=queue_ids or None
                    )
                    mode = "two-phase"
                else:
                    if old_plan is not None:
                        self._remove_intent_flows(intent.id)
                    rules = rules_for_path(
                        plan=plan,
                        intent=intent,
                        port_map=self.port_map,
                        queue_ids=queue_ids or None,
                    )
                    installed_count = install(self, rules)
                    mode = "direct"

                if self._active_install_errors:
                    err = self._active_install_errors[0]
                    raise RuntimeError(
                        f"OpenFlow error during install on dpid={err.get('dpid')}: "
                        f"type={err.get('type')} code={err.get('code')}"
                    )

                expected = 2 * len(plan.switches)
                if installed_count != expected:
                    raise RuntimeError(
                        f"Installed {installed_count} of {expected} expected OpenFlow rules"
                    )

                # Clean up any queues on ports that this intent moved off of (P1)
                remove_intent_queues(
                    conn, intent.id, keep_ports=new_keep_ports, ignore_errors=True
                )
            except Exception as exc:
                # Rollback any newly created queue entries not in old_keep_ports
                remove_intent_queues(
                    conn, intent.id, keep_ports=old_keep_ports, ignore_errors=True
                )
                if old_plan is None:
                    try:
                        self._remove_intent_flows(intent.id)
                    except Exception:
                        pass
                fail_ev = Event(
                    type=EventType.PATH_INSTALL_FAILED,
                    intent_id=intent.id,
                    severity=Severity.ERROR,
                    message=f"Path installation failed for {intent.id}: {exc}",
                    payload={
                        "intent_id": intent.id,
                        "error": str(exc),
                        "switches": list(plan.switches),
                    },
                )
                dbm.save_event(conn, fail_ev)
                bus = event_bus or getattr(self, "event_bus", None)
                if bus is not None:
                    bus.publish(fail_ev)
                raise
        finally:
            conn.close()

        self._installed_plans[intent.id] = (plan.version, plan.computed_at)
        self._installed_plan_records[intent.id] = plan

        # Emit path_installed event
        bus = event_bus or getattr(self, "event_bus", None)
        if bus is not None:
            ev = path_installed(
                intent_id=intent.id,
                switches=list(plan.switches),
                mode=mode,
                rules=installed_count,
            )
            bus.publish(ev)

        return installed_count

    def _remove_intent_flows(self, intent_id: str) -> int:
        cookie = cookie_for_intent(intent_id)
        removed = remove(self, cookie)
        removed += remove(self, two_phase.flowmod.cookie_for_version(intent_id, 0))
        removed += remove(self, two_phase.flowmod.cookie_for_version(intent_id, 1))
        return removed

    def remove_intent(
        self,
        intent_id: str,
        event_bus: Optional[EventBus] = None,
    ) -> int:
        """
        Remove all flow rules and per-intent queues associated with an intent.
        """
        removed = self._remove_intent_flows(intent_id)
        try:
            conn = dbm.connect()
            try:
                remove_intent_queues(conn, intent_id, ignore_errors=True)
            finally:
                conn.close()
        except Exception:
            pass
        return removed

    def _next_xid(self) -> int:
        self._xid_counter = (getattr(self, "_xid_counter", 1000) + 1) & 0x7FFFFFFF
        return self._xid_counter

    def barrier_all(self, switches: Optional[Iterable[str]] = None) -> None:
        """Send OFPBarrierRequest to involved datapaths and wait for OFPBarrierReply (P3)."""
        if not hasattr(self, "_pending_barriers"):
            self._pending_barriers = {}
        if switches is not None:
            datapaths = [
                self.datapaths[sw]
                for sw in switches
                if sw in getattr(self, "datapaths", {}) and self.datapaths[sw] is not None
            ]
        else:
            datapaths = [dp for dp in self.get_all_datapaths() if dp is not None]

        if not datapaths:
            return

        must_wait = bool(getattr(self, "require_barrier_reply", False))
        if not RYU_AVAILABLE and not must_wait:
            return

        timeout = float(
            getattr(
                self,
                "barrier_timeout",
                os.environ.get("TEAM16_BARRIER_TIMEOUT_S", "2.0"),
            )
        )
        wait_list: List[Tuple[int, int, threading.Event]] = []
        for datapath in datapaths:
            parser = getattr(datapath, "ofproto_parser", None)
            if parser is None or not hasattr(parser, "OFPBarrierRequest"):
                continue
            dpid = int(getattr(datapath, "id", 0))
            xid = self._next_xid()
            ev_wait = threading.Event()
            self._pending_barriers[(dpid, xid)] = ev_wait
            msg = parser.OFPBarrierRequest(datapath)
            try:
                msg.xid = xid
            except Exception:
                pass
            datapath.send_msg(msg)
            actual_xid = int(getattr(msg, "xid", None) or xid)
            if actual_xid != xid:
                self._pending_barriers.pop((dpid, xid), None)
                self._pending_barriers[(dpid, actual_xid)] = ev_wait
                xid = actual_xid
            if must_wait or getattr(datapath, "is_active", False) or getattr(datapath, "require_barrier_reply", False):
                wait_list.append((dpid, xid, ev_wait))
            else:
                self._pending_barriers.pop((dpid, xid), None)

        deadline = time.monotonic() + timeout
        for dpid, xid, ev_wait in wait_list:
            while not ev_wait.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._pending_barriers.pop((dpid, xid), None)
                    sw_name = self._dpid_to_sw_name(dpid)
                    raise TimeoutError(
                        f"Timed out waiting for OFPBarrierReply from switch {sw_name} (dpid={dpid}, xid={xid})"
                    )
                if RYU_AVAILABLE and hub is not None and not must_wait:
                    hub.sleep(min(0.005, max(0.001, remaining)))
                else:
                    ev_wait.wait(timeout=min(0.01, max(0.001, remaining)))
            self._pending_barriers.pop((dpid, xid), None)

        if getattr(self, "_active_install_errors", None):
            err = self._active_install_errors[0]
            raise RuntimeError(
                f"OpenFlow error received before barrier on dpid={err.get('dpid')}: "
                f"type={err.get('type')} code={err.get('code')}"
            )

    @set_ev_cls(ofp_event.EventOFPBarrierReply, MAIN_DISPATCHER) if RYU_AVAILABLE else lambda fn: fn
    def barrier_reply_handler(self, ev) -> None:
        """Complete pending barrier waits when a switch replies with OFPBarrierReply (P3)."""
        if not hasattr(self, "_pending_barriers"):
            return
        msg = ev.msg
        dpid = int(getattr(msg.datapath, "id", 0))
        xid = getattr(msg, "xid", None)
        if xid is not None and (dpid, int(xid)) in self._pending_barriers:
            self._pending_barriers[(dpid, int(xid))].set()
        else:
            for (k_dpid, _k_xid), waiter in list(self._pending_barriers.items()):
                if k_dpid == dpid:
                    waiter.set()

    @set_ev_cls(ofp_event.EventOFPErrorMsg, [CONFIG_DISPATCHER, MAIN_DISPATCHER]) if RYU_AVAILABLE else lambda fn: fn
    def error_msg_handler(self, ev) -> None:
        """Record OpenFlow switch errors, fail active installs, and audit PATH_INSTALL_FAILED (P4)."""
        msg = ev.msg
        dpid = int(getattr(getattr(msg, "datapath", None), "id", 0))
        err_info = {
            "dpid": dpid,
            "switch": self._dpid_to_sw_name(dpid) if dpid else "unknown",
            "xid": getattr(msg, "xid", None),
            "type": getattr(msg, "type", None),
            "code": getattr(msg, "code", None),
            "at": time.time(),
        }
        if not hasattr(self, "_ofp_errors"):
            self._ofp_errors = []
        self._ofp_errors.append(err_info)
        if not hasattr(self, "_active_install_errors"):
            self._active_install_errors = []
        self._active_install_errors.append(err_info)

        # Wake any barrier waiters on this datapath so they fail immediately
        for (k_dpid, _k_xid), waiter in list(getattr(self, "_pending_barriers", {}).items()):
            if k_dpid == dpid:
                waiter.set()

    def _set_link_operational_state(self, sw_a: str, sw_b: str, up: bool) -> None:
        """Update link state in the planning graph and SQLite, then replan affected intents (P5)."""
        canonical = PathPlan.links_for([sw_a, sw_b])[0]
        if not hasattr(self, "_base_graph"):
            self._base_graph = build_graph()

        target_graphs = []
        if getattr(self, "_control_loop", None) is not None:
            target_graphs.append(self._control_loop.graph)
        if hasattr(self, "graph") and self.graph is not None:
            target_graphs.append(self.graph)

        for g in target_graphs:
            if up:
                if self._base_graph.has_edge(sw_a, sw_b) and not g.has_edge(sw_a, sw_b):
                    attrs = dict(self._base_graph.get_edge_data(sw_a, sw_b, default={}))
                    attrs["up"] = True
                    g.add_edge(sw_a, sw_b, **attrs)
                elif g.has_edge(sw_a, sw_b):
                    g[sw_a][sw_b]["up"] = True
            else:
                if g.has_edge(sw_a, sw_b):
                    g.remove_edge(sw_a, sw_b)

        conn = getattr(self, "_event_conn", None)
        owns_conn = False
        if conn is None:
            conn = dbm.connect()
            owns_conn = True
        try:
            dbm.set_link_state(conn, canonical, up)
            ev = Event(
                type=EventType.LINK_UP if up else EventType.LINK_DOWN,
                message=f"Link {canonical} is {'UP' if up else 'DOWN'}",
                severity=Severity.INFO if up else Severity.WARNING,
                payload={"link": canonical, "up": up},
            )
            dbm.save_event(conn, ev)
            if getattr(self, "event_bus", None) is not None:
                self.event_bus.publish(ev)

            if not up and getattr(self, "_control_loop", None) is not None:
                for active in dbm.active_intents(conn):
                    cur_plan = dbm.current_path(conn, active.id)
                    if cur_plan is not None and canonical in cur_plan.links:
                        Synthetic = sla_violated(active.id, "loss_pct", 100.0, 0.0)
                        self._control_loop.on_violation(Synthetic)
            elif up:
                reconcile_preempted_intents(
                    conn,
                    self._control_loop.graph if getattr(self, "_control_loop", None) else None,
                    getattr(self, "event_bus", None),
                )
        finally:
            if owns_conn:
                conn.close()

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER) if RYU_AVAILABLE else lambda fn: fn
    def port_status_handler(self, ev) -> None:
        """Handle OpenFlow port status events to mark topology links down or up (P5)."""
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        sw_name = self._dpid_to_sw_name(datapath.id)
        port_no = msg.desc.port_no

        if not getattr(self, "port_map", None):
            self._init_default_port_map()

        peer_sw = next(
            (
                dst
                for (src, dst), pno in self.port_map.items()
                if src == sw_name and pno == port_no and dst in SWITCHES
            ),
            None,
        )
        if peer_sw is None:
            return

        delete_reason = getattr(ofproto, "OFPPR_DELETE", 1)
        cfg_down = getattr(ofproto, "OFPPC_PORT_DOWN", 1)
        st_down = getattr(ofproto, "OFPPS_LINK_DOWN", 1)
        is_down = (
            msg.reason == delete_reason
            or bool(getattr(msg.desc, "config", 0) & cfg_down)
            or bool(getattr(msg.desc, "state", 0) & st_down)
        )
        self._set_link_operational_state(sw_name, peer_sw, up=not is_down)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER]) if RYU_AVAILABLE else lambda fn: fn
    def state_change_handler(self, ev) -> None:
        """Remove disconnected datapaths, mark their links down, and replan affected intents (P5)."""
        datapath = getattr(ev, "datapath", None)
        if datapath is None or getattr(datapath, "id", None) is None:
            return
        sw_name = self._dpid_to_sw_name(datapath.id)
        if ev.state == DEAD_DISPATCHER or ev.state == "DEAD_DISPATCHER":
            self.datapaths.pop(sw_name, None)
            if not getattr(self, "port_map", None):
                self._init_default_port_map()
            peers = [
                dst
                for (src, dst) in self.port_map
                if src == sw_name and dst in SWITCHES
            ]
            for peer_sw in peers:
                self._set_link_operational_state(sw_name, peer_sw, up=False)
        elif ev.state == MAIN_DISPATCHER or ev.state == "MAIN_DISPATCHER":
            self.datapaths[sw_name] = datapath

    def wait_for_packet_drain(self, plan: PathPlan) -> None:
        """Keep old-version rules through a conservative emulated-path drain window."""
        if RYU_AVAILABLE:
            # Two directions plus a 100 ms margin; this is tailored to the
            # project's bounded Mininet topology, not a general WAN guarantee.
            hub.sleep(max(0.1, (2.0 * plan.est_latency_ms / 1000.0) + 0.1))
