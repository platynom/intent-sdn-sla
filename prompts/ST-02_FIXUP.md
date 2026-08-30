# Brief ST-02 FIXUP — your previous output failed review

> Paste this entire file into the same model. Do not summarise it.

---

## Situation

You previously worked on brief ST-02 for this project. Your output was reviewed
against the acceptance tests. **Four of the required files are missing and the one
file you produced fails four tests, one of which crashes at runtime on every single
run.**

You reported creating `experiments/scenarios/b0_baseline.sh`. It does not exist on
disk. Please do not report a file as created unless you have actually written it.

## Rule that overrides everything else

**Fix the implementation. Do not edit, delete, skip or weaken any test.** The tests
encode a project plan agreed by the team. If you believe a test is genuinely wrong,
say so in prose and explain why — but leave the file alone.

---

## Defect 1 — runtime crash in `_print_link_summary()` (topology/team16_topo.py:85)

```python
info(f"{link.name:12s}  {link.bw_mbps:7d}  {link.delay_ms:8d}")
```

`bw_mbps` and `delay_ms` are **floats** (`100.0`, `2.0`), declared as `float` in
`topology/topology_spec.py`. The `:d` format code only accepts integers, so this
raises:

```
ValueError: Unknown format code 'd' for object of type 'float'
```

This fires immediately after `net.start()`, so the topology crashes on every run.

**Fix:** use a float format such as `:7.1f` and `:8.1f`. Do not cast to `int` — the
budgets are floats deliberately and fractional values must remain representable.

## Defect 2 — missing `topos` dict

The brief required:

```python
topos = {"team16": (lambda: Team16Topo())}
```

so the topology can be used as `sudo mn --custom topology/team16_topo.py --topo team16`.
It is absent. Add it at module level.

## Defect 3 — silent empty topology when Mininet is absent

```python
def __init__(self, *args, **kwargs):
    if MININET_AVAILABLE:
        super().__init__(*args, **kwargs)
    else:
        return          # <-- silently produces an empty topology
```

A topology object that builds nothing is worse than a crash: the network comes up
with no switches and the failure surfaces much later, somewhere unrelated.

**Fix:** raise a clear error instead. The message **must contain the word "Mininet"**
so the cause is obvious from the message alone:

```python
if not MININET_AVAILABLE:
    raise RuntimeError(
        "Mininet is not available in this environment; "
        "run this inside the container (docker compose exec sdn ...)"
    )
```

Keep the module **importable** without Mininet — only *construction* may fail. The
unit tests import this module on a machine with no Mininet.

## Defect 4 — `ruff` fails

```
topology/team16_topo.py:30:5: E731 Do not assign a `lambda` expression, use a `def`
topology/team16_topo.py:31:5: E731 Do not assign a `lambda` expression, use a `def`
```

The `CLI` and `setLogLevel` fallbacks in the `except ImportError` branch use lambdas.
Replace them with `def` stubs, or restructure so the fallbacks are not needed.

## Defect 5 — an undeclared design decision

You set `autoStaticArp=True` on the `Mininet(...)` constructor. This pre-populates
every host's ARP table, which suppresses ARP broadcast traffic.

That is a meaningful choice in an SDN project: ARP handling is one of the behaviours
the controller is supposed to manage, and suppressing it can mask real forwarding
bugs and change the packet-in load we later measure as control-plane overhead
(metric E8).

**Either** remove it, **or** keep it and add a comment explaining the trade-off. Do
not leave an undeclared decision of this kind in the code.

---

## Still outstanding from the original brief

These three deliverables were never produced. All three are specified in full in
`prompts/ST-02_topology.md`, which you should re-read:

### `experiments/scenarios/b0_baseline.sh`

The B0 control condition — static forwarding, no intents, no monitoring. Bash,
`set -euo pipefail`, executable, `trap` cleanup. Measures h1↔h2 latency (`ping -c 100
-i 0.1`), throughput (`iperf3`, 30 s) and loss. Writes CSV to
`experiments/results/raw/b0_baseline_<timestamp>.csv` with header
`run_id,timestamp,metric,value,unit`. Accepts `--runs N`, default 10.

### `experiments/scenarios/flow_table_pilot.sh`

Determines whether flow-table pressure is measurable on software switches at all.
Installs a batch of dummy rules on `s1`, sweeps
`ovs-vsctl set bridge s1 other-config:flow-limit=<N>` over 100/500/1000/2000/5000/
unlimited, and records requested vs installed rule counts and install time. CSV
header `limit,requested_rules,installed_rules,rejected,install_seconds`. Ends by
printing exactly one of:

```
VERDICT: flow-table limit is enforceable — metric E5 is viable
VERDICT: flow-table limit had no effect — metric E5 will be flat, see ADR-003
```

### `docs/architecture.md`

At most two pages: ASCII topology diagram matching `topology_spec.py`, the table of
three routes with bottleneck bandwidth and delay, why three link-disjoint paths are
mandatory, and a note that the plan's original diagram was ambiguous about the s3-s7
and s6-s7 edges and that `tests/test_topology.py` proves the resolution rather than
assuming it.

---

## Constraints (unchanged)

- **Python 3.9.** No `match`, no runtime PEP 604 unions.
- **No new dependencies.** Only what is in `requirements.txt`.
- **Never hard-code topology data.** No literal `"s1"`, no literal `"10.0.0.x"`, no
  literal bandwidths or delays in `team16_topo.py`. There is a test that greps for
  exactly this.
- **Do not modify** anything under `tests/`, `src/`, or `topology/topology_spec.py`.
- Shell scripts need the executable bit and must be safe to run twice in a row.

## Acceptance

```bash
pytest tests -q                                    # expect 69 passed, 0 failed
ruff check topology tests src experiments          # expect no errors
```

Currently: `4 failed, 3 passed` in `tests/test_topo_script.py`.

Then, inside the container:

```bash
docker compose exec sdn python topology/team16_topo.py --no-cli
docker compose exec sdn ./experiments/scenarios/b0_baseline.sh --runs 3
docker compose exec sdn ./experiments/scenarios/flow_table_pilot.sh
```

## Deliverables checklist

- [ ] `topology/team16_topo.py` — five defects fixed
- [ ] `experiments/scenarios/b0_baseline.sh` (executable, actually written to disk)
- [ ] `experiments/scenarios/flow_table_pilot.sh` (executable, actually written to disk)
- [ ] `docs/architecture.md`
- [ ] `pytest tests -q` → all green, **no test file modified**
- [ ] `ruff check` clean
