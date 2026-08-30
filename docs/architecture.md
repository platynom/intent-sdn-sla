# Architecture — test topology (ST-2)

The authoritative definition is `topology/topology_spec.py`. This document explains it.
If the two ever disagree, the code is right and this file is stale.

## Topology

```
            h1  h3                h5                 h7
              \  |                 |                  |
            [ s1 ]---------------[ s2 ]-------------[ s3 ]
              | \                                       |
              |  \---[ s4 ]---[ s5 ]                    |
              |        |         |                      |
            [ s6 ]-----+---------+--------------------[ s7 ]
              |                                        |  \
              h6                                      h2   h8
```

Seven Open vSwitch instances, eight hosts.

## Hosts

| Host | IP | Switch | Role |
|---|---|---|---|
| h1 | 10.0.0.1 | s1 | URLLC source |
| h2 | 10.0.0.2 | s7 | URLLC destination |
| h3 | 10.0.0.3 | s4 | cross-traffic source, middle route |
| h4 | 10.0.0.4 | s5 | cross-traffic sink, middle route |
| h5 | 10.0.0.5 | s2 | eMBB source |
| h6 | 10.0.0.6 | s6 | eMBB destination |
| h7 | 10.0.0.7 | s3 | IoT / mMTC source |
| h8 | 10.0.0.8 | s7 | IoT / mMTC destination |

Addresses are `10.0.0.<n>` for `h<n>`, matching Mininet's default allocation and the
addresses used in `intents/*.yaml`. Renumbering one without the other breaks every
scenario.

## Link budgets

Applied with `TCLink` using HTB. Host access links are deliberately **unconstrained** —
only the switch fabric carries budgets, otherwise measured latency double-counts the
access hop.

| Link | Bandwidth | One-way delay | |
|---|---|---|---|
| s1-s2 | 100 Mbps | 2 ms | |
| s2-s3 | 100 Mbps | 2 ms | |
| s3-s7 | 100 Mbps | 2 ms | inferred |
| s1-s4 | 50 Mbps | 5 ms | |
| s4-s5 | 50 Mbps | 5 ms | |
| s5-s7 | 50 Mbps | 5 ms | |
| s1-s6 | 40 Mbps | 12 ms | |
| s6-s7 | 40 Mbps | 12 ms | inferred |

## The three routes

Between s1 and s7, where the critical pair h1 and h2 live:

| Route | Path | Bottleneck | One-way delay |
|---|---|---|---|
| northern | s1 → s2 → s3 → s7 | 100 Mbps | 6 ms |
| middle | s1 → s4 → s5 → s7 | 50 Mbps | 15 ms |
| southern | s1 → s6 → s7 | 40 Mbps | 24 ms |

The three are **link-disjoint**: no link appears in more than one.

They are also deliberately unequal. Only the northern route satisfies the baseline
URLLC intent of 20 Mbps and 20 ms; the southern route violates the latency bound
outright. That asymmetry is what makes re-planning observable — three equivalent paths
would flatten every metric we intend to measure.

## Why three link-disjoint paths are mandatory

The system's entire purpose is to detect an SLA violation and move traffic somewhere
better. **With one path there is nowhere to move to and the closed loop cannot be
tested at all** — no scenario, no metric and no demonstration would mean anything.

Three specifically, rather than two:

- **Scenario S5** brings down the active path. Re-planning must still have a choice
  afterwards, not a forced move, or we are testing failover rather than planning.
- **Scenario S6** needs two alternatives of near-equal quality to induce the
  oscillation the dwell timer and hysteresis band exist to damp.
- **Scenario S7** (isolation) needs enough disjoint capacity to keep two tenants off
  each other's links. Deferred under the three-member variant, but the topology should
  not foreclose it.

`tests/test_topology.py::test_three_link_disjoint_paths_exist` asserts this property
directly, and `test_no_single_link_failure_disconnects_the_critical_pair` checks that
removing any one link still leaves the pair connected.

## Note on the original plan diagram

The project plan (Section 10) drew this topology as ASCII art and gave `tc` budgets for
six links only. The art was ambiguous about two edges: whether the bottom rail closes
**s6-s7**, and whether the right-hand column closes **s3-s7**.

That ambiguity is not cosmetic. Without both edges, s1 has only one route to s7 and the
plan's own claim — *"three disjoint h1→h2 paths: via s2, via s4-s5, via s6"* — is false.

We resolved it in the direction that makes the plan's claim true. Both inferred edges
are marked `inferred=True` in `topology_spec.py` and inherit the budget of the link they
continue, so the resolution is visible in the data rather than buried in a commit
message.

**The resolution is proved, not assumed.** `test_three_link_disjoint_paths_exist` runs
`networkx.edge_disjoint_paths` over the same edge list Mininet consumes and fails the
build if fewer than three exist. Had our reading been wrong, the test would have caught
it before any code was written against it.
