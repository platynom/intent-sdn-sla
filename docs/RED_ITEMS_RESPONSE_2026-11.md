# Team 16 — Paper Draft Red Items & Out-of-Date Claims Response (`exp/red-items-2026-11`)

- **Branch:** `exp/red-items-2026-11` (branched from `main` at `75f2d2e18eddc84bc7046077dd9dea7c83f3726e`, `Merge pull request #2 from platynom/fix/audit-2026-11`)
- **Environment:** Ubuntu 22.04 WSL2 (`Linux DESKTOP-7Q6OT1V 6.18.33.1-microsoft-standard-WSL2`), Docker `29.6.1`, Docker Compose `v5.3.1`, image `team16/intent-sdn-sla:dev` (`Python 3.9.25`), recorded in `experiments/results/redfill_2026-11/BASELINE.txt`
- **Terminology convention:** Every value below is explicitly labelled **measured**, **predicted**, or **configured** and cites its source CSV(s) under `experiments/results/redfill_2026-11/`.
- **Data provenance disclosure:** All E9–E16 runs executed against build `75f2d2e` inside the `sdn` container (with E14 comparing `cf25af2` vs. `75f2d2e`). All 50 E9 runs completed by `2026-11-18 16:08:33 UTC` (last raw file `redfill_e9_b3_20261118160833.csv`), before the temporary live-telemetry edit to `experiments/scenarios/s1_single_intent.sh` (`2026-11-18 16:08:51`–`16:09:12 UTC`) used for E10's 150 runs (`s1_single_intent.sh` was subsequently parameterized behind `TEAM16_WAIT_FOR_LIVE_VIOLATION`, defaulting to `0`, verified by `smoke2`). No `src/` files or `src/intent_manager/schema.json` were modified, and no historical files under `experiments/results/raw/`, `experiments/results/summary/`, `experiments/figures/`, or `experiments/results/MANIFEST.sha256` were touched.

---

## Section A — Red Items (`C1`–`C2`, `J1`–`J12`)

### Item `C1`
- **Paper:** Conference (`IBN_ClosedLoop_Conference (1).pdf`)
- **Page:** p. 3 (Section IV-A, Setup, and Table I)
- **Exact red text:** `[rerun B2 on the current build]`
- **Replacement text (LaTeX-ready):**
  > All rows of Table~I were measured on the current build (`75f2d2e`), where contention-safe residual repair (Section~III) performs per-intent residual-capacity, bidirectional isolation, and barrier/error confirmation checks on every reroute. Under this common build, B2 immediate ($k=1$) measured $101.1\text{ ms}$ [$96.3, 105.9$] detection and $458.1\text{ ms}$ [$421.1, 495.1$] recovery; matched-detector B2 ($k=3$) measured $2096.3\text{ ms}$ [$2091.9, 2100.7$] detection and $454.5\text{ ms}$ [$414.2, 494.8$] recovery; and B3 damped ($k=3$) measured $2094.7\text{ ms}$ [$2092.4, 2097.0$] detection and $628.5\text{ ms}$ [$601.0, 656.1$] recovery. Thus, strict B3 recovery is $174.0\text{ ms}$ slower than matched-detector B2 on `75f2d2e` ($p = 5.27\times 10^{-7}$, Welch's $t$-test). Relative to the earlier draft build, both B2 ($458.1$ vs.\ $279.4\text{ ms}$) and B3 ($628.5$ vs.\ $537.9\text{ ms}$) increased; the exact per-change cause has not been isolated experimentally (waiting for barrier replies added in `P3` is the most likely contributor, not proven in isolation).

  Full replacement **Table I** (LaTeX-ready, **measured** at $n=10$):
  ```latex
  \begin{table}[t]
  \centering
  \caption{Detection and Recovery Latency (ms) on Build \texttt{75f2d2e}, Mean [95\% CI], $n=10$}
  \begin{tabular}{llcc}
  \hline
  Baseline & Detector & Detection & Recovery \\
  \hline
  B2 & immediate ($k=1$) & $101.1$ [$96.3, 105.9$] & $458.1$ [$421.1, 495.1$] \\
  B2 & as B3 ($k=3$) & $2096.3$ [$2091.9, 2100.7$] & $454.5$ [$414.2, 494.8$] \\
  B3 & damped ($k=3$) & $2094.7$ [$2092.4, 2097.0$] & $628.5$ [$601.0, 656.1$] \\
  \hline
  \end{tabular}
  \end{table}
  ```
- **Source CSV(s):** `experiments/results/redfill_2026-11/E9/summary.csv`, `experiments/results/redfill_2026-11/E9/welch_tests.csv`, and raw runs `experiments/results/redfill_2026-11/E9/raw/redfill_e9_{b2,b2matched,b3}_*.csv`

---

### Item `C2`
- **Paper:** Conference (`IBN_ClosedLoop_Conference (1).pdf`)
- **Page:** p. 4 (Section IV-C, Costs and Agreement with the Models — Transitions (E4))
- **Exact red text:** `[confirm the old and new paths of E4]`
- **Replacement text (LaTeX-ready):**
  > Code inspection of `experiments/scenarios/e4_packet_loss.sh` (at commit `75f2d2e`, lines~79--81, 113--119, 158, 171, and 176) and `topology/topology_spec.py` confirms that E4 initializes on the north route `s1-s2-s3-s7` (`6 ms` configured nominal one-way delay) with a `40 ms` `netem` fault on egress interface `s1-eth2` ($D_{\text{old}} = 40 + 2 + 2 = 44\text{ ms}$ configured), and verifies rerouting onto the middle route `s1-s4-s5-s7` ($D_{\text{new}} = 5 + 5 + 5 = 15\text{ ms}$ configured). The resulting configured nominal one-way delay difference is $\Delta D = 44 - 15 = 29\text{ ms}$, which agrees within 1 packet with the $28\text{ ms}$ inferred in the draft from 28 reordered packets at $1000\text{ pkt/s}$ and is directly re-measured by E12 Pair~A ($28.000$ [$28.000, 28.000$] reordered packets at $1000\text{ pkt/s}$, giving $\Delta D_{\text{meas}} = 28.001\text{ ms}$).
- **Source CSV(s) & Code:** `experiments/scenarios/e4_packet_loss.sh` (commit `75f2d2e` L79–81, L113–119, L158, L171, L176), `topology/topology_spec.py`, `experiments/results/redfill_2026-11/E12/model_comparison.csv`, `experiments/results/redfill_2026-11/E12/summary.csv`

---

### Item `J1`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 1 (Author/funding footnote)
- **Exact red text:** `[Corresponding author and funding acknowledgement, if any.]`
- **Replacement text (LaTeX-ready):**
  > **TEAM DECISION REQUIRED.**
  > - Corresponding author: *(leave author selection blank for team decision)*
  > - Suggested default funding sentence: `This work received no external funding.`
- **Source CSV(s):** N/A (editorial metadata)

---

### Item `J2`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 2 (Introduction, last paragraph)
- **Exact red text:** `[citation once accepted]`
- **Replacement text (LaTeX-ready):**
  > `LEAVE AS IS until the conference paper is accepted.`
- **Source CSV(s):** N/A (editorial citation placeholder)

---

### Item `J3`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 7 (Section 5.1, Setup, and Table 2)
- **Exact red text:** `[rerun B2 on the current build]`
- **Replacement text (LaTeX-ready):**
  > Same replacement data as **C1**: on commit `75f2d2e` ($n=10$ per row), **measured** B2 immediate ($k=1$) is $101.1\text{ ms}$ [$96.3, 105.9$] detection and $458.1\text{ ms}$ [$421.1, 495.1$] recovery; matched-detector B2 ($k=3$) is $2096.3\text{ ms}$ [$2091.9, 2100.7$] detection and $454.5\text{ ms}$ [$414.2, 494.8$] recovery; and B3 damped ($k=3$) is $2094.7\text{ ms}$ [$2092.4, 2097.0$] detection and $628.5\text{ ms}$ [$601.0, 656.1$] recovery (Table~2 updated identically to Conference Table~I above; recovery difference between B2 matched and B3 on `75f2d2e` is $174.0\text{ ms}$, $p = 5.27\times 10^{-7}$; the cause of the recovery increase relative to the earlier draft build—`458.1` vs.\ `279.4 ms` for B2 and `628.5` vs.\ `537.9 ms` for B3—has not been isolated experimentally, with barrier-reply wait in `P3` the most likely contributor). In addition, same-build O3 **measured** $18.737\text{ Mbit/s}$ [$18.039, 19.435$] ($25.038\%$ [$22.245, 27.832$] loss) unbound vs. $24.995\text{ Mbit/s}$ [$24.995, 24.996$] ($0.000\%$ loss, $74.400\text{ Mbit/s}$ cross-traffic) bound ($p = 8.05\times 10^{-9}$ Welch $t$-test for intent throughput; $p = 1.08\times 10^{-5}$ exact permutation test for loss).
- **Source CSV(s):** `experiments/results/redfill_2026-11/E9/summary.csv`, `experiments/results/redfill_2026-11/E9/welch_tests.csv`, `experiments/results/redfill_2026-11/E9/raw/redfill_e9_*.csv`

---

### Item `J4`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 9 (Section 5.3, Costs and Agreement with the Models — Transitions (E4))
- **Exact red text:** `[confirm the old and new paths of E4]`
- **Replacement text (LaTeX-ready):**
  > Same replacement text as **C2**: `experiments/scenarios/e4_packet_loss.sh` (commit `75f2d2e` L79–81, L113–119, L158, L171, L176) and `topology/topology_spec.py` confirm the initial route is north (`s1-s2-s3-s7`) with a configured `40 ms` `netem` delay on `s1-eth2` ($D_{\text{old}} = 44\text{ ms}$ configured) and the repaired route is middle (`s1-s4-s5-s7`, $D_{\text{new}} = 15\text{ ms}$ configured), yielding nominal configured $\Delta D = 29\text{ ms}$ against the $28\text{ ms}$ inferred from 28 reordered packets at $1000\text{ pkt/s}$.
- **Source CSV(s) & Code:** `experiments/scenarios/e4_packet_loss.sh`, `topology/topology_spec.py`, `experiments/results/redfill_2026-11/E12/model_comparison.csv`

---

### Items `J5`–`J12` (Journal Table 5, p. 11, eight `[result]` cells)

#### `J5` — Row `E9`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 11 (Section 6.1, Table 5, row E9)
- **Exact red text:** `[result]`
- **Replacement text (LaTeX-ready):**
  > On `75f2d2e`, B2 recovered in $458.1$ [$421.1, 495.1$]\,ms, matched B2 in $454.5$ [$414.2, 494.8$]\,ms, and B3 in $628.5$ [$601.0, 656.1$]\,ms ($+174.0\text{ ms}$ difference on `75f2d2e`, $p=5.27\times 10^{-7}$; shift vs.\ earlier build not isolated, barrier wait in `P3` likely); O3 unbound achieved $18.74$ [$18.04, 19.44$]\,Mbit/s ($25.0\%$ loss).
- **Source CSV(s):** `experiments/results/redfill_2026-11/E9/summary.csv`, `experiments/results/redfill_2026-11/E9/welch_tests.csv`

#### `J6` — Row `E10`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 11 (Section 6.1, Table 5, row E10)
- **Exact red text:** `[result]`
- **Replacement text (LaTeX-ready):**
  > Across all 15 $(k,\Delta t)$ settings ($150$ runs), measured $T_{\text{det}}$ agrees within $0.00\%$ to $-5.46\%$ of Eq.~(9) with fixed $t_0=0.1\text{ s}$; least squares yields $\hat{t}_0 = 97.6\text{ ms}$ ($\text{SD}=7.1\text{ ms}$, $R^2=0.99996$).
- **Source CSV(s):** `experiments/results/redfill_2026-11/E10/model_comparison.csv`, `experiments/results/redfill_2026-11/E10/summary.csv`, `experiments/results/redfill_2026-11/E10/t0_fit.json`

#### `J7` — Row `E11`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 11 (Section 6.1, Table 5, row E11)
- **Exact red text:** `[result]`
- **Replacement text (LaTeX-ready):**
  > Reroutes fell from $60.0$ [$60.0, 60.0$] at $\delta=0\text{ s}$ to $49.2$ [$45.5, 52.9$] ($\delta=10\text{ s}$), $30.0$ [$30.0, 30.0$] ($\delta=20\text{ s}$), and $19.4$ [$18.7, 20.1$] ($\delta=30\text{ s}$), within $-0.8\%$ to $+10.5\%$ of Eq.~(10) using effective B3 confirmable count $N_f=60$ (derived from the `experiments/scenarios/e6_oscillation.sh` schedule lines~224--259, where Phase~5 at lines~248--250 lasts $1.5\text{ s}$, vs.\ $4.2\text{ s}$ and $3.0\text{ s}$ in Phases~1 and~3; not measured per phase; strict bound held in all 50 runs).
- **Source CSV(s):** `experiments/results/redfill_2026-11/E11/model_comparison.csv`, `experiments/results/redfill_2026-11/E11/summary.csv`

#### `J8` — Row `E12`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 11 (Section 6.1, Table 5, row E12)
- **Exact red text:** `[result]`
- **Replacement text (LaTeX-ready):**
  > Across 180 runs ($\lambda \approx 250$--$4000\text{ pkt/s}$, pairs A--C), relaxed updates lost $10.4$--$172.2$ packets ($T_{\text{gap}}=40.5$--$43.2\text{ ms}$, $-1.2\%$ to $+5.4\%$ vs.\ $41\text{ ms}$); strict updates lost $0$ and reordered $4.1$--$114.3$ packets (within $\pm 7.7\%$ for pairs~A/C and $1000$--$4000\text{ pkt/s}$ pair~B, $-18.0\%$ at $250\text{ pkt/s}$ pair~B due to integer packet quantization).
- **Source CSV(s):** `experiments/results/redfill_2026-11/E12/model_comparison.csv`, `experiments/results/redfill_2026-11/E12/summary.csv`

#### `J9` — Row `E13`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 11 (Section 6.1, Table 5, row E13)
- **Exact red text:** `[result]`
- **Replacement text (LaTeX-ready):**
  > At fixed $6\text{ ms}$ normal jitter ($n=10$, $600$ samples/run), false confirmations dropped from $0.1280$ [$0.1135, 0.1425$] ($76.8$/run, predicted $q_1(1-q_1)=0.1255$ at $\theta=20\text{ ms}$, $+2.0\%$) under the naive detector to $0.00183$ [$0.00052, 0.00315$] ($1.1$/run, predicted $0.00216$) at EWMA $k=1$, and $0/5990$ ($k=2$) and $0/5980$ ($k=3$) ($95\%$ rule-of-three upper bound $5.0\times 10^{-4}$).
- **Source CSV(s):** `experiments/results/redfill_2026-11/E13/model_comparison.csv`, `experiments/results/redfill_2026-11/E13/summary.csv`, `experiments/results/redfill_2026-11/E13/chosen_jitter_ms.txt`

#### `J10` — Row `E14`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 11 (Section 6.1, Table 5, row E14)
- **Exact red text:** `[result]`
- **Replacement text (LaTeX-ready):**
  > In control-plane contention ($N \in \{4,8,12,16\}$, total floor $80\text{ Mbit/s}$), commit `cf25af2` over-committed all 3 links of the middle path in every run ($\max r_{\text{res}}/C = 1.20$--$1.40$ all-intents fault; $1.47$--$1.60$ north-fault), whereas Algorithm~2 on `main` (`75f2d2e`) recorded $0$ over-committed links ($\max r_{\text{res}}/C \le 1.000$) in all 40 runs; live check E14b \textsc{not run} (OVS HTB replaces root `netem`).
- **Source CSV(s):** `experiments/results/redfill_2026-11/E14/summary.csv`, `experiments/results/redfill_2026-11/E14/raw/redfill_e14_*.csv`

#### `J11` — Row `E15`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 11 (Section 6.1, Table 5, row E15)
- **Exact red text:** `[result]`
- **Replacement text (LaTeX-ready):**
  > Shared-clock OWD matched configured healthy budgets ($6.70$, $15.82$, $24.94\text{ ms}$ vs.\ $6,15,24\text{ ms}$) with $\text{RTT}/2$ within $0.02\text{ ms}$; under asymmetric $40\text{ ms}$ forward faults, true forward OWD measured $44.92$, $51.07$, and $52.96\text{ ms}$ (0\% $\le 35\text{ ms}$ compliance), while $\text{RTT}/2$ underestimated forward delay by $-19.02$, $-17.51$, and $-14.03\text{ ms}$, falsely clearing North ($25.90\text{ ms}$) and Middle ($33.56\text{ ms}$).
- **Source CSV(s):** `experiments/results/redfill_2026-11/E15/model_comparison.csv`, `experiments/results/redfill_2026-11/E15/summary.csv`

#### `J12` — Row `E16`
- **Paper:** Journal (`IBN_ClosedLoop_Journal_extended (1).pdf`)
- **Page:** p. 11 (Section 6.1, Table 5, row E16)
- **Exact red text:** `[result]`
- **Replacement text (LaTeX-ready):**
  > On archived Geant2012 (40 nodes, 61 links, configured $100\text{ Mbit/s}$, $0.05\text{ ms}$ delay floor, 3 fallback $1\text{ ms}$ links; SHA-256 `8487b2fb...d4786e` from `prateekshyap/CPP-in-SDN`), mean admission latency grew from $3.78$ [$2.73, 4.83$]\,ms ($k=1$) to $11.06$ [$8.76, 13.36$]\,ms ($k=64$) vs.\ $0.94$--$7.32\text{ ms}$ on Team16 7-switch; software rule-count proxy reached $76$ rules/switch ($152$ under strict $2\times$ overlap); hardware/P4 TCAM \textsc{not run} (not available).
- **Source CSV(s):** `experiments/results/redfill_2026-11/E16/model_comparison.csv`, `experiments/results/redfill_2026-11/E16/summary.csv`

---

## Section B — Out-of-Date Draft Statements Resolved on `main` (`75f2d2e`)

Between baseline commit `cf25af2` (`Merge pull request #1 from platynom/feat/final-integration`) and current `main` at `75f2d2e` (`Merge pull request #2 from platynom/fix/audit-2026-11`, documented in `docs/AUDIT_FIXES_2026-11.md`), engineering audit fixes `D1`–`D6`, `P1`–`P8`, and `M1`–`M3` updated the codebase. The following statements in the drafts are now out of date:

1. **Journal Sec. 4.2 (p. 7, after Proposition 6)**
   - **Out-of-date draft sentence:** `"The measured system computes repairs without step 1, so it satisfies Proposition 6 only when a single intent is active."`
   - **Codebase state & citation:** Audit fix **D2** in commit `f52de5c` (`fix(admission,loop): enforce residual capacity and bidirectional isolation on admission and reroute (D2-D4)`, merged in `75f2d2e`, documented in `docs/AUDIT_FIXES_2026-11.md` Section 1) updated `ControlLoop.on_violation` in `src/telemetry/loop.py` to build `residual_graph(self.conn, self.graph, exclude_intent_ids={intent.id})` and call `tenant_paths(...)`, implementing Algorithm~2 step~1.
   - **Replacement text (LaTeX-ready):**
     > Following audit fix D2 (`f52de5c`, merged in `75f2d2e`), the control loop computes repairs via Algorithm~2 on `residual_graph(conn, graph, exclude_intent_ids={intent.id})`, so Proposition~6 holds for concurrent multi-intent recovery as validated in E14 (Section~6.1); only the pre-audit E1--E8 runs on `cf25af2` omitted step~1.

2. **Journal Sec. 6.3 (p. 11) and Conference Sec. IV-D / V (p. 5)**
   - **Out-of-date draft sentence:** `"Recovery does not yet repeat residual admission."` (Journal p. 11) / `"Recovery does not yet repeat residual admission (Section III). Next steps are contention-safe recovery with residual admission..."` (Conference p. 5)
   - **Codebase state & citation:** Resolved by audit fix **D2** (`f52de5c`, merged in `75f2d2e`; `docs/AUDIT_FIXES_2026-11.md`). Note also that **M2** (`5c7c815`) added `reconcile_preempted_intents()` after withdrawal/reroute/degrade.
   - **Replacement text (LaTeX-ready):**
     > Residual-capacity admission during recovery (Algorithm~2) was added on `main` (`75f2d2e`, audit fix D2 in `f52de5c`); E14 validates that zero link bandwidth floors are over-committed under concurrent reroutes, whereas E1--E8 measured the earlier `cf25af2` build.

3. **Journal Sec. 5.2 (p. 7, O3 paragraph) and Conference Sec. IV-B (p. 4, O3 paragraph)**
   - **Out-of-date draft clause:** `"...and the bound rules share one queue identifier, so the result establishes protection for one flow."` (and Journal Sec. 5.2 `"The unbound series comes from an earlier build, and the bound rules share one queue identifier, so the result establishes protection for one flow."`)
   - **Codebase state & citation:** Resolved by audit fix **P1** in commits `408b179` and `fd0b879` (merged in `75f2d2e`; `docs/AUDIT_FIXES_2026-11.md` Section 1 & Section 3): `src/common/db.py` (`intent_queues`, `allocate_queue_id()`), `src/enforcement/queues.py`, `src/enforcement/flowmod.py`, and `src/enforcement/controller.py` now allocate dedicated per-intent HTB queue IDs per switch port (starting at queue 1) and clean them up on withdrawal. Same-build E9 re-measured both O3 unbound and O3 bound on `75f2d2e`.
   - **Replacement text (LaTeX-ready):**
     > Both the unbound and bound O3 series were re-measured on commit `75f2d2e` (E9), where audit fix P1 (`408b179`, `fd0b879`) assigns each active bandwidth intent a dedicated per-port HTB queue identifier in `intent_queues` rather than sharing queue~1; live multi-intent verification (`docs/AUDIT_FIXES_2026-11.md`, Section~3) confirms distinct `set_queue` bindings for co-hosted flows.

4. **Measured Strict-vs.-Relaxed Recovery Overhead (`174.0 ms` vs. `70 ms` in Draft Sec. IV-C / 5.3)**
   - **Out-of-date draft figure:** Draft Sec. IV-C (Conference p. 4) / Sec. 5.3 (Journal p. 9) reports `70 ms` (`537.9 - 467.7 ms`) between relaxed and strict recovery across two different builds (`cf25af2` vs later B3).
   - **Codebase state & source CSV:** Same-build E9 on `75f2d2e` (`E9/summary.csv`, `E9/welch_tests.csv`) measures `454.517 ms` (`B2_matched_detector`) vs `628.510 ms` (`B3`), giving a **measured** strict-minus-relaxed difference of **$173.993\text{ ms}$ ($174.0\text{ ms}$, $p = 5.27\times 10^{-7}$)**.
   - **Replacement text (LaTeX-ready):**
     > Measured on the same build (`75f2d2e`, E9), recovery was $454.5$ [$414.2, 494.8$]\,ms for matched-detector relaxed replacement vs.\ $628.5$ [$601.0, 656.1$]\,ms for strict two-phase update, a $174.0\text{ ms}$ difference ($p=5.27\times 10^{-7}$); both B2 (`458.1` vs.\ `279.4 ms`) and B3 (`628.5` vs.\ `537.9 ms`) also shifted upward from the earlier draft build, and the per-change cause has not been isolated experimentally (barrier-reply wait in `P3` is the most likely contributor, not proven in isolation).

5. **Alternating-Fault Confirmable Transitions on S6 (`N_f = 60` vs. `N_f = 90` in Draft Sec. 5.3 / Eq. 10 & Fig. 4b)**
   - **Clarification (derived from script schedule, not measured per phase):** Inspection of `experiments/scenarios/e6_oscillation.sh` (lines 224–259) shows `s6` runs 30 macro-cycles of 20 s each in 600 s, creating 90 raw `tc` fault/restoration transitions (`B2` immediate $k=1$ reacts to all 90): Phase 1 (lines 226–228) holds `+30 ms` for `4.2 s`, Phase 3 (lines 238–240) holds `+45 ms` for `3.0 s`, and Phase 5 (lines 248–250) holds `+18 ms` for only `1.5 s`. Because B3's detector requires $k=3$ consecutive breaches at 1 Hz sampling, Phase 5 spans at most 1–2 samples and is filtered out, leaving **$N_f = 60$ confirmable transitions** ($30 \times 2$). Both predictions (`N_f = 90` and `N_f = 60`) are reported in Section C (E11).

---

## Section C — Full Results Tables (`E9`–`E16`)

### E9 — Same-Build Rerun of Table I / Table 2 & O3 (Commit `75f2d2e`, $n=10$)
Source CSVs: `experiments/results/redfill_2026-11/E9/summary.csv`, `experiments/results/redfill_2026-11/E9/welch_tests.csv`.

| Group | Metric | Type | $n$ | Mean | SD | 95% CI | Unit | Draft Table I/2 & O3 | Diff vs Draft | Source CSV |
|---|---|---|---|---|---|---|---|---|---|---|
| `B2` | `detection_latency` | measured | 10 | 101.095 | 6.690 | [96.309, 105.881] | ms | 99.5 [96.2, 102.7] | +1.6% | `E9/summary.csv` |
| `B2` | `recovery_latency` | measured | 10 | 458.082 | 51.740 | [421.072, 495.093] | ms | 279.4 [228.9, 329.8] | **+64.0%** | `E9/summary.csv` |
| `B2` | `reroute_count` | measured | 10 | 1.000 | 0.000 | [1.000, 1.000] | count | 1.0 | 0.0% | `E9/summary.csv` |
| `B2_matched_detector` | `detection_latency` | measured | 10 | 2096.301 | 6.121 | [2091.922, 2100.679] | ms | 2116.8 [2107.3, 2126.4] | -1.0% | `E9/summary.csv` |
| `B2_matched_detector` | `recovery_latency` | measured | 10 | 454.517 | 56.372 | [414.194, 494.841] | ms | 467.7 [424.9, 510.5] | -2.8% | `E9/summary.csv` |
| `B2_matched_detector` | `reroute_count` | measured | 10 | 1.000 | 0.000 | [1.000, 1.000] | count | 1.0 | 0.0% | `E9/summary.csv` |
| `B3` | `detection_latency` | measured | 10 | 2094.722 | 3.178 | [2092.448, 2096.995] | ms | 2115.9 [2108.7, 2123.1] | -1.0% | `E9/summary.csv` |
| `B3` | `recovery_latency` | measured | 10 | 628.510 | 38.524 | [600.954, 656.067] | ms | 537.9 [446.4, 629.3] | **+16.8%** | `E9/summary.csv` |
| `B3` | `reroute_count` | measured | 10 | 1.000 | 0.000 | [1.000, 1.000] | count | 1.0 | 0.0% | `E9/summary.csv` |
| `O3_unbound` | `intent_throughput_mbps` | measured | 10 | 18.737 | 0.976 | [18.039, 19.435] | Mbps | 19.09 | -1.8% | `E9/summary.csv` |
| `O3_unbound` | `intent_loss_pct` | measured | 10 | 25.038 | 3.905 | [22.245, 27.832] | pct | 23.6% | +1.44 pp | `E9/summary.csv` |
| `O3_unbound` | `cross_traffic_throughput_mbps` | measured | 10 | 80.644 | 0.967 | [79.952, 81.336] | Mbps | 80.1 (Fig. 3c) | +0.7% | `E9/summary.csv` |
| `O3_unbound` | `cross_traffic_loss_pct` | measured | 10 | 46.228 | 0.645 | [45.766, 46.689] | pct | — | — | `E9/summary.csv` |
| `O3_bound` | `intent_throughput_mbps` | measured | 10 | 24.995 | 0.000 | [24.995, 24.996] | Mbps | 24.995 | 0.0% | `E9/summary.csv` |
| `O3_bound` | `intent_loss_pct` | measured | 10 | 0.000 | 0.000 | [0.000, 0.000] | pct | 0% | 0.0 pp | `E9/summary.csv` |
| `O3_bound` | `cross_traffic_throughput_mbps` | measured | 10 | 74.400 | 0.025 | [74.383, 74.418] | Mbps | 74.2 | +0.3% | `E9/summary.csv` |
| `O3_bound` | `cross_traffic_loss_pct` | measured | 10 | 50.391 | 0.016 | [50.379, 50.402] | pct | — | — | `E9/summary.csv` |

Welch & exact permutation tests (`E9/welch_tests.csv`, **measured**):
- Recovery `B2` vs `B3`: diff $= -170.428\text{ ms}$, $t = -8.355$, $\text{df} = 16.633$, $p = 2.364\times 10^{-7}$.
- Recovery `B2_matched_detector` vs `B3`: diff $= -173.993\text{ ms}$, $t = -8.058$, $\text{df} = 15.901$, $p = 5.267\times 10^{-7}$.
- `O3_bound` vs `O3_unbound` `intent_throughput_mbps`: diff $= +6.259\text{ Mbps}$, $t = 20.274$, $\text{df} = 9.000$, $p = 8.052\times 10^{-9}$; `intent_loss_pct`: exact permutation diff $= -25.038\%$, $p = 1.083\times 10^{-5}$.

---

### E10 — Detection Delay Sweep ($k \in \{1..5\} \times \Delta t \in \{0.25, 0.5, 1.0\}\text{ s}$, 150 runs)
All 150 runs executed live in Mininet with `TEAM16_WAIT_FOR_LIVE_VIOLATION` skip behavior (`1`) so real telemetry triggered every reroute (`n* = 1`, `n=10` per cell). Least-squares fit over all 150 runs (`E10/t0_fit.json`): **measured** $\hat{t}_0 = 97.584\text{ ms}$ ($0.09758\text{ s}$, $\text{SD} = 7.134\text{ ms}$, $\text{SE} = 0.582\text{ ms}$, $R^2 = 0.999960$; $R^2 = 0.999956$ with fixed $t_0 = 100\text{ ms}$). Source CSVs: `experiments/results/redfill_2026-11/E10/model_comparison.csv`, `E10/summary.csv`, `E10/t0_fit.json`.

| Configured $k$ | Configured $\Delta t$ (s) | $n$ | Measured Mean (ms) | SD (ms) | Measured 95% CI (ms) | Predicted Eq. (9) ($t_0=0.1\text{ s}$) | Abs Error (ms) | % Error |
|---|---|---:|---:|---:|---|---:|---:|---:|
| 1 | 0.25 | 10 | 96.725 | 3.172 | [94.456, 98.995] | 100.000 | -3.275 | -3.27% |
| 2 | 0.25 | 10 | 345.235 | 6.053 | [340.905, 349.564] | 350.000 | -4.765 | -1.36% |
| 3 | 0.25 | 10 | 596.036 | 8.268 | [590.122, 601.950] | 600.000 | -3.964 | -0.66% |
| 4 | 0.25 | 10 | 849.540 | 7.248 | [844.355, 854.724] | 850.000 | -0.460 | -0.05% |
| 5 | 0.25 | 10 | 1099.277 | 7.749 | [1093.734, 1104.820] | 1100.000 | -0.723 | -0.07% |
| 1 | 0.50 | 10 | 94.538 | 9.611 | [87.663, 101.413] | 100.000 | -5.462 | -5.46% |
| 2 | 0.50 | 10 | 594.077 | 3.358 | [591.676, 596.479] | 600.000 | -5.923 | -0.99% |
| 3 | 0.50 | 10 | 1099.192 | 8.267 | [1093.279, 1105.106] | 1100.000 | -0.808 | -0.07% |
| 4 | 0.50 | 10 | 1602.381 | 9.516 | [1595.575, 1609.188] | 1600.000 | +2.381 | +0.15% |
| 5 | 0.50 | 10 | 2098.318 | 6.340 | [2093.783, 2102.853] | 2100.000 | -1.682 | -0.08% |
| 1 | 1.00 | 10 | 95.246 | 7.061 | [90.196, 100.297] | 100.000 | -4.754 | -4.75% |
| 2 | 1.00 | 10 | 1094.035 | 4.978 | [1090.474, 1097.596] | 1100.000 | -5.965 | -0.54% |
| 3 | 1.00 | 10 | 2098.560 | 7.291 | [2093.345, 2103.775] | 2100.000 | -1.440 | -0.07% |
| 4 | 1.00 | 10 | 3100.012 | 6.229 | [3095.557, 3104.468] | 3100.000 | +0.012 | +0.00% |
| 5 | 1.00 | 10 | 4100.581 | 6.148 | [4096.183, 4104.978] | 4100.000 | +0.581 | +0.01% |

---

### E11 — Dwell Sweep ($\delta \in \{0, 5, 10, 20, 30\}\text{ s}$ on S6, $T=600\text{ s}$, 50 runs)
Predictions shown for both $N_f = 90$ (paper Eq. 10 using all raw `tc` transitions) and $N_f = 60$ (effective B3-confirmable transitions, derived from `experiments/scenarios/e6_oscillation.sh` lines 224–259 because Phase 5 at lines 248–250 lasts $1.5\text{ s}$ vs.\ $4.2\text{ s}$ and $3.0\text{ s}$ in Phases 1 and 3—not measured per phase), with $T_{\text{det}} = 2.1\text{ s}$. Source CSVs: `experiments/results/redfill_2026-11/E11/model_comparison.csv`, `E11/summary.csv`.

| Configured $\delta$ (s) | $n$ | Measured Reroutes/10m | SD | Measured 95% CI | Max Run | Measured Dwell Suppressions Mean [CI] (`E11/summary.csv`) | Pred. Eq. (10) ($N_f=90$) | Err ($N_f=90$) | Pred. Eq. (10) ($N_f=60$) | Err ($N_f=60$) | Strict Bound ($\lfloor T/\delta\rfloor+1$ / $N_f$) Held? |
|---:|---:|---:|---:|---|---:|---|---:|---:|---:|---:|---|
| 0 | 10 | 60.000 | 0.000 | [60.000, 60.000] | 60 | 0.000 [0.000, 0.000] | 90.000 | **-33.33%** | 60.000 | +0.00% | True (max 60 $\le$ 60, 90) |
| 5 | 10 | 59.900 | 0.316 | [59.674, 60.126] | 60 | 0.000 [0.000, 0.000] | 84.507 | **-29.12%** | 60.000 | -0.17% | True (max 60 $\le$ 60, 90, 121) |
| 10 | 10 | 49.200 | 5.203 | [45.479, 52.921] | 56 | 28.000 [26.123, 29.877] | 49.587 | -0.78% | 49.587 | -0.78% | True (max 56 $\le$ 61) |
| 20 | 10 | 30.000 | 0.000 | [30.000, 30.000] | 30 | 35.800 [34.858, 36.742] | 27.149 | **+10.50%** | 27.149 | **+10.50%** | True (max 30 $\le$ 31) |
| 30 | 10 | 19.400 | 0.966 | [18.709, 20.091] | 20 | 46.700 [45.392, 48.008] | 18.692 | +3.79% | 18.692 | +3.79% | True (max 20 $\le$ 21) |

*(Note: During `d20` run 2 on 2026-11-19 ~02:20–02:30 UTC the host laptop shut down without writing a file; 9 resumed runs restarted filename indexing at `_01`, completing $n=10$ distinct runs for `d20`.)*

---

### E12 — Rate & Path-Pair Sweep (Pairs A/B/C $\times \{250, 1000, 4000\}\text{ pkt/s} \times \{b2, b3\}$, 180 runs)
All 18 cells achieved $99.996\%$ to $100.02\%$ of target rate (zero cells below 90%). Predictions use achieved per-run rate $\lambda = \text{packets\_sent}/\text{window\_duration\_s}$ with paper $T_{\text{gap}}=41\text{ ms}$ for relaxed `b2` loss and configured $\Delta D \in \{29, 20, 26\}\text{ ms}$ for strict `b3` reordering ($0$ strict loss predicted and observed in all 90 strict runs). Source CSVs: `experiments/results/redfill_2026-11/E12/model_comparison.csv`, `E12/summary.csv`.

| Pair | Target $\lambda$ (pkt/s) | Mode | $n$ | Measured Achieved $\lambda$ | Measured Lost Mean (SD; 95% CI) | Pred. Lost ($\lambda T_{\text{gap}}$) | Lost Err % | Measured $T_{\text{gap}}$ (ms) | Measured Reord. Mean (SD; 95% CI) | Pred. Reord. ($\lambda\Delta D$) | Reord. Err % | Measured $\Delta D$ (ms) | Config $\Delta D$ (ms) |
|---|---:|---|---:|---:|---|---:|---:|---:|---|---:|---:|---:|---:|
| A | 250 | b2 | 10 | 250.04 | 10.400 (0.966; [9.709, 11.091]) | 10.252 | +1.44% | 41.593 | 0.000 (0.000; [0, 0]) | 0 | — | 0.000 | 29.0 |
| A | 250 | b3 | 10 | 250.02 | 0.000 (0.000; [0, 0]) | 0.000 | 0.0% | — | 7.000 (0.000; [7.000, 7.000]) | 7.251 | -3.46% | 27.998 | 29.0 |
| A | 1000 | b2 | 10 | 1000.01 | 40.500 (2.415; [38.772, 42.228]) | 41.000 | -1.22% | 40.500 | 0.000 (0.000; [0, 0]) | 0 | — | 0.000 | 29.0 |
| A | 1000 | b3 | 10 | 999.96 | 0.000 (0.000; [0, 0]) | 0.000 | 0.0% | — | 28.000 (0.000; [28.000, 28.000]) | 28.999 | -3.44% | 28.001 | 29.0 |
| A | 4000 | b2 | 10 | 4000.03 | 168.000 (0.000; [168.000, 168.000]) | 164.001 | +2.44% | 42.000 | 2.800 (5.903; [-1.422, 7.022]) | 0 | — | 0.700 | 29.0 |
| A | 4000 | b3 | 10 | 3999.98 | 0.000 (0.000; [0, 0]) | 0.000 | 0.0% | — | 114.300 (0.483; [113.954, 114.646]) | 116.000 | -1.47% | 28.575 | 29.0 |
| B | 250 | b2 | 10 | 249.99 | 10.400 (0.699; [9.900, 10.900]) | 10.250 | +1.46% | 41.601 | 0.000 (0.000; [0, 0]) | 0 | — | 0.000 | 20.0 |
| B | 250 | b3 | 10 | 250.05 | 0.000 (0.000; [0, 0]) | 0.000 | 0.0% | — | 4.100 (0.316; [3.874, 4.326]) | 5.001 | **-18.02%** | 16.397 | 20.0 |
| B | 1000 | b2 | 10 | 999.98 | 43.000 (3.162; [40.738, 45.262]) | 40.999 | +4.88% | 43.001 | 0.000 (0.000; [0, 0]) | 0 | — | 0.000 | 20.0 |
| B | 1000 | b3 | 10 | 1000.04 | 0.000 (0.000; [0, 0]) | 0.000 | 0.0% | — | 19.000 (0.000; [19.000, 19.000]) | 20.001 | -5.00% | 18.999 | 20.0 |
| B | 4000 | b2 | 10 | 3999.99 | 169.400 (11.207; [161.383, 177.417]) | 163.999 | +3.29% | 42.350 | 0.000 (0.000; [0, 0]) | 0 | — | 0.000 | 20.0 |
| B | 4000 | b3 | 10 | 4000.01 | 0.000 (0.000; [0, 0]) | 0.000 | 0.0% | — | 78.700 (0.483; [78.354, 79.046]) | 80.000 | -1.62% | 19.675 | 20.0 |
| C | 250 | b2 | 10 | 250.01 | 10.800 (0.919; [10.143, 11.457]) | 10.251 | +5.36% | 43.198 | 0.000 (0.000; [0, 0]) | 0 | — | 0.000 | 26.0 |
| C | 250 | b3 | 10 | 250.01 | 0.000 (0.000; [0, 0]) | 0.000 | 0.0% | — | 6.000 (0.000; [6.000, 6.000]) | 6.500 | -7.69% | 23.999 | 26.0 |
| C | 1000 | b2 | 10 | 999.98 | 42.000 (2.582; [40.153, 43.847]) | 40.999 | +2.44% | 42.001 | 0.000 (0.000; [0, 0]) | 0 | — | 0.000 | 26.0 |
| C | 1000 | b3 | 10 | 1000.05 | 0.000 (0.000; [0, 0]) | 0.000 | 0.0% | — | 25.000 (0.000; [25.000, 25.000]) | 26.001 | -3.85% | 24.999 | 26.0 |
| C | 4000 | b2 | 10 | 3999.98 | 172.200 (12.856; [163.004, 181.396]) | 163.999 | +5.00% | 43.050 | 3.200 (9.773; [-3.791, 10.191]) | 0 | — | 0.800 | 26.0 |
| C | 4000 | b3 | 10 | 4000.00 | 0.000 (0.000; [0, 0]) | 0.000 | 0.0% | — | 106.200 (11.183; [98.200, 114.200]) | 104.000 | +2.12% | 26.550 | 26.0 |

*(Note: Under relaxed `b2` at $4000\text{ pkt/s}$, isolated out-of-order arrivals also occurred during rule replacement in pairs~A (`2.800`) and~C (`3.200`).)*

---

### E13 — False Confirmations Under Normal Jitter (Configured $J=6\text{ ms}$, 40 main runs + 1 calibration run)
Calibration run `experiments/results/redfill_2026-11/E13/calibration/redfill_e13_cal_j6_naive_j6_20261119082603_01.csv` verified $J=6\text{ ms}$ (`q1_raw_gt22 = 0.076667`, within $[0.02, 0.10]$; recorded in `chosen_jitter_ms.txt`). Since naive uses $h=0$, its breach threshold is $\theta = 20\text{ ms}$ ($q_1 = q_{1,\text{raw}>20}$), whereas damped configurations use $\theta(1+h) = 22\text{ ms}$. Episode rate is predicted as $q(1-q)$ for $k=1$ (`naive` with $q=q_1$ at $20\text{ ms}$, and `k1` with $q=q_\alpha$ at $22\text{ ms}$) and $q_\alpha^k$ for $k=2,3$ (`k2`, `k3`), with rule-of-three 95% upper bound $3/W$ where 0 confirmations occur. Source CSVs: `experiments/results/redfill_2026-11/E13/model_comparison.csv`, `E13/summary.csv`.

| Config | Configured $(k,\alpha,h)$ | $n$ | Total Conf. / Total Win. | Measured Conf. Mean (SD) | Measured Rate Mean [95% CI] | Measured Raw $q_1$ / EWMA $q_\alpha$ | Predicted Episode Rate | % Err vs Pred. | Rule-of-Three 95% Upper |
|---|---|---:|---|---:|---|---|---|---|---|
| `naive` | $k=1, \alpha=1.0, h=0$ ($\theta=20\text{ ms}$) | 10 | 768 / 6000 | 76.800 (12.200) | 0.128000 [0.113455, 0.142545] | $q_{1,\text{gt20}} = 0.147167$ | 0.125509 | +1.99% | — |
| `k1` | $k=1, \alpha=0.3, h=0.1$ ($\theta_b=22\text{ ms}$) | 10 | 11 / 6000 | 1.100 (1.101) | 0.001833 [0.000521, 0.003145] | $q_\alpha = 0.002167$ ($q_{1,\text{gt22}} = 0.096333$) | 0.002162 | **-15.20%** | — |
| `k2` | $k=2, \alpha=0.3, h=0.1$ ($\theta_b=22\text{ ms}$) | 10 | 0 / 5990 | 0.000 (0.000) | 0.000000 [0.000000, 0.000000] | $q_\alpha = 0.001333$ ($q_{1,\text{gt22}} = 0.088000$) | 0.000002 | — | 0.000501 |
| `k3` | $k=3, \alpha=0.3, h=0.1$ ($\theta_b=22\text{ ms}$) | 10 | 0 / 5980 | 0.000 (0.000) | 0.000000 [0.000000, 0.000000] | $q_\alpha = 0.000333$ ($q_{1,\text{gt22}} = 0.075000$) | 0.000000 | — | 0.000502 |

---

### E14 — Contention-Safe Recovery (Proposition 6: `cf25af2` old vs. `main` `75f2d2e` new, $n=10 \times 4 = 40$ runs per build)

Because production `select_best()` (`src/pathing/prune.py`, Eq.~4) ranks candidates lexicographically by `(-bottleneck_residual_mbps, total_delay)`, sequential admission of $N$ intents summing to $80\text{ Mbit/s}$ places most intents on north (`s1-s2-s3-s7`) until north's residual falls below $50\text{ Mbit/s}$, then spills $1$--$3$ intents onto middle (`s1-s4-s5-s7`) and (at $N=12$) $1$ onto south (`s1-s6-s7`). Each `(build, N, seed)` therefore measured **two distinct passes** on fresh SQLite DBs (`experiments/e14_contention.py`):
1. **"all-intents fault" pass:** Every one of the $N$ active intents receives an `SLA_VIOLATED` event in seeded random order.
2. **"north-fault" pass:** Only intents whose initial admitted path is north (`s1-s2-s3-s7`) receive `SLA_VIOLATED` (modeling a single physical link fault on `s1-eth2` while middle/south intents remain undisturbed).

Source CSV: `experiments/results/redfill_2026-11/E14/summary.csv`.

| Build | $N$ (Floor $80/N$) | Initial Routes (N/M/S) | All-Intents Fault Overcommitted Links Mean [CI] | All-Intents Max Res/Cap Mean [CI] | All-Intents Mid Reserved (Mbps) | North-Fault Overcommitted Links Mean [CI] | North-Fault Max Res/Cap Mean [CI] | North-Fault Mid Reserved (Mbps) |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `old` (`cf25af2`) | 4 (20 Mbps) | 3 / 1 / 0 | **3.000** [3.000, 3.000] | 1.200 [1.200, 1.200] | 60.000 | **3.000** [3.000, 3.000] | 1.600 [1.600, 1.600] | 80.000 |
| `old` (`cf25af2`) | 8 (10 Mbps) | 7 / 1 / 0 | **3.000** [3.000, 3.000] | 1.400 [1.400, 1.400] | 70.000 | **3.000** [3.000, 3.000] | 1.600 [1.600, 1.600] | 80.000 |
| `old` (`cf25af2`) | 12 (6.67 Mbps) | 9 / 2 / 1 | **3.000** [3.000, 3.000] | 1.200 [1.200, 1.200] | 60.000 | **3.000** [3.000, 3.000] | 1.467 [1.467, 1.467] | 73.333 |
| `old` (`cf25af2`) | 16 (5 Mbps) | 13 / 3 / 0 | **3.000** [3.000, 3.000] | 1.300 [1.300, 1.300] | 65.000 | **3.000** [3.000, 3.000] | 1.600 [1.600, 1.600] | 80.000 |
| `new` (`75f2d2e`) | 4 (20 Mbps) | 3 / 1 / 0 | **0.000** [0.000, 0.000] | 0.820 [0.775, 0.865] | 38.000 | **0.000** [0.000, 0.000] | 1.000 [1.000, 1.000] | 40.000 |
| `new` (`75f2d2e`) | 8 (10 Mbps) | 7 / 1 / 0 | **0.000** [0.000, 0.000] | 0.840 [0.780, 0.900] | 42.000 | **0.000** [0.000, 0.000] | 1.000 [1.000, 1.000] | 50.000 |
| `new` (`75f2d2e`) | 12 (6.67 Mbps) | 9 / 2 / 1 | **0.000** [0.000, 0.000] | 0.693 [0.653, 0.734] | 34.667 | **0.000** [0.000, 0.000] | 0.933 [0.933, 0.933] | 46.667 |
| `new` (`75f2d2e`) | 16 (5 Mbps) | 13 / 3 / 0 | **0.000** [0.000, 0.000] | 0.800 [0.800, 0.800] | 40.000 | **0.000** [0.000, 0.000] | 0.900 [0.900, 0.900] | 45.000 |

- **E14b (Secondary Live Mininet Check) — `NOT RUN` (2 failed attempts) & Important Infrastructure Finding:**
  > **FINDING (`src/enforcement/queues.py`):** When an intent specifies `min_bandwidth_mbps > 0`, `src/enforcement/queues.py` attaches an Open vSwitch `linux-htb` QoS record (`ovs-vsctl set port <port> qos=...`) to each traversed egress port, replacing Mininet's root `tc` qdisc hierarchy (`netem`). Consequently, that egress port loses its emulated `netem` link delay (which is why E14b failed twice with `FAIL: no netem parent on s1-eth2` and `FAIL: no netem parent on s1-eth2 or s2-eth1` after `POST /intent` with `min_bandwidth_mbps: 20`). Among the published experiments, **only O3** used a bandwidth intent (`min_bandwidth_mbps: 20`, no emulated link-delay threshold fault); all published and new latency experiments (**E1–E4**, **E6**, **E9–E13**, **E15**) used latency-only intents (`B_min` unset) and are completely unaffected. `src/` was left untouched.

---

### E15 — One-Way Delay vs. `RTT/2` (Shared Kernel Clock, $n=10 \times 6 = 60$ runs)
*Methodology note:* Measured via a TWAMP-Light-style shared-clock UDP probe (`scripts/owd_probe.py`), valid only because Mininet host namespaces share a single Linux kernel clock (`time.time_ns()`), **NOT** an RFC 5357 TWAMP implementation. Run `redfill_e15_middle_healthy_20261119133024_07.csv` (which recorded `rtt_ms = 98738.36` due to a stale pre-pause packet across the ~10:45–13:30 UTC host pause) was preserved in `E15/excluded/`, `scripts/owd_probe.py` was hardened with a 64-bit per-run `session_id` + sent `(seq, t1_ns)` matching, 1 replacement `middle/healthy` run was executed, and all 60 active raw files pass `rtt_ms <= 1000 ms`. Source CSVs: `experiments/results/redfill_2026-11/E15/model_comparison.csv`, `E15/summary.csv`.

| Route | Condition | $n$ | Configured Planned OWD (ms) | Measured Fwd OWD Mean (SD; 95% CI) | Measured RTT Mean (SD; 95% CI) | Measured $\text{RTT}/2$ (ms) | Err of $\text{RTT}/2$ vs Fwd OWD | Fwd OWD vs Planned | Measured OWD $\le 35\text{ ms}$ |
|---|---|---:|---:|---|---|---:|---:|---:|---:|
| `north` | `healthy` | 10 | 6.0 | 6.696 (0.086; [6.634, 6.758]) | 13.353 (0.121; [13.267, 13.440]) | 6.677 | -0.019 ms | +0.696 ms (**+11.6%**) | 1.00 |
| `middle` | `healthy` | 10 | 15.0 | 15.824 (0.254; [15.642, 16.006]) | 31.626 (0.515; [31.257, 31.995]) | 15.813 | -0.011 ms | +0.824 ms (+5.5%) | 1.00 |
| `south` | `healthy` | 10 | 24.0 | 24.943 (0.119; [24.858, 25.028]) | 49.854 (0.213; [49.701, 50.006]) | 24.927 | -0.016 ms | +0.943 ms (+3.9%) | 1.00 |
| `north` | `fault` | 10 | 44.0 | 44.924 (0.176; [44.798, 45.050]) | 51.808 (0.348; [51.560, 52.057]) | 25.904 | **-19.020 ms (-42.3%)** | +0.924 ms (+2.1%) | **0.00** (note $\text{RTT}/2=25.9 \le 35$) |
| `middle` | `fault` | 10 | 50.0 | 51.068 (0.159; [50.955, 51.182]) | 67.114 (0.277; [66.916, 67.312]) | 33.557 | **-17.511 ms (-34.3%)** | +1.068 ms (+2.1%) | **0.00** (note $\text{RTT}/2=33.6 \le 35$) |
| `south` | `fault` | 10 | 52.0 | 52.962 (0.113; [52.882, 53.043]) | 77.872 (0.156; [77.760, 77.984]) | 38.936 | **-14.026 ms (-26.5%)** | +0.962 ms (+1.9%) | **0.00** |

---

### E16 — Larger Topology Scaling (Geant2012 vs. Team16 7-Switch, 140 control-plane runs)
- **Topology provenance:** Direct `http://www.topology-zoo.org/files/Geant2012.graphml` download failed (`curl: (56) Recv failure: Connection reset by peer`, logged in `FAILURES.md`); the archived `Geant2012.graphml` was retrieved into `experiments/results/redfill_2026-11/E16/Geant2012.graphml` from `https://raw.githubusercontent.com/prateekshyap/CPP-in-SDN/master/Geant2012.graphml` (SHA-256 `8487b2fb091d53f1317035162df0d8ef436c9e1d10727e26865b0ecd89d4786e`).
- **Configured topology properties:** Team16 7-switch = `7` nodes, `8` undirected links. Geant2012 = `40` nodes, `61` simple undirected links, `bw_mbps = 100.0` (configured assumption), `delay_ms = max(0.05, dist_km * 0.005)` (`0.05 ms` minimum link-delay floor applied in `experiments/e16_topology_zoo.py` line 63 for short hops), with `3` edges missing coordinates using the configured `1.0 ms` fallback (`fallback_1ms_edges=3`).
- **Hardware / P4 disclosure:** No hardware or P4 switch was available; TCAM usage was **NOT RUN** (not measured). Reported rule counts are from the software model only.
- Source CSVs: `experiments/results/redfill_2026-11/E16/model_comparison.csv`, `E16/summary.csv`.

| Topology | Active $k$ | $n$ | Measured Admission Latency Mean (ms) | SD (ms) | Measured 95% CI (ms) | Max Rules/Switch Mean (SD) | Max Observed Rules/Switch | Max Strict ($2\times$) Overlap | Total Rules Mean |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| `team16_7sw` (7 nodes, 8 links) | 1 | 10 | 0.944 | 0.230 | [0.780, 1.108] | 2.00 (0.00) | 2 | 4 | 5.60 |
| `team16_7sw` | 2 | 10 | 2.660 | 1.974 | [1.248, 4.072] | 3.80 (0.63) | 4 | 8 | 11.40 |
| `team16_7sw` | 4 | 10 | 3.728 | 2.382 | [2.024, 5.432] | 5.60 (0.84) | 6 | 12 | 23.20 |
| `team16_7sw` | 8 | 10 | 1.303 | 0.151 | [1.195, 1.412] | 11.40 (1.90) | 14 | 28 | 50.60 |
| `team16_7sw` | 16 | 10 | 1.822 | 0.144 | [1.719, 1.925] | 19.20 (1.93) | 24 | 48 | 96.80 |
| `team16_7sw` | 32 | 10 | 3.627 | 0.840 | [3.026, 4.227] | 38.80 (4.24) | 44 | 88 | 192.40 |
| `team16_7sw` | 64 | 10 | 7.324 | 1.906 | [5.961, 8.687] | 80.80 (4.73) | 90 | 180 | 397.00 |
| `geant2012` (40 nodes, 61 links) | 1 | 10 | 3.783 | 1.466 | [2.734, 4.831] | 2.00 (0.00) | 2 | 4 | 9.00 |
| `geant2012` | 2 | 10 | 4.798 | 1.011 | [4.075, 5.521] | 3.00 (1.05) | 4 | 8 | 20.40 |
| `geant2012` | 4 | 10 | 5.070 | 2.205 | [3.493, 6.647] | 5.40 (1.65) | 8 | 16 | 40.40 |
| `geant2012` | 8 | 10 | 4.299 | 2.076 | [2.814, 5.784] | 9.60 (1.58) | 12 | 24 | 80.60 |
| `geant2012` | 16 | 10 | 5.502 | 1.946 | [4.111, 6.894] | 16.60 (3.13) | 24 | 48 | 158.20 |
| `geant2012` | 32 | 10 | 6.258 | 1.062 | [5.498, 7.017] | 32.20 (3.71) | 40 | 80 | 311.80 |
| `geant2012` | 64 | 10 | 11.061 | 3.215 | [8.761, 13.361] | 64.20 (7.33) | 76 | 152 | 625.40 |

---

## Section D — Figures Generated (`PNG` + `PDF`)

1. **E10 detection delay sweep:**
   - `experiments/results/redfill_2026-11/E10/fig_e10_detection_sweep.png`
   - `experiments/results/redfill_2026-11/E10/fig_e10_detection_sweep.pdf`
2. **E11 dwell timer sweep:**
   - `experiments/results/redfill_2026-11/E11/fig_e11_dwell_sweep.png`
   - `experiments/results/redfill_2026-11/E11/fig_e11_dwell_sweep.pdf`
3. **E12 rate and path-pair sweep:**
   - `experiments/results/redfill_2026-11/E12/fig_e12_rate_pair_sweep.png`
   - `experiments/results/redfill_2026-11/E12/fig_e12_rate_pair_sweep.pdf`
4. **E13 false confirmations vs. confirmation count $k$:**
   - `experiments/results/redfill_2026-11/E13/fig_e13_false_confirmations.png`
   - `experiments/results/redfill_2026-11/E13/fig_e13_false_confirmations.pdf`

---

## Section E — Partial / Not-Run Items, Failures, and Scenario Script Compatibility Proofs

### 1. Not-Run or Partial Items & Limitations
- **`J1` (`[Corresponding author and funding acknowledgement, if any.]`):** Marked `TEAM DECISION REQUIRED` with default funding text `"This work received no external funding."` and author selection left to the team.
- **`J2` (`[citation once accepted]`):** Left as-is until the conference paper is accepted.
- **`E14b` (Secondary live Mininet contention check):** `NOT RUN` after 2 failed attempts (logged below). Primary Proposition~6 evidence is the 80-run control-plane experiment `E14a` (`experiments/e14_contention.py`). As noted in Section C (`E14`), this uncovered a genuine infrastructure finding in `src/enforcement/queues.py` (`ovs-vsctl set port ... qos=...` replaces Mininet's `netem` qdisc when `min_bandwidth_mbps > 0`), leaving `src/` untouched.
- **`E16` Hardware / P4 TCAM & `www.topology-zoo.org` direct download:** No hardware or P4 switch was available, so TCAM usage is `NOT RUN` (rule counts are from the software model only). Direct `http://www.topology-zoo.org/files/Geant2012.graphml` reset the connection, so the archived Topology Zoo `Geant2012.graphml` (`40` nodes, `61` links, SHA-256 `8487b2fb091d53f1317035162df0d8ef436c9e1d10727e26865b0ecd89d4786e`) was fetched from `prateekshyap/CPP-in-SDN`, with configured `bw_mbps = 100.0`, `delay_ms = max(0.05, dist_km * 0.005)` (`0.05 ms` floor in `experiments/e16_topology_zoo.py` line~63), and `3` `fallback_1ms_edges`.
- **E10 live-violation collection flag (`TEAM16_WAIT_FOR_LIVE_VIOLATION`):** After E9 finished (`2026-11-18 16:08:33 UTC`), `experiments/scenarios/s1_single_intent.sh` was temporarily edited (`2026-11-18 16:08:51`–`16:09:12 UTC`) to bypass the synthetic SQLite injection helper so all 150 runs of E10 confirmed every breach from real telemetry at $(k, \Delta t)$. Subsequently, `s1_single_intent.sh` was guarded with `TEAM16_WAIT_FOR_LIVE_VIOLATION` defaulting to `0` (`smoke2` verified unchanged default behavior).
- **E11 `d20` filename indexing on resume:** After the host shutdown during `d20` run 2, the remaining 9 runs restarted filename suffixes at `_01` (distinct timestamps) alongside pre-shutdown `_01`, totaling $n=10$ valid 600 s runs.
- **E15 shared-clock caveat & replaced run:** `scripts/owd_probe.py` is TWAMP-Light-style shared-clock measurement valid only across same-kernel Mininet namespaces (not RFC 5357 TWAMP). Defective run `redfill_e15_middle_healthy_20261119133024_07.csv` (`rtt_ms = 98738.36 ms`) was excluded to `E15/excluded/` and replaced.

### 2. All Logged Failures (`experiments/results/redfill_2026-11/FAILURES.md`)
1. `2026-11-19 ~02:20-02:30 UTC`: Host laptop shut down during E11 `d20` run 2; run lost with no CSV written; resumed cleanly with 9 further `d20` runs and 10 `d30` runs.
2. `2026-11-19 ~10:30 UTC`: E14 Step 7b attempt 1 (`e14_live_check.sh` on `new` and `old`) failed with `FAIL: no netem parent on s1-eth2`; ran `mn -c`; added `s2-eth1` fallback matching `scripts/inject_fault.sh` and `--samples 8`.
3. `2026-11-19 ~10:32 UTC`: E14 Step 7b attempt 2 failed with `FAIL: no netem parent on s1-eth2 or s2-eth1` because bidirectional rule installation replaces root qdiscs on both sides of `s1-s2` with OVS `linux-htb` QoS once `min_bandwidth_mbps: 20` is admitted; ran `mn -c`; marked Step 7b `NOT RUN` (max 2 attempts) keeping E14a as primary evidence.
4. `2026-11-19 ~10:45-13:30 UTC`: Host laptop paused (~9,880 s gap) during E15 `middle/healthy`; run `redfill_e15_middle_healthy_20261119133024_07.csv` recorded `rtt_ms = 98738.357510 ms` from a stale pre-pause reply. Moved CSV to `E15/excluded/`, added 64-bit `session_id` + sent `(seq, t1_ns)` checks and `> 1000 ms` rejection to `scripts/owd_probe.py` and `summarize_e15()`, and ran 1 replacement `middle/healthy` run.
5. `2026-11-20 11:05:35 +05:30`: Direct download `http://www.topology-zoo.org/files/Geant2012.graphml` failed (`curl: (56) Recv failure: Connection reset by peer`); fell back to archived mirror `https://raw.githubusercontent.com/prateekshyap/CPP-in-SDN/master/Geant2012.graphml`.

### 3. Edited Scenario Scripts & Default-Behavior Verification
Three existing scenario scripts were edited strictly to add environment-variable overrides whose unset defaults reproduce baseline behavior:
1. `experiments/scenarios/s1_single_intent.sh`: Added `TEAM16_DETECTOR_K` (unset default: none), `TEAM16_TELEMETRY_SAMPLES` (default `5`), `TEAM16_PROBE_INTERVAL_S` (default `1`), and `TEAM16_WAIT_FOR_LIVE_VIOLATION` (default `0`, running the synthetic SQLite injection path just as before).
2. `experiments/scenarios/e6_oscillation.sh`: Added `TEAM16_E6_DWELL_S` (default `10`).
3. `experiments/scenarios/e4_packet_loss.sh`: Added `E4_RATE` (default `1000`), `E4_INTENT_FILE` (default per mode fixture), `E4_FAULT_DEV` (default `s1-eth2`), `E4_EXPECTED_INITIAL` (default `s1,s2,s3,s7`), and `E4_EXPECTED_ALT` (default `s1,s4,s5,s7`).

**Verification proofs (all checks pass with defaults):**
- Container `pytest tests -q`: **`326 passed, 11 skipped, 3 warnings`** (337 tests collected; 11 API TestClient tests skipped in container where pinned Starlette lacks a compatible `httpx` version; verified before edits in `BASELINE.txt`, after scenario edits in `RULE5_SMOKE2_PYTEST.txt`, and again after all experiments in Step 10).
- Default B3 smoke runs with all overrides unset:
  - `SMOKE/raw/redfill_smoke_b3_20261118161621.csv`: `detection_latency = 2095.763 ms`, `recovery_latency = 643.575 ms`, `reroute_count = 1.0`.
  - `SMOKE/raw/redfill_smoke2_b3_20261119034811.csv` (post-`TEAM16_WAIT_FOR_LIVE_VIOLATION` guard): `detection_latency = 2102.684 ms`, `recovery_latency = 547.159 ms`, `reroute_count = 1.0`.
- `python3.9 experiments/verify_summaries.py`: `summary verification passed: raw CSVs, summaries, and public result claims agree`.
- `python3.9 experiments/artifact_manifest.py verify`: `manifest verification passed: 355 artifacts (LF-canonical text; verbatim binaries)`.

---

## Section F — Email Draft to Dr. Navin Kumar

To: Dr. Navin Kumar
Cc: Srikanth Dinesh, Dheepak K
Subject: Team 16 - data for the red items in both drafts

Dear Dr. Navin Kumar,

Please find attached the summary report covering all measured data for the red items in both the conference and extended journal drafts, measured on the current main build (commit 75f2d2e on github.com/platynom/intent-sdn-sla) in our Docker/Mininet testbed.
Same-build reruns (E9) supply the updated Table I and Table 2 B2, matched-B2, and B3 latencies alongside O3 bound and unbound throughput and loss, while code inspection plus E12 confirm the 29 ms nominal delay difference (28 ms measured at 1000 pkt/s).
E10 verifies the linear detection-delay law across 15 settings, E11 confirms the Eq. (10) dwell bound across 50 runs under B3's effective 60 confirmable transitions per 600 s, and E12 validates loss and reordering across all three path pairs up to 4000 pkt/s.
E13 confirms EWMA plus k >= 2 hysteresis cuts synthetic false confirmations from 76.8/run to zero across 5990 windows, and E14 shows zero over-committed links under concurrent control-plane recovery on 75f2d2e versus all 3 middle-path links over-committed on cf25af2.
E15 exposes up to 19.02 ms asymmetric underestimation by RTT/2 against shared-clock one-way delay; live multi-intent E14b did not run because OVS HTB replaces root netem, and E16 software-modeled Geant2012 scaling to 64 intents since no hardware/P4 switch was available for TCAM measurement.
Please let us know if you would like any additional runs or clarifications for either manuscript.

Sincerely,
Tanmaya Kumar, Srikanth Dinesh and Dheepak K (Team 16)
