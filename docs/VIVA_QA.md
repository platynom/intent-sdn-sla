# Team 16 viva preparation

Suggested preparation groups below identify module responsibilities, not an unverified claim about who wrote the code. Team members should agree their own speaking allocation. Exact measured values should be read from the final report's generated result tables and the registered CSV summaries.

## M1 and M2 preparation

1. **What problem does the project address?** Translating explicit service requirements into switch configuration, checking feasibility, measuring service behavior, and reacting when a confirmed breach occurs.
2. **What is an intent?** A structured description of endpoints, traffic match, service constraints, priority, consistency, and violation policy. It states the required outcome rather than individual switch commands.
3. **Is an LLM used?** No. YAML parsing, JSON Schema, semantic checks, graph algorithms, and explicit policies implement the runtime.
4. **How is an invalid intent rejected?** M1 validates the parsed document against `schema.json` and semantic checks, returning HTTP 422 with field paths and reasons.
5. **What is the difference between invalid and infeasible?** Invalid means the request violates the grammar or semantic rules. Infeasible means a valid request has no admissible route under the current model and reservations.
6. **Does HTTP 201 prove the service is active?** No. Inspect the response state and then controller activation evidence. A syntactically valid but infeasible request can be stored as rejected.
7. **How does admission account for bandwidth?** M2 subtracts existing reservations from each affected link before evaluating the new intent.
8. **How does preemption work?** A higher-priority intent may displace an eligible lower-priority reservation; state, audit events, and rule removal must agree.
9. **Why SQLite?** It provides durable shared state across API, telemetry, controller, and dashboard processes without an additional database server. WAL and a busy timeout support concurrent access.
10. **Is telemedicine bandwidth a universal standard here?** No. The shipped application intents are experiment configurations. A real deployment requires an application-specific SLA and workload definition.
11. **What is frozen?** The supported intent fields and their constraint/action vocabulary are deliberately fixed and tested. Expanding the grammar would change the evaluation contract.

## M3 and M4 preparation

12. **Why three link-disjoint routes?** They provide alternatives with different modelled capacities and delays, so selection and recovery can be observed. The configured network has seven switches, eight hosts, eight inter-switch links, eight host-access links, and one Ryu SDN controller. These configuration counts do not establish large-network scalability.
13. **How is a route's bandwidth calculated?** It is the minimum capacity or residual capacity along the route, since the narrowest link constrains the flow.
14. **How is route latency calculated?** Planning sums configured edge delays. The live UDP echo probe measures round-trip delay. Both currently use the same latency budget without conversion; disclose that limitation instead of claiming a verified common one-way SLA.
15. **Why Yen's algorithm?** It supplies several loop-free candidate routes for constraint pruning and deterministic selection using an established method.
16. **Why might a feasible route be missed?** Candidate enumeration is bounded; the prototype does not exhaustively search every possible route in an arbitrary graph.
17. **What is SDN?** A control application programs forwarding devices through a controller rather than configuring each switch manually.
18. **What are Mininet, OVS, and Ryu?** Mininet creates virtual hosts and links; OVS forwards packets as a software switch; Ryu sends OpenFlow control messages to those switches.
19. **What is an intent cookie?** A deterministic identifier attached to an intent's OpenFlow rules so they can be found and removed. It is unrelated to browser cookies.
20. **Why include Ethernet type in an IPv4 match?** OpenFlow requires the appropriate protocol prerequisites; an IP protocol field without an IPv4 Ethernet match can fail to match as intended.
21. **What does HTB mean and why is SET_QUEUE necessary?** Hierarchical Token Bucket controls egress scheduling. Creating an OVS queue alone is insufficient; matching forwarding actions must select that queue.
22. **Why derive queue ceilings from topology?** A queue's root rate must reflect its actual egress link instead of assuming every link has the northern route's capacity.
23. **What does a two-phase update do?** Stage a new version, synchronize rule processing, flip ingress to that version, drain old packets, and remove old-version rules.
24. **Did we invent consistent updates?** No. Versioned consistent updates follow Reitblatt et al.; selective per-intent consistency follows CCG. The contribution is implementation and evaluation of the integrated artifact.
25. **Why can B3 reorder packets while losing none?** Packets already on the slower old route can arrive after newer packets sent on the faster replacement route.
26. **Why use strict mode selectively?** It trades additional rules and transition time for packet preservation. Services that tolerate transient loss can use relaxed updates.

## M5 and M6 preparation

27. **How is live throughput obtained?** Read matching flow byte counters twice and divide the byte difference by elapsed time, converting bytes to bits and then to Mbps.
28. **Does low measured traffic prove the network lacks bandwidth?** No. It can mean the application offered little traffic. Capacity assurance requires a workload that offers enough traffic and receiver-side measurements.
29. **Why is B3 detection slower?** Smoothing and consecutive-sample confirmation wait for sustained evidence. The naive baseline reacts sooner but changes paths more frequently.
30. **What is a stable breach?** A violation that survives the detector's smoothing, threshold band, and confirmation requirements. Dwell can suppress a route change after confirmation.
31. **How does the event cross processes?** Telemetry persists it in SQLite; Ryu polls unresolved events and publishes them on its local bus. An in-memory bus cannot directly communicate with another process.
32. **What explains the control-stack CPU cost?** The closed loop runs telemetry and probes in addition to Ryu and the API. E8v2 measures those process trees; the earlier Ryu-only field omitted much of that work.
33. **What is simulated dashboard telemetry?** Clearly labelled illustrative samples seeded for a visual demonstration. They are not Mininet measurements and must not enter experimental results.
34. **What does the audit trail explain?** Which measurement crossed which threshold, what decision followed, and which network action was taken.

## Evaluation and research preparation

35. **Is this a live network or simulation?** Packets travel through running Linux namespaces, traffic-control links, and OVS datapaths in Mininet. It is live emulation on software, with no claim of physical switch or 5G radio validation.
36. **What are B0 through B3?** B0 is static forwarding, B1 installs intents without feedback, B2 is a naive closed loop, and B3 adds the full policy and consistency mechanisms. The matched-detector ablation helps isolate update cost.
37. **Why Student-t intervals and exact tests?** Intervals express uncertainty in a mean estimated from independent runs. A Welch comparison handles unequal nonzero variances; exact permutation tests avoid reporting misleading infinite t statistics when a group has zero sample variance.
38. **What does the evaluation show B3 buys and costs?** It preserves packets during the tested strict transitions and reduces oscillation. Its costs include slower confirmation/recovery, temporary flow rules, reordering, and higher measured control-stack CPU. Cite the generated tables rather than memorized rounded numbers.
39. **What limits generalization?** The fixed topology, single-machine software datapath, inferred links, bounded candidate search, calibrated drain time, workload definitions, and historical code revisions. Software flow limits do not establish physical TCAM scarcity.
40. **How do the six papers relate?** Leivadeas and Falkner provide the IBN survey context; Martini et al. and Park et al. frame relevant service/intent orchestration approaches as described in the supplied literature review; Foerster et al. review consistent-update foundations; Reitblatt et al. supply the versioned update method; Zhou et al. supply selective consistency. Read the final report's condensed review and DOI references before assigning more specific claims to those papers.

## Standards-derived profiles

41. **Why use 5QI rather than call these slice types?** A 5QI identifies QoS characteristics for a QoS flow. URLLC/eMBB/mMTC usage categories and end-to-end network slices are different concepts. Our application-to-5QI mapping is explicit project policy, not implementation of a 5G slice.
42. **Is PER the same as measured packet loss?** No. TS 23.501 PER concerns non-congestion link-layer delivery errors and has resource-type-specific late-packet handling. Multiplying it by 100 yields a percentage, but using that value for IP probe loss remains a disclosed proxy.
43. **Why choose CN PDB as the transport target?** Notes 4/5/13 explicitly allocate delay between the UPF terminating N6 and 5G-AN, closest to the represented transport segment. Giving the emulator that entire allocation is an approximation; real CN processing can consume some of it. The alternative radio-side-share calculation is comparison only, with an assumed configurable fraction.
44. **Why reject the delay-critical profiles?** The unchanged h1-to-h2 routes have larger configured delays than the selected CN budgets. A correct system explains infeasibility instead of relaxing the SLA or silently changing the topology. Adjacent-host feasibility may differ.
45. **Why was the grammar not changed?** Profiles generate normal existing fields and invoke the same validation/admission handler. Source metadata stays in the catalogue and GET /profiles. Tests protect the schema hash and the original handler, preserving the evaluated contract.
46. **Does remote surgery have a dedicated 5QI here?** No. Release 17's table has no dedicated remote-surgery row. We explicitly use discrete-automation 5QI 82 as a proxy, with an assumed bandwidth. That is not a clinical standard or safety certification.

## Parameter provenance and realism

47. **Are our probes one-way delay measurements?** No. The source times a UDP send-to-echo-reply exchange, including return-path and endpoint delay. RFC 7679 section 3.4 defines one-way delay; RFC 2681 section 2.4 defines round-trip delay. Our code compares RTT to the same bound used for one-way planning. Under symmetry this is roughly twice as strict; it does not prove a common one-way SLA. It is a custom echo, not RFC 5357 TWAMP.
48. **Are 2/5/12 ms links realistic metro links?** They are deliberate emulator budgets, not measured carrier links. G.114 (05/2003) Annex A.1 Table A.1 gives a provisional 5 microseconds/km planning value; pure propagation equivalents are 400/1000/2400 km per link. Processing/queuing may also be represented. A universal typical metro-span range was not verified, so we do not claim one.
49. **Where did detector constants come from?** Alpha 0.3, 10% hysteresis, three confirmations and 10 s dwell create a damped B3 comparator; B2 uses 1, 0%, one confirmation and zero dwell. The plan motivates anti-flapping; these numerical choices are engineering settings, not standards or proven optima. Higher smoothing/confirmation/dwell trades responsiveness for stability.
50. **Why a 250 ms drain window?** That fixed number in older documentation is stale. Current controller.py uses max(100 ms, twice old planned one-way latency plus 100 ms), giving 112/130/148 ms on nominal routes. Reitblatt's versioned update method motivates draining, not our numeric margin. Arbitrary fault and queue tails can exceed it, so no general WAN lifetime proof is claimed.
51. **Is this simulation or hardware?** It forwards real generated packets through live OVS software switches and Linux namespace hosts created by Mininet, inside Docker/WSL. This is network emulation. It is not a physical-switch deployment, a full 5G radio/core network, clinical certification or evidence of hardware TCAM scarcity.
52. **How are queues isolated when multiple intents share an egress port?** `dbm.allocate_queue_id` assigns each `(intent_id, port)` a distinct `queue_id` in `intent_queues` (starting sequentially at 1), and `queues.ensure_queue` attaches that queue UUID to the port's `linux-htb` QoS map without clobbering existing queues. On reroute or withdrawal, `queues.destroy_intent_queues` removes stale queues.
53. **Does reroute respect residual bandwidth and tenant isolation?** Yes. `ControlLoop.on_violation` calls `admission.replan_intent`, which builds `residual_graph` (excluding the rerouting intent's own bandwidth reservation) and checks bidirectional link disjointness against other tenants' active paths (`_canonical_link`).
54. **Why do reverse OpenFlow rules match `tp_src`?** When an intent specifies `dst_port` (e.g., UDP 5001), return packets from the server originate from source port 5001 (`tp_src=5001`). Matching `tp_src` in the reverse direction prevents broad reverse rules from stealing return traffic belonging to other co-hosted intents.
55. **What happens when `action_on_violation` is `DEGRADE` or `REROUTE_OR_DEGRADE` has no backup path?** The control loop invokes `controller.degrade_intent_queues` to scale the intent's HTB queue `min-rate` by `TEAM16_DEGRADE_FACTOR` (default `0.5`) and records an `SLA_DEGRADED` event and audit trail entry.
56. **Can a preempted intent recover automatically?** Yes. When an active intent is withdrawn (`DELETE /intent/{id}`), `admission.try_readmit_preempted` scans `preempted` intents in priority order (`CRITICAL`, `HIGH`, `NORMAL`, `LOW`) and re-admits any intent whose constraints are now feasible on the freed residual graph.
57. **What are the main remaining prototype limitations?** Preemption displaces at most one lower-priority victim per admission attempt (no multi-victim combinatorial search); OpenFlow control channels use plaintext TCP without TLS; the runtime container uses `privileged: true` and `network_mode: host` for Mininet/OVS access; and all evaluations are conducted on a single-machine emulated 7-switch, 8-host topology.
