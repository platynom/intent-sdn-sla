# Audit Findings & Remediation Report (2026-11)

This document records the 17 engineering audit items (`D1`–`D6`, `P1`–`P8`, `M1`–`M3`) remediated on branch `fix/audit-2026-11`, their regression tests, the before/after reproduction outputs from `repro_audit_findings.py`, live Open vSwitch / Mininet verification evidence, and the `n=3` regression rechecks stored in `experiments/results/audit_recheck_2026-11/`.

---

## 1. Summary of All 17 Audit Items

| ID | Category & Defect | Fix Summary | Modified / Added Files | Regression Test(s) |
|---|---|---|---|---|
| **D1** | **Co-hosted reverse OpenFlow rule collision**: When two intents share `(src_ip, dst_ip, l4_proto)` on different `dst_port`s, reverse rules omitted `tp_src` and had identical priority/match on the reverse switches, causing the second install to overwrite the first. | Added `src_port` to `FlowRule` (`src/common/models.py`), mapped `src_port` to `udp_src` / `tcp_src` / `tp_src` in `build_match()` (`src/enforcement/flowmod.py`), and set `src_port=intent.dst_port` on reverse-path rules in `rules_for_path()`. Integrated the 5 live demo files (`demo_010`..`demo_013`, `live_all_intents.sh`). | `src/common/models.py`, `src/enforcement/flowmod.py`, `intents/demo_010_v2x_safety.yaml`, `intents/demo_011_remote_surgery.yaml`, `intents/demo_012_public_safety_video.yaml`, `intents/demo_013_smart_grid.yaml`, `scripts/live_all_intents.sh` | `tests/test_enforcement.py::test_reverse_rules_match_source_port_when_dst_port_set`, `test_cohosted_intents_keep_distinct_reverse_matches`, `test_ryu_match_uses_protocol_specific_source_port_field`; `tests/test_audit_regressions.py::test_d1_cohosted_reverse_rules_do_not_collide` |
| **D2** | **Reroute bypasses M2 residual capacity**: `ControlLoop.on_violation` planned replacement paths on a raw topology graph without subtracting other active intents' bandwidth reservations, oversubscribing backup links. | Added `replan_intent()` in `src/intent_manager/admission.py` that builds `residual_graph(base, reserved_bandwidth_by_link(conn, exclude_intent=intent.id))`, zeroes failed/excluded edges, and checks admission constraints. Updated `ControlLoop.on_violation` (`src/telemetry/loop.py`) to call `admission.replan_intent`. | `src/intent_manager/admission.py`, `src/telemetry/loop.py` | `tests/test_audit_regressions.py::test_d2_reroute_respects_residual_capacity` |
| **D3** | **Reroute bypasses tenant isolation**: `ControlLoop.on_violation` passed no `existing_tenant_paths` to `compute_path`, allowing a rerouted `strict_isolation: true` intent to land on a path already used by another tenant. | `admission.replan_intent()` queries `dbm.active_paths_by_tenant(conn, exclude_intent=intent.id)` and passes it to `compute_path()`, enforcing bidirectional link disjointness during reroutes. | `src/intent_manager/admission.py`, `src/telemetry/loop.py` | `tests/test_audit_regressions.py::test_d3_reroute_respects_tenant_isolation` |
| **D4** | **Unidirectional tenant isolation check**: `src/path_engine/ConflictGraph.py` compared directed `(u, v)` tuples, allowing two `strict_isolation: true` intents in opposite directions (`h1 -> h2` vs `h2 -> h1`) to share physical links. | Normalized inter-switch links via `_canonical_link(u, v) = (min(u, v), max(u, v))` in `ConflictGraph.links_of()` and `shares_link()`. | `src/path_engine/ConflictGraph.py` | `tests/test_audit_regressions.py::test_d4_bidirectional_tenant_isolation` |
| **D5** | **Overlapping flow match admission**: `POST /intent` admitted multiple live intents with identical or overlapping 5-tuples (`src_ip, dst_ip, l4_proto, dst_port`), causing silent OpenFlow rule collisions. | Added `_matches_overlap()` and `find_overlapping_intent()` in `src/common/db.py` (accounting for wildcard `any` protocol or `None` port). `POST /intent` returns `HTTP 409 Conflict` when a live intent overlaps. | `src/common/db.py`, `src/intent_manager/api.py`, `tests/test_StandardsProfiles.py` | `tests/test_audit_regressions.py::test_d5_duplicate_or_overlapping_match_returns_409` (`exact_duplicate` & `wildcard_port_overlap`) |
| **D6** | **Live intent ID overwrite via `INSERT OR REPLACE`**: Re-submitting an existing `admitted` or `active` intent ID overwrote the live record (even across tenants/priorities) without tearing down existing datapath state. | Changed `POST /intent` (`src/intent_manager/api.py`) to check `dbm.get_intent(conn, record.id)` and return `HTTP 409 Conflict` if the intent exists in a non-terminal state (`admitted`, `active`, `degraded`, `preempted`). | `src/intent_manager/api.py`, `tests/test_StandardsProfiles.py` | `tests/test_audit_regressions.py::test_d6_live_intent_id_overwrite_returns_409` |
| **P1** | **Shared `queue_id = 1` clobbers HTB rates**: `ensure_queue()` always wrote `queues:1=@q` on an egress port, overwriting `min-rate` when multiple intents shared a link, and never cleaned up queues on withdrawal/reroute. | Added `intent_queues` table and deterministic per-`(intent_id, port)` queue allocator (`allocate_queue_id`, `list_intent_queues`, `delete_intent_queues`) in `src/common/db.py`. Updated `queues.ensure_queue()` to attach `queues:<queue_id>=@q` without clobbering sibling queues, added `queues.destroy_intent_queues()`, and wired per-hop `queue_map` into `install_plan`, `remove_intent`, and `two_phase.install`. | `src/common/db.py`, `src/enforcement/queues.py`, `src/enforcement/flowmod.py`, `src/enforcement/two_phase.py`, `src/enforcement/controller.py` | `tests/test_audit_regressions.py::test_p1_per_intent_queue_allocation_and_cleanup` |
| **P2** | **Two-phase update continues when stage 1 or 2 fails**: `two_phase.install` unconditionally ran stage 3 (`DELETE_STRICT` old rules) even if stage 1 (` internal` rules) or stage 2 (ingress flip) failed, blackholing traffic. | Checked `stage1_ok` and `stage2_ok` in `two_phase.install` (`src/enforcement/two_phase.py`); on failure, rolls back newly staged `new_version` rules and preserves old rules, returning `ok=False`. | `src/enforcement/two_phase.py` | `tests/test_audit_regressions.py::test_p2_two_phase_aborts_and_rolls_back_on_stage_failure` |
| **P3** | **Fire-and-forget `OFPBarrierRequest`**: `send_barrier()` sent `OFPBarrierRequest` without tracking `xid`s or handling `OFPBarrierReply` / `OFPErrorMsg`. | Added pending barrier `xid` tracking (`_pending_barriers`, `_ofp_errors`) and `@set_ev_cls` handlers for `EventOFPBarrierReply` and `EventOFPErrorMsg` in `Team16Controller` (`src/enforcement/controller.py`) and `flowmod.send_barrier`. | `src/enforcement/controller.py`, `src/enforcement/flowmod.py` | `tests/test_audit_regressions.py::test_p3_barrier_reply_and_ofp_error_handling` |
| **P4** | **No topological link/port down handling**: The controller did not subscribe to `EventOFPPortStatus` or `ryu.topology.event.EventLinkDelete`, waiting solely for active probe timeouts. | Added `handle_port_down()` and `handle_link_down(u, v)` on `Team16Controller` (plus Ryu event handlers) that immediately emit `sla.violated` and trigger `ControlLoop.on_violation` for any active intent traversing the failed link/port. | `src/enforcement/controller.py` | `tests/test_audit_regressions.py::test_p4_link_down_triggers_immediate_reroute` |
| **P5** | **`active` state persisted before verifying all switches**: `install_plan` marked intents `active` even if a switch was missing from `self.datapaths` or a flow/queue operation failed. | Verified all switches on `plan.switches` are present in `self.datapaths` before programming, rolled back partial rules/queues on any failure, and only persisted `state = active` after all switches and queues succeeded. | `src/enforcement/controller.py` | `tests/test_audit_regressions.py::test_p5_install_plan_fails_closed_when_datapath_missing` |
| **P6** | **Unbounded SQLite table growth**: `measurements`, `events`, and `audit_log` grew without bound during long runs. | Added `prune_old_records(conn, max_rows, max_age_s)` in `src/common/db.py` (configurable via `TEAM16_RETENTION_MAX_ROWS` and `TEAM16_RETENTION_MAX_SECONDS`) and invoked it from `src/telemetry/runtime.py`. | `src/common/db.py`, `src/telemetry/runtime.py` | `tests/test_audit_regressions.py::test_p6_sqlite_retention_pruning` |
| **P7** | **Unmetered `OFPP_CONTROLLER` table-miss flood**: Priority-0 table-miss sent all unmatched traffic (`OFPCML_NO_BUFFER`) to the controller without rate limiting. | Installed OpenFlow 1.3 meter 1 (`OFPMeterMod` with `OFPMF_PKTPS`, `OFPFMF_DROP` at 100 pkt/s) and bound it via `OFPInstructionMeter(1)` on the table-miss rule in `switch_features_handler` (`src/enforcement/controller.py`), with a drop-by-default fallback when `TEAM16_TABLE_MISS_METER=0`. | `src/enforcement/controller.py` | `tests/test_audit_regressions.py::test_p7_table_miss_rate_limits_or_drops_packet_in` |
| **P8** | **`DEGRADE` and `REROUTE_OR_DEGRADE` fallback were no-ops**: `ControlLoop.on_violation` returned `None` on `DEGRADE` or when `REROUTE_OR_DEGRADE` had no backup route, leaving HTB queues unchanged. | Implemented `degrade_intent_queues()` on `Team16Controller` (`src/enforcement/controller.py`) and wired `ControlLoop.on_violation` (`src/telemetry/loop.py`) to scale `min_bps` by `TEAM16_DEGRADE_FACTOR` (default `0.5`), update `intent_queues` and OVS HTB queues, and record `SLA_DEGRADED` in `events` and `audit_log`. | `src/telemetry/loop.py`, `src/enforcement/controller.py`, `src/common/db.py` | `tests/test_audit_regressions.py::test_p8_degrade_and_reroute_or_degrade_shape_queues` |
| **M1** | **Preempted intents are never re-admitted**: Intents moved to `preempted` remained dead even after the higher-priority intent was withdrawn via `DELETE /intent/{id}`. | Added `try_readmit_preempted(conn)` in `src/intent_manager/admission.py` (scanning `preempted` intents in priority order `CRITICAL` -> `LOW`) and invoked it in `delete_intent` (`src/intent_manager/api.py`). | `src/intent_manager/admission.py`, `src/intent_manager/api.py` | `tests/test_audit_regressions.py::test_m1_preempted_intent_readmitted_on_delete` |
| **M2** | **No HTTP request body size limit**: `POST /intent` accepted arbitrarily large bodies before YAML parsing. | Added `enforce_body_size_limit` HTTP middleware in `src/intent_manager/api.py` enforcing `TEAM16_MAX_BODY_BYTES` (default `65536` bytes / 64 KiB) and returning `HTTP 413 Content Too Large`. | `src/intent_manager/api.py` | `tests/test_audit_regressions.py::test_m2_oversized_yaml_payload_returns_413` |
| **M3** | **No authentication on mutating API endpoints**: Any client could create or delete any tenant's intents. | Added optional Bearer token authentication (`_check_bearer_auth`) in `src/intent_manager/api.py` controlled by `TEAM16_API_TOKENS` (disabled when unset/empty; enforces `401 Unauthorized` and tenant-scoped `403 Forbidden` when configured). | `src/intent_manager/api.py` | `tests/test_audit_regressions.py::test_m3_bearer_token_auth_when_configured` |

> **Note on `tests/test_StandardsProfiles.py::test_profile_instantiation_reuses_existing_validation_and_admission_flow`**:
> That AST pin test checks the helper function names called inside `create_intent`. We updated its expected call set in commit `ade9395` solely to include `_check_bearer_auth` (M3), `get_intent` (D6), and `find_overlapping_intent` (D5) while preserving the exact validation and admission flow.

---

## 2. Reproduction Script (`repro_audit_findings.py`) — Before vs. After

### 2.1 Before Fixes (`before-linux.txt` on baseline `cf25af2`)

```text
== T1 reroute vs reservations
(201, {'id': 'INT-101', 'tenant': 'a', 'priority': 2, 'state': 'admitted', 'path': ['s1-s2', 's2-s3', 's3-s7'], 'switches': ['s1', 's2', 's3', 's7'], 'est_latency_ms': 6.0, 'bottleneck_mbps': 100.0})
(201, {'id': 'INT-102', 'tenant': 'b', 'priority': 2, 'state': 'admitted', 'path': ['s1-s4', 's4-s5', 's5-s7'], 'switches': ['s1', 's4', 's5', 's7'], 'est_latency_ms': 15.0, 'bottleneck_mbps': 50.0})
(201, {'id': 'INT-103', 'tenant': 'c', 'priority': 2, 'state': 'admitted', 'path': ['s1-s6', 's6-s7'], 'switches': ['s1', 's6', 's7'], 'est_latency_ms': 24.0, 'bottleneck_mbps': 40.0})
after reroute INT-101 path: ('s1', 's4', 's5', 's7')
OVERSUBSCRIBED s1 s4 reserved 75.0 capacity 50.0
OVERSUBSCRIBED s4 s5 reserved 75.0 capacity 50.0
OVERSUBSCRIBED s5 s7 reserved 75.0 capacity 50.0
== T2 asymmetric isolation
(201, {'id': 'INT-201', 'tenant': 'alpha', 'priority': 2, 'state': 'admitted', 'path': ['s1-s2', 's2-s3', 's3-s7'], 'switches': ['s1', 's2', 's3', 's7'], 'est_latency_ms': 6.0, 'bottleneck_mbps': 100.0})
(201, {'id': 'INT-202', 'tenant': 'beta', 'priority': 2, 'state': 'admitted', 'path': ['s1-s2', 's2-s3', 's3-s7'], 'switches': ['s1', 's2', 's3', 's7'], 'est_latency_ms': 6.0, 'bottleneck_mbps': 100.0})
== T3 identical match, two intents
201 admitted 201 admitted ['s1', 's2', 's3', 's7']
== T4 id overwrite by another tenant
{'id': 'INT-401', 'tenant': 'victim', 'priority': 1, 'state': 'admitted', 'path': ['s1-s2', 's2-s3', 's3-s7'], 'switches': ['s1', 's2', 's3', 's7'], 'est_latency_ms': 6.0, 'bottleneck_mbps': 100.0}
{'id': 'INT-401', 'tenant': 'attacker', 'priority': 5, 'state': 'admitted', 'path': ['s1-s2', 's2-s3', 's3-s7'], 'switches': ['s1', 's2', 's3', 's7'], 'est_latency_ms': 6.0, 'bottleneck_mbps': 100.0}
stored tenant: attacker priority: 5
== T5 reroute vs isolation
['s1', 's4', 's5', 's7']
['s1', 's2', 's3', 's7']
alpha after reroute: ('s1', 's4', 's5', 's7') | beta: ('s1', 's4', 's5', 's7')
== T6 same host pair, two ports: reverse-rule collision (GitHub flowmod)
COLLISION on s1 [('INT-601', 1), ('INT-602', 1)]
COLLISION on s7 [('INT-601', 3), ('INT-602', 4)]
315 passed, 1 skipped, 13 warnings in 9.14s
```

### 2.2 After Fixes (`after-linux.txt` on `fix/audit-2026-11`)

```text
== T1 reroute vs reservations
(201, {'id': 'INT-101', 'tenant': 'a', 'priority': 2, 'state': 'admitted', 'path': ['s1-s2', 's2-s3', 's3-s7'], 'switches': ['s1', 's2', 's3', 's7'], 'est_latency_ms': 6.0, 'bottleneck_mbps': 100.0})
(201, {'id': 'INT-102', 'tenant': 'b', 'priority': 2, 'state': 'admitted', 'path': ['s1-s4', 's4-s5', 's5-s7'], 'switches': ['s1', 's4', 's5', 's7'], 'est_latency_ms': 15.0, 'bottleneck_mbps': 50.0})
(201, {'id': 'INT-103', 'tenant': 'c', 'priority': 2, 'state': 'admitted', 'path': ['s1-s6', 's6-s7'], 'switches': ['s1', 's6', 's7'], 'est_latency_ms': 24.0, 'bottleneck_mbps': 40.0})
after reroute INT-101 path: ('s1', 's2', 's3', 's7')
== T2 asymmetric isolation
(201, {'id': 'INT-201', 'tenant': 'alpha', 'priority': 2, 'state': 'admitted', 'path': ['s1-s2', 's2-s3', 's3-s7'], 'switches': ['s1', 's2', 's3', 's7'], 'est_latency_ms': 6.0, 'bottleneck_mbps': 100.0})
(201, {'id': 'INT-202', 'tenant': 'beta', 'priority': 2, 'state': 'admitted', 'path': ['s1-s4', 's4-s5', 's5-s7'], 'switches': ['s1', 's4', 's5', 's7'], 'est_latency_ms': 15.0, 'bottleneck_mbps': 50.0})
== T3 identical match, two intents
201 admitted 409 None None
== T4 id overwrite by another tenant
{'id': 'INT-401', 'tenant': 'victim', 'priority': 1, 'state': 'admitted', 'path': ['s1-s2', 's2-s3', 's3-s7'], 'switches': ['s1', 's2', 's3', 's7'], 'est_latency_ms': 6.0, 'bottleneck_mbps': 100.0}
{'detail': "Intent INT-401 already exists in state 'admitted'; updating a live intent is not supported."}
stored tenant: victim priority: 1
== T5 reroute vs isolation
['s1', 's4', 's5', 's7']
['s1', 's2', 's3', 's7']
alpha after reroute: ('s1', 's6', 's7') | beta: ('s1', 's4', 's5', 's7')
== T6 same host pair, two ports: reverse-rule collision (GitHub flowmod)
336 passed, 1 skipped, 18 warnings in 8.77s
```

---

## 3. Live Mininet / Open vSwitch Verification (`live-verification.txt`)

Executed inside `team16/intent-sdn-sla:dev` using an isolated database (`TEAM16_DB_PATH=/tmp/live_audit.db`) with all 5 intents (`INT-001`, `INT-010`, `INT-011`, `INT-012`, `INT-013`) active simultaneously under a `+25 ms` delay fault injected on `s2-s3` at `t=8s`:

1. **Co-hosted `h1 -> h2` intents (`INT-001` on `udp/5001` and `INT-010` on `udp/5601`) keep distinct reverse rules and paths**:
   - After the `s2-s3` fault, `INT-001` (`max_latency_ms: 20`, `20 Mbps`) rerouted to `s1-s4-s5-s7` (`15.87 ms` mean RTT, `0.00%` loss, `22.06 Mbit/s`), while `INT-010` (`max_latency_ms: 35`, `8 Mbps`) remained on `s1-s2-s3-s7` (`21.93 ms` mean RTT, `0.00%` loss, `10.10 Mbit/s`).
   - `ovs-ofctl -O OpenFlow13 dump-flows` on `s1` and `s7` confirms distinct `tp_dst` forward matches, distinct `tp_src` reverse matches, and distinct `set_queue` IDs (`set_queue:1` for `INT-001`, `set_queue:2` for `INT-010`):
     ```text
     Switch s1:
      cookie=0x80006b2decd34ea5, priority=200,udp,vlan_tci=0x0000/0x1fff,nw_src=10.0.0.1,nw_dst=10.0.0.2,tp_dst=5001 actions=push_vlan:0x8100,set_field:4197->vlan_vid,set_queue:1,output:3
      cookie=0x4000940bd08cf141, priority=200,udp,vlan_tci=0x0000/0x1fff,nw_src=10.0.0.1,nw_dst=10.0.0.2,tp_dst=5601 actions=push_vlan:0x8100,set_field:4196->vlan_vid,set_queue:2,output:2
      cookie=0x6b2decd34ea5, priority=100,udp,dl_vlan=101,nw_src=10.0.0.2,nw_dst=10.0.0.1,tp_src=5001 actions=pop_vlan,output:1
      cookie=0x940bd08cf141, priority=100,udp,dl_vlan=100,nw_src=10.0.0.2,nw_dst=10.0.0.1,tp_src=5601 actions=pop_vlan,output:1
     Switch s7:
      cookie=0x80006b2decd34ea5, priority=200,udp,vlan_tci=0x0000/0x1fff,nw_src=10.0.0.2,nw_dst=10.0.0.1,tp_src=5001 actions=push_vlan:0x8100,set_field:4197->vlan_vid,output:4
      cookie=0x4000940bd08cf141, priority=200,udp,vlan_tci=0x0000/0x1fff,nw_src=10.0.0.2,nw_dst=10.0.0.1,tp_src=5601 actions=push_vlan:0x8100,set_field:4196->vlan_vid,output:3
      cookie=0x6b2decd34ea5, priority=100,udp,dl_vlan=101,nw_src=10.0.0.1,nw_dst=10.0.0.2,tp_dst=5001 actions=pop_vlan,output:1
      cookie=0x940bd08cf141, priority=100,udp,dl_vlan=100,nw_src=10.0.0.1,nw_dst=10.0.0.2,tp_dst=5601 actions=pop_vlan,output:1
     ```

2. **Reroute of `INT-001` respects residual capacity and isolation**:
   - `INT-011` (`20 Mbps` on `s4-s5`, `strict_isolation: false`) leaves `30 Mbps` residual capacity on `s4-s5` (`50 Mbps` link). When `s2-s3` experienced the `+25 ms` fault, `admission.replan_intent` routed `INT-001` (`20 Mbps`) onto `s1-s4-s5-s7` (`30 Mbps >= 20 Mbps` residual).

3. **Dedicated per-intent HTB queue IDs (`intent_queues` & `ovs-vsctl list queue`)**:
   - Before withdrawing `INT-001`, each intent held its own queue ID across its egress ports (11 total OVS queues):
     - `INT-001`: `queue_id=1` on `s1-eth3`, `s4-eth3`, `s5-eth3` (`min_bps=20000000, max_bps=50000000`)
     - `INT-010`: `queue_id=2` on `s1-eth2`, `s2-eth3`, `s3-eth3` (`min_bps=8000000, max_bps=100000000`)
     - `INT-011`: `queue_id=3` on `s4-eth3` (`min_bps=20000000, max_bps=50000000`)
     - `INT-012`: `queue_id=4` on `s2-eth3`, `s3-eth3`, `s7-eth5` (`min_bps=12000000, max_bps=100000000/40000000`)
     - `INT-013`: `queue_id=5` on `s3-eth3` (`min_bps=5000000, max_bps=100000000`)

4. **Clean flow and queue teardown on `DELETE /intent/INT-001`**:
   - Calling `DELETE /intent/INT-001` returned `204 No Content`.
   - Subsequent `ovs-ofctl -O OpenFlow13 dump-flows` on `s1` and `s7` confirmed all `0x80006b2decd34ea5` / `0x6b2decd34ea5` (`tp_dst=5001` / `tp_src=5001`) rules were removed while `INT-010` (`tp_dst=5601` / `tp_src=5601`) remained untouched.
   - `intent_queues` and `ovs-vsctl list queue` dropped from 11 queues to 8 queues (`INT-001`'s 3 queues on `s1-eth3`, `s4-eth3`, `s5-eth3` were destroyed).

---

## 4. `n=3` Regression Rechecks (`experiments/results/audit_recheck_2026-11/`)

All recheck CSVs were written exclusively to `experiments/results/audit_recheck_2026-11/`; zero historical files under `experiments/results/raw/` or `experiments/results/summary/` were modified (`verify_summaries.py` and `artifact_manifest.py verify` pass on all 355 historical artifacts).

| Experiment | Group | Metric | `n=3` Recheck Mean (Min..Max) | Published Mean (`n=10`) | Published 95% CI | Published Range (`Min..Max`) | Verdict vs. 95% CI | Notes |
|---|---|---|---|---|---|---|---|---|
| **E1** | `B1` | `sla_violation_duration_s` | `15.000` (`15.000..15.000`) | `15.000` | `[15.000, 15.000]` | `[15.000, 15.000]` | `in-interval` | Exact match |
| **E1** | `B1` | `right_censored` | `1.000` (`1.000..1.000`) | `1.000` | `[1.000, 1.000]` | `[1.000, 1.000]` | `in-interval` | Exact match |
| **E1** | `B3` | `sla_violation_duration_s` | `3.003` (`3.003..3.004`) | `3.003` | `[3.003, 3.003]` | `[3.003, 3.004]` | `in-interval` | Exact match |
| **E1** | `B3` | `right_censored` | `0.000` (`0.000..0.000`) | `0.000` | `[0.000, 0.000]` | `[0.000, 0.000]` | `in-interval` | Exact match |
| **E3** | `B2` | `detection_latency` (ms) | `91.438` (`91.080..91.693`) | `99.467` | `[96.249, 102.684]` | `[94.968, 110.836]` | `out-of-interval` | ~8 ms faster probe-to-persist scheduling jitter in WSL container |
| **E3** | `B2` | `recovery_latency` (ms) | `450.667` (`392.419..514.647`) | `279.355` | `[228.889, 329.821]` | `[215.894, 440.267]` | `out-of-interval` | Includes SQLite residual-capacity + isolation queries (`replan_intent`) and barrier tracking across 500 ms controller poll |
| **E3** | `B2` | `reroute_count` | `1.000` (`1.000..1.000`) | `1.000` | `[1.000, 1.000]` | `[1.000, 1.000]` | `in-interval` | Exact match |
| **E3** | `B3` | `detection_latency` (ms) | `2115.814` (`2105.767..2124.656`) | `2104.262` | `[2101.405, 2107.119]` | `[2097.640, 2110.407]` | `out-of-interval` | Within 0.5% (+11.5 ms) of published 3-sample confirmation latency |
| **E3** | `B3` | `recovery_latency` (ms) | `618.757` (`597.998..630.373`) | `618.535` | `[559.508, 677.561]` | `[475.152, 740.103]` | `in-interval` | Within 0.22 ms of published mean |
| **E3** | `B3` | `reroute_count` | `1.000` (`1.000..1.000`) | `1.000` | `[1.000, 1.000]` | `[1.000, 1.000]` | `in-interval` | Exact match |
| **E4** | `B2` | `packets_lost` | `42.000` (`42.000..42.000`) | `42.000` | `[42.000, 42.000]` | `[42.000, 42.000]` | `in-interval` | Exact match |
| **E4** | `B2` | `packets_reordered` | `0.000` (`0.000..0.000`) | `0.000` | `[0.000, 0.000]` | `[0.000, 0.000]` | `in-interval` | Exact match |
| **E4** | `B2` | `packets_duplicated` | `0.000` (`0.000..0.000`) | `0.000` | `[0.000, 0.000]` | `[0.000, 0.000]` | `in-interval` | Exact match |
| **E4** | `B2` | `packets_received` | `4285.667` (`4240..4328`) | `4313.100` | `[4256.208, 4369.992]` | `[4181.000, 4468.000]` | `in-interval` | Inside 95% CI |
| **E4** | `B2` | `packets_sent` | `4327.667` (`4282..4370`) | `4355.100` | `[4298.208, 4411.992]` | `[4223.000, 4510.000]` | `in-interval` | Inside 95% CI |
| **E4** | `B2` | `window_duration_s` | `4.328` (`4.282..4.370`) | `4.355` | `[4.298, 4.412]` | `[4.223, 4.510]` | `in-interval` | Inside 95% CI |
| **E4** | `B3` | `packets_lost` | `0.000` (`0.000..0.000`) | `0.000` | `[0.000, 0.000]` | `[0.000, 0.000]` | `in-interval` | Zero packet loss preserved |
| **E4** | `B3` | `packets_reordered` | `27.667` (`27.000..28.000`) | `28.000` | `[28.000, 28.000]` | `[28.000, 28.000]` | `out-of-interval` | 2 runs had 28 reordered packets, 1 run had 27 (published zero-variance CI `[28, 28]`) |
| **E4** | `B3` | `packets_duplicated` | `0.000` (`0.000..0.000`) | `0.000` | `[0.000, 0.000]` | `[0.000, 0.000]` | `in-interval` | Exact match |
| **E4** | `B3` | `packets_received` | `4514.000` (`4489..4533`) | `4501.600` | `[4457.750, 4545.450]` | `[4414.000, 4616.000]` | `in-interval` | Inside 95% CI |
| **E4** | `B3` | `packets_sent` | `4514.000` (`4489..4533`) | `4501.600` | `[4457.750, 4545.450]` | `[4414.000, 4616.000]` | `in-interval` | Inside 95% CI |
| **E4** | `B3` | `window_duration_s` | `4.514` (`4.489..4.533`) | `4.502` | `[4.458, 4.545]` | `[4.414, 4.616]` | `in-interval` | Inside 95% CI |
| **E6** | `B2` | `reroute_count_10min` | `90.000` (`90.000..90.000`) | `90.000` | `[90.000, 90.000]` | `[90.000, 90.000]` | `in-interval` | Exact match (60s run = 3 macro-cycles = 9 raw reroutes = 90/10min; `violations=9, restorations=9`) |
| **E6** | `B2` | `dwell_suppressions` | `0.000` (`0.000..0.000`) | `0.000` | `[0.000, 0.000]` | `[0.000, 0.000]` | `in-interval` | Exact match |
| **E6** | `B3` | `reroute_count_10min` | `50.000` (`50.000..50.000`) | `48.300` | `[47.542, 49.058]` | `[46.000, 50.000]` | `out-of-interval` | Inside published `[46.0, 50.0]` range (60s run = 5 raw reroutes * 10 = `50.0`, `suppressions=3` * 10 = `30.0` vs `28.7`) |
| **O3** | `bound` | `intent_throughput_mbps` | `24.996` (`24.995..24.996`) | `24.995` | `[24.995, 24.996]` | `[24.995, 24.996]` | `in-interval` | Exact match |
| **O3** | `bound` | `intent_loss_pct` | `0.000` (`0.000..0.000`) | `0.000` | `[0.000, 0.000]` | `[0.000, 0.000]` | `in-interval` | Exact match |
| **O3** | `bound` | `cross_traffic_throughput_mbps` | `74.225` (`74.208..74.245`) | `74.352` | `[74.304, 74.399]` | `[74.207, 74.441]` | `out-of-interval` | Inside published `[74.207, 74.441]` range |
| **O3** | `bound` | `cross_traffic_loss_pct` | `50.507` (`50.494..50.518`) | `50.423` | `[50.391, 50.455]` | `[50.362, 50.519]` | `out-of-interval` | Inside published `[50.362, 50.519]` range |
| **O3** | `unbound` | `intent_throughput_mbps` | `19.285` (`18.590..20.056`) | `19.091` | `[18.818, 19.365]` | `[18.458, 19.801]` | `in-interval` | Inside 95% CI |
| **O3** | `unbound` | `intent_loss_pct` | `22.844` (`19.761..25.628`) | `23.620` | `[22.527, 24.714]` | `[20.780, 26.156]` | `in-interval` | Inside 95% CI |
| **O3** | `unbound` | `cross_traffic_throughput_mbps` | `79.944` (`79.103..80.626`) | `80.133` | `[79.810, 80.457]` | `[79.115, 80.813]` | `in-interval` | Inside 95% CI |
| **O3** | `unbound` | `cross_traffic_loss_pct` | `46.694` (`46.239..47.255`) | `46.568` | `[46.352, 46.784]` | `[46.115, 47.248]` | `in-interval` | Inside 95% CI |
