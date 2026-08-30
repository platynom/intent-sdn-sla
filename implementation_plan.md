# Implementation Plan for Remaining Defects

## Goal
Fix the six remaining defects identified in the project:
1. Lint errors in `experiments/scenarios/_driver.py`.
2. Off‑by‑one error when counting installed OpenFlow rules.
3. Accumulation of orphaned `Flow_Table` rows.
4. Race condition between iperf3 server and client.
5. Fragile parsing of the `mdev` field from ping output.
6. Incorrect diagram rendering and missing documentation in `docs/architecture.md`.

All changes must preserve existing functionality, keep the tests passing (`69 passed`), and result in **zero ruff errors**.

## Constraints
- Python 3.9, no new dependencies.
- No hard‑coded topology values; use the existing `topology_spec` where needed.
- Only modify files within `experiments/scenarios/` and `docs/`.
- Use relative paths for any file operations.
- Do not edit files under `tests/`, `src/`, or `topology/`.

## Open Questions (User Review Required)
> **[!IMPORTANT]**
> Do you approve the proposed modifications, especially the addition of extra cleanup commands in the driver and the extended documentation in `architecture.md`?
>
> - The plan adds `time.sleep(1)` after starting the iperf3 server and checks the client output for connection failures.
> - The architecture document will be updated with the exact ASCII diagram (single backslashes) and additional tables/paragraphs.
>
> Please confirm or suggest alternatives.

## Proposed Changes

### 1. `experiments/scenarios/_driver.py`
- **Imports**: Split onto separate lines, drop `os`, and remove `SWITCHES` import if unused.
- **`parse_ping`**: Rename comprehension variable `l` to `line` and adjust the `mdev` parsing to use `split()[0]`.
- **Installed rules count**: Replace `wc -l` with `grep -c "cookie="` to exclude the header.
- **Flow‑Table cleanup**: At the start of each iteration, run:
  ```python
  s1.cmd('ovs-vsctl clear bridge %s flow_tables' % s1.name)
  s1.cmd('ovs-vsctl -- --all destroy Flow_Table')
  ```
  Also perform the same cleanup after the loop ends.
- **iperf3 race condition**: After launching the server (`h2.cmd('iperf3 -s -1 &')`), add `time.sleep(1)` and verify the client output for phrases like "connect failed". If a failure is detected, set `thr = ''` (empty string) instead of `0`.
- **General lint clean‑up**: Use explicit imports, rename ambiguous variables, and ensure no unused imports remain.

### 2. `docs/architecture.md`
- Replace the diagram block with the exact ASCII art from `topology/topology_spec.py` (single backslashes, no escaping).
- Add a table listing the three routes, their bottleneck bandwidths, and one‑way delays.
- Add a paragraph explaining why three link‑disjoint paths are mandatory for the SLA loop.
- Add a note about the original ambiguous plan diagram and how `tests/test_topology.py` proves the resolution.

## Verification Plan
- Run `bash -n` on both shell wrappers to ensure syntax.
- Execute `python -m pytest tests -q` – expect **69 passed**.
- Run `ruff check topology tests src experiments` – expect **0 errors**.
- Manually inspect a few pilot runs to confirm the iperf3 throughput handling and rule counting.

**UserFacing:** true, **RequestFeedback:** true
