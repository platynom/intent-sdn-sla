# Team 16 code walkthrough

This guide explains how a structured service request becomes forwarding rules and how measurements can trigger a new path. The application is deterministic Python software. It does not use an LLM to interpret requests. File and line references refer to the final integration implementation; search for the named function if subsequent edits move a line.

## M1 Intent management

Purpose: accept a machine-readable request and reject malformed or unsupported requests before networking work begins. `src/intent_manager/api.py:67` declares `POST /intent`; `validator.py:173` implements `validate`, and `validator.py:204` implements `validate_yaml`. `schema.json` freezes the accepted fields. `_semantic_checks` at `validator.py:80` checks relationships beyond field types. `IntentRecord.from_document` converts the validated dictionary into the shared model.

Input is YAML text or a JSON document containing `intent`. Output is an admitted or rejected record, a JSON response, SQLite rows, and lifecycle events. Schema errors return HTTP 422. A well-formed request that cannot be admitted can still return HTTP 201 with state `rejected`; HTTP success alone does not prove an installed service.

Design question: why a frozen grammar? Explicit fields allow repeatable validation, testing, and measurement. Natural language interpretation would introduce ambiguity beyond this project's evaluated scope.

Viva explanation:
We accept the required service as structured data.
We validate its syntax and meaning before attempting admission.
The API stores the request and returns its decision and computed path.

## M2 Admission and conflict handling

Purpose: decide whether the network model has enough remaining resources. `src/admission/residual.py:15` implements `residual_graph`; `residual.py:54` gathers tenant paths. `src/admission/feasibility.py:16` implements `assess`. `src/intent_manager/api.py:35` calls admission for each request. It consults persisted active intents and their paths, then records admission and preemption decisions.

Input is an intent, topology graph, and reservations. Output is a verdict, explanation, optional candidate path, and optional preemption victim. Priority uses the frozen scale where a smaller number means higher priority. Preemption requires the controller to remove the victim's forwarding rules, not merely mark a database row.

Design question: why use residual capacity? Physical link capacity alone ignores existing promises. Residual capacity subtracts reserved bandwidth before evaluating a new promise.

Viva explanation:
We account for services already using each link.
A new request must fit the remaining modelled capacity.
When policy permits it, a higher-priority service can preempt a lower-priority one.

## M3 Path computation

Purpose: select a feasible route with a deterministic explanation. `src/pathing/compute.py:30` implements `compute_path`. `_resolve_ip_to_switch` at line 20 maps a host address to its access switch. `yen_ksp.py:16` implements `k_shortest_paths`; `prune.py:17` checks constraints, and `prune.py:107` implements `select_best`.

Input is the intent and graph, optionally including tenant routes for isolation. Output is a `PathPlan` or rejection reasons. The implementation considers up to three candidates, prunes infeasible candidates, then selects deterministically. Path bandwidth is the minimum edge bandwidth; path delay is the sum of edge delays. These are model estimates, not measured application performance.

Design question: why several routes? Alternatives allow a feasible choice after a link is excluded. The small topology is an experiment for recovery and tradeoffs, not a scalability benchmark.

Viva explanation:
We generate candidate routes and check each against the requested guarantees.
We choose a surviving route consistently for the same inputs.
If none survives, we return the reason rather than installing an unsuitable route.

## M4 Enforcement

Purpose: translate a plan into operations on Open vSwitch. `src/enforcement/controller.py:54` defines `Team16Controller`. `_sync_intents_from_db` at line 98 polls persisted plans. `install_plan` at line 355 installs a plan; `remove_intent` at line 439 removes its rules. In `src/enforcement/flowmod.py`, line 38 defines `cookie_for_intent`, line 60 defines `build_match`, line 99 defines `rules_for_path`, and line 196 defines `install`. `queues.py:23` implements `ensure_queue`. `two_phase.py:105` implements strict installation.

Input is a plan and intent. Output is OpenFlow 1.3 flow modifications, OVS HTB configuration, barriers, and installation events. Cookies identify an intent's rules. IPv4 matches include Ethernet type 0x0800. Forward inter-switch actions bind reserved traffic to queue 1 with SET_QUEUE. Queue rates use bits per second and their ceilings come from topology capacities.

Queue 1 is shared when multiple intents leave through the same port. The protected-flow bandwidth experiment therefore proves that tested flow's binding under cross-traffic, not independent bandwidth isolation for every concurrent intent.

Strict updates stage a different VLAN version, wait for barriers, flip ingress classification, wait for old packets to drain, and remove old rules. Relaxed updates replace rules directly. `controller.py:256` installs a priority-zero table-miss rule that sends unmatched traffic to the controller.

Design question: why strict and relaxed modes? Strict updates preserve packets in flight but require temporary rules, barriers, and a drain interval. Relaxed updates cost less but can lose packets during replacement. The design follows Reitblatt et al.; selective use follows CCG.

Viva explanation:
The controller programs software switches with rules for the selected path.
Queues bind bandwidth promises to the forwarding actions.
Strict updates keep old and new forwarding versions during the transition.

## M5 Telemetry and control loop

Purpose: observe the running service and respond to confirmed violations. `src/telemetry/runtime.py:51` starts the live collector process. `flow_bytes` reads OVS counters; consecutive byte snapshots produce throughput. The live runtime sends UDP echo probes through host namespaces, so measured delay is round trip. `src/telemetry/probes.py:36` derives jitter/loss observations in `ActiveProbeSource.observation`. `src/telemetry/detector.py:62` implements `ViolationDetector.observe`. `runtime.py:17` persists emitted transitions; `reload_persisted_replan_state` at line 23 refreshes dwell state written by the controller.

`controller.py:174` dispatches persisted violations into its process-local bus. `src/telemetry/loop.py:47` implements `ControlLoop.on_violation`: load the intent, check policy/dwell, exclude current path edges, compute an alternative, install it, save the new path, and write a causal audit entry. SQLite crosses the process boundary; a Python event bus alone cannot do that.

That replan uses its topology graph directly rather than calling M2 residual-capacity admission again. The initial admission and the recovery calculation therefore have different resource-accounting scopes. The current single-protected-flow recovery experiments do not prove contention-safe multi-intent recovery.

Input is probe observations and counter snapshots. Output is stored measurements, detector state, durable events, and potentially a new path. EWMA smooths values; hysteresis separates breach and recovery boundaries; consecutive confirmation and dwell reduce flapping. Low observed traffic alone does not establish that available bandwidth is insufficient: an offered-load test is needed.

The same latency field currently constrains a one-way planning estimate and a round-trip live probe without conversion. Explain these as different quantities; do not claim that this prototype verifies a common one-way latency guarantee.

Design question: why slower detection in B3? Confirmation deliberately waits for sustained evidence instead of reacting to a single sample. That trades reaction time for fewer route changes.

Viva explanation:
We measure the live virtual network and store each sample.
The detector confirms persistent SLA breaches and records them durably.
The controller consumes those events and can install a feasible alternative.

## M6 Dashboard and audit

Purpose: explain current state and past actions. `src/dashboard/app.py:27` builds an intent snapshot, line 104 serves `/api/dashboard`, line 130 serves one intent, and line 144 serves the web page. `src/common/audit.py:86` records the measurement, threshold, decision, and action in a causal chain.

Input is the existing SQLite schema. Output is read-only JSON and an operator view. `scripts/seed_demo_intents.py` posts the shipped application examples and adds illustrative samples only when none already exist. Simulation is identified by an explicit audit payload and dashboard label. When live rows follow the simulation window, the chart selects live rows. These seeded values are demonstration data and are excluded from evaluation CSV aggregation.

Design question: does a computed route mean installed? No. Admission computes a route; the Ryu controller must activate it on a live datapath. The dashboard distinguishes these states.

The installed badge reflects the last persisted controller state; the read-only dashboard does not independently probe switch liveness. A retained badge after scenario cleanup is not a fresh datapath check. Use the scenario's flow dump and packet delivery checks to establish current installation.

Viva explanation:
The dashboard reads stored intents, measurements, and audit events.
It explains the selected path and why an automatic action happened.
Illustrative demo samples are labelled and must never be cited as experimental results.

## Topology

`topology/topology_spec.py` is the graph authority: host records, links, capacities, delays, and inferred-link flags. `build_graph` at line 131 serves path planning; `link_capacity_mbps` at line 123 serves queues. `topology/team16_topo.py:46` builds `Team16Topo` with Mininet hosts, OVS switches, and TCLink links. One remote Ryu controller programs the switches. These are live Linux network namespaces and software datapaths carrying packets within an emulated topology.

Design question: why inferred links? They complete the experimental alternatives and must remain disclosed as modelling choices. They are not claimed to represent measured physical infrastructure.

Viva explanation:
The topology specification supplies the planner and the emulator.
Three unequal alternatives make route changes observable.
The experiment runs real packets through virtual hosts and software switches.

## Trace of the baseline intent

1. Submit `intents/s1_urllc_baseline.yaml` to `POST /intent`, handled by `create_intent` at `src/intent_manager/api.py:68`. The endpoint parses YAML, calls `validate`, and constructs `IntentRecord.from_document`.
2. `_admission_for_request` calls `assess` in the ordinary full-system mode. `assess` builds `residual_graph`, gathers `tenant_paths`, and calls `compute_path`. Path computation uses `_resolve_ip_to_switch` -> `k_shortest_paths` -> `prune` -> `select_best`. The B2 admission ablation deliberately takes a different request path.
3. M1 calls `db.save_intent` and `db.save_path`; a strict plan is assigned its version with `two_phase.with_version`. The response contains the computed switch path.
4. Ryu's `_enforcement_loop` calls `_sync_intents_from_db` -> `install_plan`. This configures `ensure_queue`, then calls strict `two_phase.install` or relaxed `rules_for_path` -> flow installation. Ryu marks the intent active and publishes installation evidence.
5. `runtime.main` probes the hosts, reads `flow_bytes`, calculates counter deltas, calls `db.save_measurement`, refreshes persisted dwell state, and calls `ViolationDetector.observe` -> `persist_confirmed_event` -> `db.save_event`.
6. `_dispatch_persisted_violations` publishes the durable transition to `ControlLoop.on_violation`, which computes and installs an alternative, saves its path and last-replan time, and records the explanation through `AuditLog.chain`.
7. M6 `dashboard_data` and `intent_detail` read the updated path, measurements, and causal audit history. A bandwidth queue is a configuration result; sustained bandwidth delivery still requires offered traffic and receiver measurements.

## Experiments and CSV production

The shell scripts start the required processes, inject a controlled condition, query the datapath/database, and write long-form CSV rows with run id, timestamp, metric, value, and unit. Aggregation reads those files and computes sample SD and Student-t intervals. `experiments/verify_summaries.py` independently checks registered outputs against raw values. Preserve historical raw files; use new prefixes for corrected or regression runs.

| Script | Injection and measurement |
|---|---|
| `b0_baseline.sh` | Static forwarding and iperf traffic; receiver throughput baseline. |
| `b1_open_loop.sh` | Submit an intent without a closed loop; API response timing pilot. |
| `b2_closed_loop.sh` | Calls the S1 driver with naive detector and relaxed replacement; writes detection/recovery latency. |
| `b2_matched_detector.sh` | Uses B3 detector settings with relaxed replacement to isolate update cost. |
| `b2_no_conflict.sh` | Admission ablation using conflicting fixture intents. |
| `b3_closed_loop.sh` | S1 driver with strict updates and the default detector; detection/recovery CSV. |
| `e1_violation_duration.sh` | A bounded delay fault; measures duration of SLA violation, marking open-loop censoring. |
| `e4_packet_loss.sh` | Sequence-numbered UDP stream across a delay fault and reroute; counts lost, duplicated, and reordered packets within the observation window. |
| `o3_queue_binding.sh` | Protected flow plus competing offered load; compares receiver throughput and loss with and without SET_QUEUE. |
| `e5_flow_table_entries.sh` | Concurrent updates under relaxed, selective, and strict consistency; peak rule count and packet loss. |
| `e6_oscillation.sh` | Alternating delay phases, including brief spikes and recovery; counts path revisions and durable detector events over the configured duration. |
| `e7_admission_scaling.sh` | Increases active-intent count; times POST decision latency. |
| `e8_control_overhead.sh` | Open-loop versus closed-loop window; estimates control traffic from captured TCP PSH segments and samples inclusive process CPU ticks for the control stack. |
| `flow_table_pilot.sh` | Attempts increasing rule populations; tests whether a software flow-table limit affects installation. This does not establish ASIC TCAM behavior. |
| `s1_single_intent.sh` | Functional intent installation, queue, forwarding, measurements; optional ST-7 reroute checks. |
| `s9_preemption.sh` | Lower-priority reservation followed by a higher-priority conflict; verifies victim removal and critical intent activation. |
| `s10_two_phase.sh` | Changes a strict path version; checks ingress/version replacement, old-path cleanup, and UDP delivery. |

`analyze_closed_loop.py` handles closed-loop latency families. `summarize_metrics.py` handles the other metric families and keeps current-code reruns distinct. `plot_results.py` creates figures. A summary, chart, or dashboard is evidence only for the source and run that actually produced it.

`experiments/e6_accounting.py:4` provides `counts_for_run`, the complete SQL event count used by the corrected E6 recorder. `watch_e6_accounting.py` is a read-only boundary observer: it saves full event/path records beside each new CSV and checks that they reconcile. It also compares a bounded latest-200-event history page with the complete count. UI pagination is appropriate for displaying recent history, but is not an experiment's total event count. See `docs/E6_ACCOUNTING.md` for the distinction between this demonstrated mechanism and the uncertain historical invocation.
