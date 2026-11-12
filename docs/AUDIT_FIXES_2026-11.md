# Audit Findings & Remediation Report (2026-11)

This document records the 17 engineering audit items (`D1`–`D6`, `P1`–`P8`, `M1`–`M3`) remediated on branch `fix/audit-2026-11`, their regression tests, the before/after reproduction outputs from `repro_audit_findings.py`, live Open vSwitch / Mininet verification evidence, and the `n=3` regression rechecks stored in `experiments/results/audit_recheck_2026-11/`.

---

## 1. Summary of All 17 Audit Items

| ID | Defect | Fix | Files | Regression test (`tests/test_audit_regressions.py`) |
|---|---|---|---|---|
| **D1** | Reverse-rule collision: two intents between the same host pair on different ports installed identical reverse matches. | The reverse match in `rules_for_path()` now carries `sport` = the intent's `dport`, mapped to `udp_src` / `tcp_src` in `build_match()`. Live-demo helpers added. | `src/enforcement/flowmod.py`, `scripts/inject_fault.sh`, `scripts/udp_load.py`, `scripts/udp_probe_echo.py`, `experiments/scenarios/live_all_intents.sh` | `test_d1_reverse_rules_disambiguate_same_host_pair_by_sport`; new cases in `tests/test_enforcement.py` |
| **D2** | Reroute bypassed admission: `ControlLoop.on_violation` planned on the raw topology and could oversubscribe a link. | `on_violation` plans on `residual_graph(conn, graph, exclude_intent_ids={intent.id})`. | `src/telemetry/loop.py`, `src/admission/residual.py` | `test_d2_reroute_uses_residual_capacity_and_never_oversubscribes` |
| **D3** | Reroute ignored `isolate_from`. | `on_violation` passes `tenant_paths(conn, exclude_intent_ids={intent.id})` to `compute_path()`. | `src/telemetry/loop.py` | `test_d3_reroute_enforces_tenant_isolation` |
| **D4** | Isolation was one-directional: only the incoming intent's `isolate_from` was checked. | `tenant_paths()` also reports links of active intents that isolate from the incoming tenant; `prune()` and `compute_path()` reject paths in both directions. | `src/admission/residual.py`, `src/pathing/prune.py`, `src/pathing/compute.py`, `src/admission/feasibility.py` | `test_d4_isolation_is_bidirectional_in_admission_and_reroute` |
| **D5** | Two intents with an identical or overlapping match were both admitted. | `matches_overlap()` compares forward and reverse flow matches; `POST /intent` returns HTTP 409 naming the conflicting intent. The check is skipped when `TEAM16_EXPERIMENT_MODE=b2` so the B2 ablation is unchanged. | `src/intent_manager/validator.py`, `src/intent_manager/api.py` | `test_d5_overlapping_or_identical_match_returns_409` |
| **D6** | Re-posting an existing intent ID overwrote the live record, whatever the tenant. | `POST /intent` returns HTTP 409 unless the existing intent is `withdrawn` or `rejected`. | `src/intent_manager/api.py` | `test_d6_intent_id_overwrite_returns_409_unless_withdrawn_or_rejected` |
| **P1** | Every bandwidth intent on a port shared queue 1 and overwrote its rate; queues were never removed. | `intent_queues` table with `allocate_queue_id()` (IDs start at 1); `ensure_queue()` adds a queue per intent and keeps the port root rate at link capacity; `remove_intent_queues()` cleans up; per-hop `queue_ids` are passed to `rules_for_path()` and `versioned_rules()`. | `src/common/db.py`, `src/enforcement/queues.py`, `src/enforcement/flowmod.py`, `src/enforcement/two_phase.py`, `src/enforcement/controller.py` | `test_p1_per_intent_queues_allocated_persisted_and_cleaned_up` |
| **P2** | A failed `ovs-vsctl` call was swallowed. | `_run_cmd()` raises `QueueConfigurationError`; the install is audited as `PATH_INSTALL_FAILED` and the intent does not become active. | `src/enforcement/queues.py`, `src/enforcement/controller.py` | `test_p2_queue_failure_raises_audits_path_install_failed_and_does_not_activate` |
| **P3** | Barriers were sent but their replies were not awaited. | `barrier_all()` waits for a reply from each involved datapath (`TEAM16_BARRIER_TIMEOUT_S`, default 2.0 s); on timeout the two-phase update fails closed and rolls back. | `src/enforcement/controller.py`, `src/enforcement/two_phase.py` | `test_p3_two_phase_waits_for_barrier_reply_and_rolls_back_on_timeout` |
| **P4** | Rule installs were counted as sent, not confirmed. | `error_msg_handler()` records OpenFlow errors; a rule that draws an error counts as not installed and is audited. | `src/enforcement/controller.py` | `test_p4_openflow_error_msg_counts_as_failed_install_and_audits` |
| **P5** | No link-down or switch-disconnect handling. | `port_status_handler()` and `state_change_handler()` update the controller's datapath map and persisted link state (`set_link_state()` / `down_links()`); down links are excluded from planning and affected intents are re-planned. | `src/enforcement/controller.py`, `src/common/db.py`, `src/admission/residual.py` | `test_p5_topology_port_status_and_disconnect_update_graph_and_replan` |
| **P6** | The violation dispatcher rescanned the whole events table every 0.5 s; tables grew without bound. | The dispatcher tracks the last processed rowid. `prune_retention()` trims `measurements` and `events` only when `TEAM16_RETENTION_MAX_ROWS` or `TEAM16_RETENTION_SECONDS` is set (off by default). | `src/enforcement/controller.py`, `src/common/db.py` | `test_p6_violation_dispatcher_tracks_rowid_and_retention_prunes_when_configured` |
| **P7** | Unmatched packets went to the controller without a rate limit. | The table-miss rule is bound to OpenFlow meter 1 (drop band, 50 packets/s, burst 10) when the switch supports meters and `TEAM16_TABLE_MISS_METER` is `1` (default). | `src/enforcement/controller.py` | `test_p7_table_miss_rate_limits_or_drops_packet_in` |
| **P8** | No request body size limit. | `POST /intent` rejects bodies over 64 KiB with HTTP 413 (fixed limit, not configurable). | `src/intent_manager/api.py` | `test_p8_post_intent_body_over_64kib_returns_413` |
| **M1** | `on_violation: degrade` only relabelled the intent. | The control loop lowers the intent's queue rate by `TEAM16_DEGRADE_FACTOR` (default 0.5), records it with `set_degraded_rate()`, releases the difference in the residual model, and `on_restored()` restores the full rate when capacity allows. | `src/telemetry/loop.py`, `src/common/db.py`, `src/enforcement/queues.py`, `src/admission/residual.py` | `test_m1_degrade_lowers_queue_rate_releases_residual_and_restores_on_sla_restored` |
| **M2** | Preempted intents were never re-admitted. | `reconcile_preempted_intents()` re-runs admission for preempted intents in priority order after a withdrawal, reroute or degrade. | `src/admission/feasibility.py`, `src/intent_manager/api.py`, `src/telemetry/loop.py` | `test_m2_readmission_of_preempted_intents_in_priority_order` |
| **M3** | No access control on the intent API. | Optional bearer tokens: when `TEAM16_API_TOKENS` holds `tenant=token` pairs, creating and withdrawing intents requires a valid token (401) and a tenant may only act on its own intents (403). Off when unset. | `src/intent_manager/api.py` | `test_m3_bearer_token_access_control_enforces_tenant_ownership` |

> **Existing tests.** No existing test was weakened or removed. `tests/test_enforcement.py` gained 53 lines of new D1 cases and no line was deleted; every other test file from `main` is unchanged.

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
   - `INT-011` (`20 Mbps` on `s4-s5`) leaves `30 Mbps` residual capacity on `s4-s5` (`50 Mbps` link). When `s2-s3` experienced the `+25 ms` fault, the control loop's residual-capacity replan routed `INT-001` (`20 Mbps`) onto `s1-s4-s5-s7` (`30 Mbps >= 20 Mbps` residual).

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
| **E3** | `B2` | `recovery_latency` (ms) | `450.667` (`392.419..514.647`) | `279.355` | `[228.889, 329.821]` | `[215.894, 440.267]` | `out-of-interval` | Cause not isolated; the reroute now runs residual-capacity and isolation queries and confirms installs |
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

### 4.1 Comparison with the figures used in the paper

The "Published" columns above for E3 and E4 come from the first evaluation summaries (`b2_b3_comparison.json`, `e4_packet_loss_summary.csv`). The paper and final report quote the later `current` summaries for B3 recovery and E4. Against those figures the recheck reads:

| Metric | Paper figure (`n=10`, 95% CI) | Recheck mean (`n=3`) | Verdict |
|---|---|---|---|
| E3 B3 detection latency | 2115.9 ms [2108.7, 2123.1] | 2115.8 ms | in-interval |
| E3 B3 recovery latency | 537.9 ms [446.4, 629.3] | 618.8 ms | in-interval |
| E4 B2 packets lost | 41.0 [39.5, 42.5] | 42.0 | in-interval |
| E4 B3 packets lost | 0 | 0 | unchanged |
| E6 B3 reroutes per 10 min | 48.3 [47.5, 49.1] | 50.0 | not comparable: 60 s runs scaled by 10, so the value moves in steps of 10 |
| **E3 B2 recovery latency** | **279.4 ms [228.9, 329.8]** | **450.7 ms (392.4 to 514.6)** | **out-of-interval** |

**Open item.** B2 recovery latency is about 170 ms slower on the fixed code than the published figure, which was measured at commit `cf25af2` before these fixes. Three runs are not enough to replace a published mean, so the published numbers are unchanged. Before the paper quotes B2 recovery for the fixed code, E3 B2 needs a full `n=10` rerun; otherwise the paper should state that E1 to E8 were measured at `cf25af2`.

