# E6 durable event accounting

## What the historical files establish

The first three historical B2 files each report 90 path revisions but only 50 violation events. The seven later B2 files report 90 of each. The first three B3 files also have a shortfall: their violation counts are 40, 40, and 41 against path-revision counts of 48, 48, and 50. The seven later B3 files reconcile. Therefore the earlier statement that this was exclusively a B2 issue was too broad. Original raw files remain unchanged.

Sources are the per-run `e6_oscillation_b2_*.csv` and `e6_oscillation_b3_*.csv` files and their registered `e6_oscillation_summary` outputs. The historical path-revision metric and historical event-accounting fields must be distinguished.

## Reproduction of the counting shortfall

An independent read-only observer captured the complete SQLite event and path records after the second isolated accounting rerun, before the next run reset its database. Its JSON snapshot is under `experiments/results/diagnostics/`, named after the corresponding `e6accounting_oscillation_b2_..._02.csv` file.

That snapshot contains 600 measurement rows, 90 reroutes, and 90 distinct persisted `sla.violated` rows. Applying a latest-200-row audit-history view to the very same durable event data produces only 50 violation rows. The remainder of that bounded view consists of restorations and installation/audit events. This reproduces the apparent 90-versus-50 discrepancy without losing an event from the database.

The demonstrated failure mechanism is using a bounded history page as a complete experimental count. The historical committed scenario currently specifies a larger history limit, and the original executed working tree/database snapshots were not preserved for those early files. Consequently the repository does not prove that a 200-row query was the exact historical invocation. The reproduction supports that explanation strongly, but does not justify retroactively changing those original CSVs or claiming their missing rows were recovered.

`INSERT OR IGNORE` makes a repeated publication of the same event id idempotent. This deliberately avoids duplicate audit rows; it does not merge distinct UUID-labelled transitions. Current control-loop dispatch reads persisted violations, and the new run snapshots reconcile these unique durable events with path revisions.

## Corrected measurement procedure

The E6 harness now counts all matching durable rows using SQL `GROUP BY type`, with the run-start filter applied in SQL. It does not count events through a UI/history pagination function. It requires the complete requested measurement count, propagates collector failure, checks fault-injector failure, and fails a B2 run if path changes and persisted violation counts differ.

Each invocation also has an isolated temporary database. During the first merged pilot, automatic dashboard seeding raced with the shared evaluation database. Ryu installed the seeded bandwidth queues and replaced the netem configuration used by the fault injector. That pilot is invalid for oscillation measurement and remains retained under the separate `regression_e6_accounting` prefix. The isolated pilot's data was followed by a shell error because the script had been edited during execution; it is also retained as diagnostic data, not included in a headline series. Full reruns execute an immutable sed-fed shell snapshot.

The corrected full B2 series uses `e6accounting_oscillation_b2_*.csv`. Its registered summary is `e6_accounting_summary.csv/json`. The observer's `_accounting.json` snapshots preserve full events, full paths, direct counts, a bounded-history comparison, and whether the snapshot agrees with the corresponding CSV. A snapshot that misses a reset boundary is flagged rather than treated as successful evidence.

## Interpretation

The completed corrected series, its summary, and the observer snapshots are the primary evidence for current B2 event accounting. Historical short event counts remain a provenance limitation. They do not establish that a controller can reroute without a durable violation, and they must not be used to claim event-persistence failure or a different detector rate. The oscillation comparison remains a path-revision comparison; causal-event claims use the corrected direct counts.
