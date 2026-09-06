# ST-7 brief - close the control loop

Work only in this repository. ST-7 connects confirmed M5 SLA violations back to
M3 path computation and M4 enforcement. Do not add telemetry collection,
admission/preemption policy, dashboard work or evaluation features in this task.

## Read before changing anything

- `src/common/models.py`: `IntentRecord`, `IntentState`, `OnViolation`,
  `PathPlan` and the authoritative `IntentRecord.may_replan_at(now)` dwell gate.
- `src/common/events.py`: `Event`, `EventBus`, `EventType` and event constructors.
- `src/common/db.py`: intent/path loading and persistence.
- `src/common/audit.py`: `AuditLog.chain` and its five-part causal record.
- `src/pathing/compute.py`: `compute_path(intent, graph, tenant_paths=None)`.
- `src/enforcement/controller.py`: `install_plan(plan, intent, event_bus=None)`.
- `src/telemetry/detector.py`: what constitutes one confirmed violation event.

Do not change a frozen shared interface merely to make the loop convenient.

## Build

Implement `src/telemetry/loop.py`:

```python
class ControlLoop:
    def __init__(self, conn, graph, controller, bus, audit):
        ...

    def on_violation(self, event, now=None):
        ...
```

Construction must subscribe `on_violation` to `EventType.SLA_VIOLATED` on the
provided `EventBus`. `on_violation` must also remain directly callable in tests.
When `now` is omitted, use the event timestamp; do not call `time.sleep`, and do
not make tests depend on wall-clock time.

## Required behaviour

1. Validate the event defensively. An event without a known `intent_id` must not
   crash or alter the network; record an explanation where an intent is known.
2. Load the current `IntentRecord` and path from SQLite. Keep the persisted record
   as the source of truth.
3. Honour `intent.on_violation`:
   - `alert_only`: write the causal audit chain and make no state, path or network
     change.
   - `degrade`: set the intent state to `IntentState.DEGRADED`, persist it, write
     the causal audit chain and do not reroute.
   - `reroute`: continue with the remaining steps.
4. For rerouting, call `intent.may_replan_at(now)`. Do not reproduce its dwell
   arithmetic in the loop. If it returns false, retain the current path, do not
   call the controller, and audit that dwell suppressed the action.
5. Make a copy of the supplied NetworkX graph. Remove every link in the current
   `PathPlan` from that copy before calling `compute_path`. This exclusion is
   mandatory: otherwise the deterministic selector can choose the same failing
   path again and claim it rerouted.
6. If no alternative path exists, keep the current path installed and current in
   the database. Do not update `last_replan_at`. Write an audit chain that states
   plainly that no feasible alternative exists and includes the path-computation
   reasons.
7. If an alternative exists, call `controller.install_plan(new_plan, intent, bus)`.
   Only after installation succeeds:
   - call `db.save_path(conn, new_plan)` so the old path becomes superseded;
   - set `intent.current_path` to the new plan;
   - set `intent.last_replan_at` to the injected `now`;
   - set the appropriate active state and persist the intent;
   - write the complete causal audit chain.
8. Catch any exception raised by the controller. The event subscriber must never
   crash the event bus. Keep the old path current, do not update
   `last_replan_at`, and audit the exact installation failure.
9. Every outcome must call `AuditLog.chain` with all five causal parts:
   intent, observed measurement, promised threshold, decision and action. Obtain
   the metric, observed value and threshold from the violation event payload;
   do not invent them.

## Safety and scope constraints

- Python 3.9: no `match` statements and no runtime PEP 604 union annotations.
- Unit tests require no Ryu, Mininet, root privileges, sockets or sleeps.
- Use fake controllers, an in-memory SQLite database and injected timestamps.
- Do not edit an existing test to make the implementation pass.
- Do not implement two-phase updates, admission, preemption or dashboard logic.
- Never mutate the shared topology graph while excluding the current route.

## Acceptance tests to add

Create `tests/test_control_loop.py` with at least these cases. Every test must
explain in its docstring what production failure it prevents.

1. Construction subscribes exactly to `EventType.SLA_VIOLATED`.
2. Publishing another event type performs no control action.
3. An unknown intent does not crash or call the controller.
4. `alert_only` writes an audit chain and does not change state or path.
5. `degrade` persists `DEGRADED` and does not call the controller.
6. `reroute` calls the existing `may_replan_at(now)` dwell rule.
7. An active dwell timer suppresses controller installation.
8. Dwell suppression retains the current path and `last_replan_at`.
9. Once dwell expires, the identical violation may proceed.
10. Path computation receives a graph without any current-path link.
11. The original graph is unchanged after computation.
12. The failing current path cannot be selected again.
13. No feasible alternative retains the current path.
14. No feasible alternative leaves `last_replan_at` unchanged.
15. No feasible alternative produces a readable causal audit entry.
16. A successful installation saves the new path.
17. A successful installation supersedes exactly the previous path.
18. A successful installation stores the injected time in `last_replan_at`.
19. A successful action includes measurement, threshold, decision and action in
    the audit record.
20. A controller exception is caught rather than escaping through the event bus.
21. A controller exception leaves the old path current.
22. A controller exception does not advance `last_replan_at`.
23. Re-publishing one event cannot corrupt path history.
24. The loop imports and all tests run when Ryu and Mininet are absent.

### Mandatory oscillation experiment test

Run the same alternating violation/recovery sequence twice with an identical
injected clock and fresh state:

- `dwell_seconds=0` must produce many reroutes.
- `dwell_seconds=10` must produce at most one or two reroutes over the same
  interval.
- The damped reroute count must be strictly lower than the undamped count.

Count reroutes through `db.reroute_count`, not a mock-only counter. This is the
test that proves the loop is controlled rather than merely connected.

## Acceptance commands

```bash
python -m pytest tests/test_control_loop.py -v
python -m pytest tests -q
python -m ruff check src tests topology experiments
python -c "import src.telemetry.loop; print('loop imports ok')"
```

Report real output. If a check fails, show the failure and fix production source,
not the test.
