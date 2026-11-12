# Architecture Decision Records

Every architectural choice and its reasoning. This file is where viva answers come
from. Append, never rewrite history.

Compatibility correction (3 November 2026): ADR-001's historical explanation below
incorrectly attributes removal of `ssl.wrap_socket` to Python 3.10. The removal
occurred in Python 3.12, as documented in the official [Python release notes](https://docs.python.org/3.12/whatsnew/3.12.html#ssl).
The evidence for this project's pin is its verified Python 3.9.25 / Ryu 4.34 /
legacy dependency image. We have not validated every other interpreter and
dependency combination and do not claim that all Python 3.10+ combinations fail
for that reason. The original ADR text is retained as the historical record.

---

## ADR-001 - SDN controller: Ryu 4.34 on Python 3.9, inside Docker

**Date:** 07 Aug 2026 (ST-1) **Status:** Accepted **Decision owner:** whole team

**Context.** The project needs an OpenFlow 1.3 controller. Two realistic options:
Ryu (Python, small API, large tutorial base) and ONOS 2.7 (Java, production-grade,
actively maintained).

Ryu is effectively unmaintained. Its `eventlet` dependency breaks on Python 3.10+
because `ssl.wrap_socket` was removed. Ubuntu 22.04 ships Python 3.10, so a host
install fails outright.

**Decision.** Ryu 4.34, pinned to Python 3.9, `eventlet==0.30.2` and
`dnspython==1.16.0`, entirely inside the Docker image. Never pip-install Ryu on a
host machine.

**Reasoning.** Three members, fourteen weeks, and the difficulty of this project is
in the control loop, not the controller API. Ryu lets us write the whole controller
in the same language as the rest of the system. ONOS would add a Java toolchain and
a substantial learning curve to a schedule that has no slack for it.

**Consequences.**
- We inherit an unmaintained dependency. Mitigated by pinning inside a container,
  so the environment is reproducible regardless of host Python.
- We cannot claim to have extended a production controller.
- If Ryu proves unworkable by the end of ST-1, ONOS 2.7 is the documented fallback.
  After ST-1 this decision is closed.

**Considered and rejected.** *os-ken*, the maintained OpenStack fork of Ryu with a
near-identical API, would remove the Python 3.9 pin. Rejected for now only because
its documentation base is far smaller and we could not verify its current state
inside ST-1. Worth revisiting if Ryu blocks us.

---

## ADR-002 - The intent grammar is frozen at five constraint types

**Date:** 07 Aug 2026 (ST-1) **Status:** Accepted **Decision owner:** whole team

**Context.** Scope creep in the intent grammar is listed in the project plan's risk
register at likelihood High, impact High. Every new constraint type multiplies work
across M1 (validation), M2 (feasibility), M3 (pruning), M4 (enforcement) and M5
(measurement).

**Decision.** The grammar is frozen at:
- **Five constraint types:** `min_bandwidth_mbps`, `max_latency_ms`, `max_loss_pct`,
  `isolate_from`, `avoid_links`
- **Three violation actions:** `reroute`, `degrade`, `alert_only`
- **One priority scale:** integer 1 (highest) to 5 (best effort)
- **Two consistency modes:** `strict` (two-phase versioned update),
  `relaxed` (direct install)

`additionalProperties: false` at every level of the schema, so an unknown field is a
hard error rather than a silent ignore.

**Enforcement.** `tests/test_intent_validation.py` asserts the exact constraint set,
the exact action set and the priority bounds. CI runs those assertions on every push.
Widening the grammar requires editing a test that says, in terms, not to.

**Consequences.** Jitter is deliberately absent as a *constraint* even though M5
measures it, because a jitter bound would need its own admission maths. Any new
constraint type proposed after ST-3 is rejected by default.

---

## ADR-003 - Evaluation metric E9 and the flow-table pilot are additions to the plan

**Date:** 07 Aug 2026 (ST-1) **Status:** Accepted

**Context.** The project plan defines metrics E1-E8. Two additions were made during
planning and should not be presented as though they came from the plan.

**Decision.**
1. **E9 - time and resources from a clean VM to first result.** The plan claims
   laptop reproducibility but never measures it. E9 turns the claim into a number.
2. **Flow-table cap pilot pulled forward into ST-2.** Two-phase update roughly
   doubles flow-table occupancy during a switch-over, but that cost only bites where
   switch memory is scarce. Open vSwitch in software keeps flow tables in RAM, so
   metric E5 may return a flat result. Testing this in August rather than in the
   evaluation weeks is the difference between a scheduling adjustment and a crisis.

**Consequences.** If the pilot shows no measurable difference, E5 is demoted and the
evaluation leans on E2, E3, E4 and E6, which Mininet represents faithfully.

### Pilot result (25 Oct 2026)

The corrected pilot created 2,000 distinct OpenFlow matches per trial and tested
the documented OVS bridge `other-config:flow-limit` values 100, 500, 1,000, 2,000
and 5,000, plus an unlimited control. OVS 2.17.12 retained all 2,000 rules in every
trial (about 0.29–0.31 seconds per batch). The tested software-switch configuration
therefore showed no measurable cap effect; this does not establish hardware TCAM
capacity or behavior. The raw CSV is
`experiments/results/raw/flow_table_pilot_20261025161825.csv`.

---

## ADR-004 - Per-intent HTB queue allocation per egress port

**Date:** 11 Nov 2026 (Audit P1/P2) **Status:** Accepted **Decision owner:** whole team

**Context.** Initially, `ensure_queue` hardcoded `queues:1` on every switch egress port
and overwrote the port's root QoS `max-rate` with the latest intent's bandwidth. When
two bandwidth-guaranteed intents traversed the same inter-switch link, the second
intent overwrote the first intent's HTB queue entry and capped the shared root QoS.

**Decision.** Allocate a deterministic, collision-checked `queue_id` per `(intent_id, switch, port)`
persisted in SQLite (`intent_queues` table, starting at `1` so single-intent scenarios
bind `set_queue:1`, and assigning distinct integers `2, 3, ...` to additional intents).
Keep the port's root `linux-htb` QoS `max-rate` at the physical link capacity
(`link_capacity_mbps`) while setting each intent's `min-rate` and `max-rate` on its
own `Queue` record. Pass `queue_ids` into `rules_for_path` and `two_phase.versioned_rules`,
raise `QueueConfigurationError` on `ovs-vsctl` failure, and remove an intent's queues
when it is withdrawn, preempted, or moved off a port.

**Consequences.** Concurrent bandwidth-guaranteed intents sharing a link receive
independent HTB minimum-rate queues without capping the link root or clobbering one
another's shaping configuration.

---

## ADR-005 - Bidirectional tenant isolation on admission and reroute

**Date:** 11 Nov 2026 (Audit D3/D4) **Status:** Accepted **Decision owner:** whole team

**Context.** Previously, `tenant_paths` only collected active intents by tenant name,
and `prune` only checked the incoming intent's `isolate_from` list. If an already-active
intent of tenant `alpha` declared `isolate_from: [beta]` and a new intent from tenant
`beta` had `isolate_from: []`, `beta` was admitted onto `alpha`'s links. Furthermore,
closed-loop reroute did not pass `tenant_paths` into `compute_path`, allowing a
rerouted intent to violate isolation.

**Decision.** Extend `tenant_paths(conn)` to return both `by_tenant` (active links per
tenant) and `isolated_links_for` (active links belonging to any active intent whose
`isolate_from` includes a given tenant). Update `prune()` and `compute_path()` to enforce
both directions (`guarantee.isolate_from` and `isolated_links_for[intent_tenant]`), and
pass `tenant_paths(self.conn)` during closed-loop reroute in `ControlLoop.on_violation`.

**Consequences.** Isolation is symmetric and preserved across both initial admission
and closed-loop recovery.

---

## ADR-006 - Closed-loop reroute uses residual-capacity admission graph

**Date:** 11 Nov 2026 (Audit D2) **Status:** Accepted **Decision owner:** whole team

**Context.** `ControlLoop.on_violation` previously computed alternate paths on a
copy of `self.graph` (physical link capacities) after removing only the violating
intent's current links. It ignored bandwidth already reserved by other admitted or
active intents on alternate paths, allowing a reroute to oversubscribe a link.

**Decision.** Build the reroute planning graph from `residual_graph(self.conn, self.graph, exclude_intent_id=intent.id)`
before removing the violating path's links, and pass `tenant_paths(self.conn)` and
`intent.tenant` to `compute_path`. Exclude `exclude_intent_id` from `residual_graph`
so the rerouting intent does not subtract its own prior reservation.

**Consequences.** Closed-loop reroutes obey the exact same residual-capacity and
bidirectional isolation invariants as initial M2 admission.
