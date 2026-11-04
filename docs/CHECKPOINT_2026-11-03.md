# Final integration and service-profile checkpoint - 3 November 2026

## Parameter provenance follow-up - 4 November 2026

Done: PARAMETER_PROVENANCE.md now contains 566 source-located parameter occurrences:
36 STANDARD, 13 PROJECT PLAN, 509 ENGINEERING CHOICE, 8 ASSUMPTION;
LITERATURE and MEASURED are both zero because papers motivate mechanisms and
configured settings are not field measurements. Official Y.1541 (12/2011), G.114
(05/2003), RFCs 7679/2681/5357 and all six local papers were opened. Source hashes
are retained in docs/report_assets/parameter_sources.json. Typical metro span
statistics, optimal detector tuning and general WAN drain sufficiency remain
NOT VERIFIED. No experiment was rerun; no raw file, runtime parameter, test,
topology or frozen schema changed.

The report has a provenance/realism subsection, was rebuilt and exported through
Word, and all 18 pages were visually inspected. Cover identities are unchanged.
Viva Q&A now has 51 questions. Older fixed-250-ms statements were corrected:
current code computes max(100 ms, twice old planned delay plus 100 ms). Y.1541
comparators are interpretive, not compliance mappings. RTT/one-way consequences
are enumerated without changing numerical results.

Fresh checks: host 316 passed, 3 warnings (10.25 s); Ruff exit 0; summaries exit 0;
manifest 355 artifacts, zero mismatches. The sandboxed host attempt stalled and
was interrupted; the complete host rerun outside the sandbox passed. Container
verification could not run: WSL returned Wsl/Service/CreateInstance/E_UNEXPECTED.
The earlier 305 passed / 11 skipped count below is historical. Actual current
verification details: docs/demo_assets/parameter_provenance_checks_20261104.json.

Publication attempted after commit 00cc46f: GitHub returned HTTP 403, permission
denied to platynom on 5rikanth/SDN. No branch push or PR succeeded.
Fallback outputs for this revision are ../SDN_final_integration.bundle and
../SDN_final_documents_20261104T081110Z.zip. The ZIP includes docs/*.md, the final DOCX/PDF
and experiments/figures/*; neither includes ignored standards PDFs or databases.
Next exact command after the owner grants write access:
`git push -u origin feat/final-integration`, then open a PR into
`feat/st-12-evaluation`. Never force-push, change permissions, or touch main.

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

Publication is blocked: GitHub rejected `git push -u origin feat/final-integration`
with HTTP 403, permission denied to the authenticated account `platynom` on
`5rikanth/SDN`. No PR was opened. The authorized fallback is a complete-history
bundle at `../SDN_final_integration.bundle` and a timestamped final-documents ZIP
beside the repository. These external release artifacts are not Git-tracked.
After the owner grants write access, the exact next command is:

```powershell
git push -u origin feat/final-integration
```

Then open a PR into `feat/st-12-evaluation`, never main. Do not force-push or
change account permissions as a workaround.

## Remaining scientific limitations

Profiles are project mappings, not 5G/clinical certification. Transport share and
several rates remain assumptions; PER and IP loss differ; runtime RTT and planning
one-way budgets differ. Functional profile checks are not sustained-rate or
extreme-reliability measurements. The existing fixed emulated topology, shared
queue and recovery resource-accounting limits remain disclosed in the report.
