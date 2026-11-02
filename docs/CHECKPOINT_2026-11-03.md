# Final integration checkpoint

## Completed

- T1: fetched and merged origin/feat/st-12-evaluation at a723800 into feat/final-integration from local 6b050dd. Merge commit 047ea8f. README was the only conflicted file; evaluation status was preserved and dashboard usage was retained.
- Software verification after merge: 278 passed, 11 skipped, Ruff clean. Fixed dashboard title/read-only metadata in b6d3ecd without altering tests.
- Dashboard API and browser inspection: four seeded application intents are present and their simulated measurements are explicitly labelled. The existing test demonstrates live-only selection after later real measurements.
- T4 code walkthrough committed as 2606ae7. T7 forty viva questions committed as 58cd802. T6 demo instructions committed as ce137e9; final smoke recordings and end-to-end command validation remain pending.
- Final report draft and generator exist. Amrita cover/logo retained; faculty name corrected to the user-specified Navin Kumar. Reference SHA-256: b4437154aa7cef630a9b24a9e8ea4f6a7caf80d7add3121899ff19fde3ccb976. Initial full-page layout review completed; pagination/table refinements and updated figures still require final render review.

## Active work

T3 is running ten full B2 E6 repetitions under prefix e6accounting_oscillation. Unified terminal session 39643 holds the live process. Do not restart it while active. The first completed full run produced 90 reroutes, 90 persisted violations, and 90 restorations. Each run requires a complete 600-s measurement window.

The scenario uses an isolated temporary SQLite database exported through TEAM16_DB_PATH. Direct SQL counts replace use of a bounded event-history list. Incomplete telemetry and B2 path/event mismatch now fail the run. A failed preliminary pilot demonstrated actual interference from auto-seeded bandwidth intents overwriting netem configuration when they shared the experiment database; its regression CSV is retained and must not be included in results.

Historical raw-file audit: only the initial three B2 and initial three B3 files show event shortfalls. The seven later runs of each baseline reconcile exactly. B3's initial shortfalls were also present, contrary to the earlier issue description. The exact historical extraction/runtime cause is not established from retained evidence; report that uncertainty, rather than asserting database loss or a particular old query limit.

All other database-backed measurement harnesses now default to separate temporary databases. These edits are awaiting final smoke verification and commit. E6's currently running shell input is an immutable sed-fed snapshot; do not alter or restart its active network.

## Remaining gates

1. Finish all ten E6 accounting runs, preserve their logs, recompute e6_accounting_summary and verify equality in every run. Update the historical issue note and report discussion without claiming an unproven historical cause.
2. Run all four requested live smoke scripts and one E4 B2/B3 regression with separate regression_ output prefixes. Capture real output into docs/demo_assets. No parallel Mininet scenarios.
3. Re-run final pytest/Ruff and independent verifier, including generated final-report tables. Fix source only for failures.
4. Rebuild FINAL_REPORT.md/docx after final summaries. Export with docs/render_final_report.ps1, render PDF pages using bundled pypdfium2, and inspect every page. The packaged renderer failed because bundled LibreOffice is absent; Word 16 export is working. Render work lives in .final_report_work and must not be committed.
5. Finalize demo script commands/fallback recordings, figures, manifest, and README status. Commit task changes separately.
6. Push feat/final-integration to origin and open a PR into feat/st-12-evaluation if permitted. If rejected, create the requested bundle and report-documents zip. Do not modify main.

## Environment and exact next operations

Repository: SDN, branch feat/final-integration. WSL distribution: Ubuntu-22.04. Docker Engine runs inside WSL; do not assume Windows Docker Desktop works. The existing E6 session can be polled directly. A separate diagnostic command is:

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd '/mnt/c/Users/Admin/Documents/Software Defined Networks/SDN' && docker compose exec -T sdn bash -lc 'tail -2 /var/log/team16/telemetry-e6-b2-1.log'"
```

Runtime capture: docs/report_assets/environment.json. Bundled report Python: C:/Users/Admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe. Build with that interpreter and docs/build_final_report.py. Export with PowerShell -File docs/render_final_report.ps1 -InputDocx docs/FINAL_REPORT.docx -OutputPdf docs/FINAL_REPORT.pdf. Existing untracked .fuse_hidden and state.db-wal files predate this integration; preserve them and keep databases out of commits.
