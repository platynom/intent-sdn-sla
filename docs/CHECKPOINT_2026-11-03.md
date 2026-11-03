# Final integration and service-profile checkpoint - 3 November 2026

## Current state

Repository: SDN. Branch: feat/final-integration. This replaces the earlier stale
checkpoint: the full E6 accounting series and previous evaluation are complete.
No E1-E8 experiment was rerun for the service-profile layer. Existing raw CSVs,
topology and schema are unchanged relative to 73e6b57.

## Profile tasks completed

- T1: corrected pinned Release 17 references and service mappings; specs remain
  ignored, never tracked. Commit e74bc20.
- T2: documented default CN budget A, assumed-share comparison B, PER/IP-loss
  distinction, rate assumptions and unchanged-topology feasibility. Commit 1d64f7b.
- T3: profiles.yaml / profiles.py, GET /profiles, POST /intent/from-profile,
  generated examples and illustrative-fixture comments; 21 new regression cases.
  Existing POST /intent handler remains unchanged. Commit d5029f2.
- T4: isolated real activation/refusal evidence in docs/demo_assets/profile_*.
  eMBB and mMTC installed s1-s2-s3-s7 and forwarded matching UDP/TCP traffic;
  URLLC proxy, V2X and high-voltage protection returned explained refusals.
  Existing dashboard API displayed the active records with no invented telemetry.
  Commit 1759260. Startup HTB advisories did not fail the assertions.
- T5: sourced report subsection, checked export for report regeneration, README,
  code walkthrough, scope statement and six extra viva answers. Report exported
  with Word and all 16 pages inspected. Commit 01721be.
- T6 verification: host 316 passed; container 305 passed / 11 skipped; Ruff exit 0;
  independent summary verifier exit 0; S1, ST-7, ST-9, ST-10 all exit 0.
  Actual outputs are the 20261103T132758Z / 133047Z / 133114Z demo assets.
- L1: manifest regenerated and independently checked: 355 artifacts, zero
  mismatches. CSV/JSON line endings are canonicalized for hashes; raw files were
  not rewritten.
- L2: local core.autocrlf override unset. System Git setting remains untouched;
  .gitattributes still enforces LF for shell scripts. No whole-file CRLF diffs.

## Integrity

Physical schema SHA-256 stayed:
7a3a8b25067a3049f9668fb3c96e91f355cbd6d6ddb8e7d3b2b8fa2f53b44573
Git's LF-normalized baseline SHA-256:
6181eb5198e39a96b6fee65e28415c792e648cfb22805e3992bffd82df51003e
The difference is pre-existing Windows checkout line endings, not a schema edit.
Tests protect the baseline content and original handler. Report source-export
hashes and visual-QA metadata are in docs/report_assets/.

## Runtime and remaining publication step

Docker Engine runs inside WSL Ubuntu-22.04, not Docker Desktop. A temporary hidden
WSL keepalive was started (Windows PID 7188) after services stopped when the build
session closed. No running experiment was restarted. The four Compose services
can be prepared with:

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd '/mnt/c/Users/Admin/Documents/Software Defined Networks/SDN' && docker compose up -d"
```

Publication is pending the requested git push. If access is rejected, preserve the
integration branch in ../SDN_final_integration.bundle and final documents in a ZIP.
Do not change main, force-push, or change account permissions.

## Remaining scientific limitations

Profiles are project mappings, not 5G/clinical certification. Transport share and
several rates remain assumptions; PER and IP loss differ; runtime RTT and planning
one-way budgets differ. Functional profile checks are not sustained-rate or
extreme-reliability measurements. The existing fixed emulated topology, shared
queue and recovery resource-accounting limits remain disclosed in the report.
