# Brief ST-02 — Mininet topology, B0 baseline, flow-table pilot

> Paste this entire file into the model. Do not summarise it.

---

## Your role

You are implementing one subtask of an existing, well-specified undergraduate research
project. The architecture, the data model and the acceptance tests already exist and
are **not yours to change**. Produce code that makes the given tests pass and does
nothing else.

## Project context (one paragraph)

We are building an intent-based SDN system that enforces service-level agreements on
an emulated 5G transport network. An operator writes a machine-readable *intent* — a
promise such as "20 Mbps, never more than 20 ms delay, less than 0.5% loss" — and the
system compiles it into OpenFlow rules and queues, measures continuously whether the
promise is being kept, and automatically recomputes and reinstalls the path when it is
violated. It runs entirely on one laptop using Mininet and Open vSwitch, controlled by
Ryu. The system is six modules: **M1** Intent Manager, **M2** Admission & Conflict,
**M3** Path Computation, **M4** Enforcement, **M5** Telemetry & SLA Monitor,
**M6** Dashboard & Audit Log. This brief is infrastructure that precedes all of them.

## What ST-02 must deliver

Three things, in this order of importance:

1. A Mininet topology script that boots the network described by the existing spec.
2. A **B0 baseline** measurement harness — static shortest-path forwarding, no intents,
   no monitoring. This is the control condition every later result is compared against.
3. A **flow-table cap pilot** that answers one question early: *is the rule-space cost
   of a lossless path switch measurable at all on software switches?*

---

## GIVEN — read this before writing anything

### `topology/topology_spec.py` (already written, do not modify)

This is the single source of truth for the network. Import from it. Never hard-code an
edge, a bandwidth, a delay or a host IP anywhere else.

It exports:

```python
SWITCHES: tuple[str, ...]                    # ("s1" ... "s7")
LINKS: tuple[Link, ...]                      # Link(a, b, bw_mbps, delay_ms, inferred)
HOSTS: tuple[Host, ...]                      # Host(name, ip, switch, role)
CRITICAL_PAIR: tuple[str, str]               # ("h1", "h2")
REQUIRED_DISJOINT_PATHS: int                 # 3

host_by_name(name) -> Host
link_names() -> tuple[str, ...]              # canonical "sX-sY", lower switch first
build_graph()                                # NetworkX graph (needs networkx)
path_delay_ms(switch_path) -> float
path_bottleneck_mbps(switch_path) -> float
```

`Link.name` gives the canonical `sX-sY` identifier used by the intent grammar's
`avoid_links` field.

The topology has **seven switches, eight hosts, and exactly three link-disjoint paths**
between s1 and s7 (where h1 and h2 live):

| Route | Links | Bottleneck | One-way delay |
|---|---|---|---|
| northern | s1-s2, s2-s3, s3-s7 | 100 Mbps | 6 ms |
| middle | s1-s4, s4-s5, s5-s7 | 50 Mbps | 15 ms |
| southern | s1-s6, s6-s7 | 40 Mbps | 24 ms |

Three disjoint paths are mandatory. Without alternatives there is nothing to re-plan
to and the closed loop cannot be tested.

### Existing repository layout

```
topology/topology_spec.py       the spec above — read only
topology/team16_topo.py         YOU WRITE THIS (currently a docstring stub)
experiments/scenarios/          YOU ADD SCRIPTS HERE
tests/test_topology.py          acceptance tests — read only, already passing
src/intent_manager/schema.json  the frozen intent grammar
docker-compose.yml              privileged container with Mininet + OVS + Ryu
```

---

## REQUIREMENTS

### 1. `topology/team16_topo.py`

A Mininet topology built from `topology_spec`.

- Subclass `mininet.topo.Topo`. Class name `Team16Topo`.
- Build switches from `SWITCHES`, hosts from `HOSTS` (set each host's IP from
  `Host.ip` with a `/24`), and switch-to-switch links from `LINKS`.
- Apply each link's budget with `TCLink`: `bw=link.bw_mbps`, `delay=f"{delay_ms}ms"`.
  Use `max_queue_size=1000` and `use_htb=True` so bandwidth limiting is HTB-based, as
  the enforcement module later assumes.
- **Host access links are unconstrained** — no `bw` or `delay` on host-to-switch links.
  Only the switch fabric carries budgets, otherwise measured latency double-counts.
- Register the topology as `topos = {"team16": (lambda: Team16Topo())}` so it can be
  used with `sudo mn --custom`.
- Provide a `if __name__ == "__main__":` block that starts the network with a remote
  controller at `127.0.0.1:6653`, calls `net.pingAll()`, prints a summary table of
  every link and its budget, and drops into the Mininet CLI. Accept `--no-cli` to skip
  the CLI (needed for scripted runs) and `--controller-ip` / `--controller-port`.
- Use `mininet.log.setLogLevel("info")`.
- The module must be **importable without Mininet installed** — put every `mininet`
  import inside the functions or guard the module-level ones, so the unit tests can
  import `topology_spec` through this package on a machine without Mininet. If that is
  not achievable cleanly, keep all Mininet imports below a `try/except ImportError`
  that sets a `MININET_AVAILABLE` flag.

### 2. `experiments/scenarios/b0_baseline.sh`

The B0 control condition: static shortest-path forwarding, no intents, no monitoring.

- Bash, `set -euo pipefail`, executable.
- Boot the topology with Mininet's built-in learning switch behaviour — that is,
  **no Ryu controller**; use `--controller ovsc` or OVS's own MAC learning, so there is
  genuinely no intent logic in the path.
- Measure, between `h1` and `h2`:
  - round-trip latency with `ping -c 100 -i 0.1`, capturing min/avg/max/mdev
  - throughput with `iperf3` for 30 seconds
  - loss percentage from the ping summary
- Write results as **CSV** to `experiments/results/raw/b0_baseline_<timestamp>.csv`
  with a header row: `run_id,timestamp,metric,value,unit`.
- Accept `--runs N` (default 10) and loop, because every data point in this project is
  the mean of at least ten runs with confidence intervals. One run is not a result.
- Print a one-line summary per run to stdout so a human can watch it work.
- Clean up with `mn -c` on exit, including on failure (use `trap`).

### 3. `experiments/scenarios/flow_table_pilot.sh`

This is the important one. Read the reasoning before implementing.

**Why it exists.** Moving traffic to a new path can be done two ways. The cheap way
installs the new rules immediately and drops packets that are in flight. The careful
way ("two-phase update") tags packets with a version number so each packet follows
either the old path or the new one, never a mixture — losing almost nothing, but
holding the old and new rule sets simultaneously, roughly doubling flow-table
occupancy during the switch-over. On hardware switches that space is scarce and
expensive, which is the entire reason anyone chooses between the two methods.

**The risk.** We run Open vSwitch in software, where flow tables live in ordinary RAM
and are effectively unbounded. If the cost never bites, our metric E5 (flow-table
entries used) produces a flat, meaningless graph. We need to know that in August, not
during the evaluation weeks in November.

**What the script must do:**

- Boot the topology.
- Install a deliberately large number of dummy flow rules on `s1` (parameterised,
  default 2000) using `ovs-ofctl add-flows` from a batch file — not one call per rule,
  which is far too slow.
- Sweep a flow-table limit using
  `ovs-vsctl set bridge s1 other-config:flow-limit=<N>` over a range (default:
  100, 500, 1000, 2000, 5000, unlimited).
- At each limit, record:
  - how many rules `ovs-ofctl dump-flows s1 | wc -l` actually reports
  - whether rule installation was rejected or silently evicted
  - the wall-clock time to install the batch
- Write CSV to `experiments/results/raw/flow_table_pilot_<timestamp>.csv` with header
  `limit,requested_rules,installed_rules,rejected,install_seconds`.
- Print a clear verdict at the end, in these exact words depending on the outcome:
  - `VERDICT: flow-table limit is enforceable — metric E5 is viable`
  - `VERDICT: flow-table limit had no effect — metric E5 will be flat, see ADR-003`

### 4. `docs/architecture.md`

A short document, at most two pages, containing:

- The topology diagram in ASCII, matching `topology_spec.py` exactly.
- The table of three routes with their bottleneck bandwidth and delay.
- A paragraph explaining why three link-disjoint paths are mandatory.
- A note recording that the plan's original ASCII art was ambiguous about two edges
  (s3-s7 and s6-s7), that we resolved it in the direction that makes the plan's own
  three-disjoint-path claim true, and that `tests/test_topology.py` proves it rather
  than assuming it.

---

## CONSTRAINTS — violating any of these fails review

- **Python 3.9.** No `match` statements. No PEP 604 unions evaluated at runtime.
- **Only the dependencies already in `requirements.txt`.** Mininet, NetworkX, pytest.
  No new libraries.
- **Never hard-code topology data.** Every switch, host, IP, bandwidth and delay comes
  from `topology_spec`. If you find yourself typing `100` or `"10.0.0.1"` in
  `team16_topo.py`, you have made a mistake.
- **Do not modify** `topology/topology_spec.py`, `tests/test_topology.py`,
  `src/intent_manager/schema.json`, or anything under `src/`.
- **Do not add** a sixth constraint type to the intent grammar or touch the schema.
- Shell scripts: `set -euo pipefail`, `trap` for cleanup, executable bit set.
- Every script must be safe to run twice in a row — clean up stale Mininet state first.
- Comment *why*, not *what*. Explain the reasoning behind a non-obvious choice; do not
  narrate the code.
- No emoji, no decorative banners in code or output.

---

## ACCEPTANCE

The existing test suite must stay green, and it must stay green **without you editing
any test**:

```bash
pytest tests -q          # expect: 62 passed
ruff check topology tests src experiments
```

Then, inside the container:

```bash
docker compose up -d --build
docker compose exec sdn python topology/team16_topo.py --no-cli
docker compose exec sdn ./experiments/scenarios/b0_baseline.sh --runs 3
docker compose exec sdn ./experiments/scenarios/flow_table_pilot.sh
```

Expected: `pingAll` reports 0% dropped, the B0 CSV appears with three runs of data,
and the pilot prints one of the two verdict lines.

**If a test fails, fix your implementation — do not edit the test.** The tests encode
the project plan. If you believe a test is genuinely wrong, say so and explain why
rather than changing it.

## Deliverables checklist

- [ ] `topology/team16_topo.py`
- [ ] `experiments/scenarios/b0_baseline.sh` (executable)
- [ ] `experiments/scenarios/flow_table_pilot.sh` (executable)
- [ ] `docs/architecture.md`
- [ ] `pytest tests -q` → 62 passed, no test files modified
- [ ] `ruff check` clean
