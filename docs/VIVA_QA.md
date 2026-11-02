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
