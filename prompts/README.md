# Implementation briefs

One brief per subtask. Each is a self-contained prompt you can paste into Gemini,
ChatGPT or any coding model with **no other context**, and get back code that either
passes our tests or visibly fails them.

## How this works

| Written by | What |
|---|---|
| **Us (spec side)** | JSON Schemas, interface contracts, the topology spec, and **all acceptance tests** |
| **The model** | The implementation that makes those tests pass |

The tests are the contract. You never have to read the generated code line by line to
know whether it is right — you run `pytest` and it tells you.

## The loop

1. Open the brief for the subtask, e.g. `ST-02_topology.md`.
2. Paste the **whole file** into the model. Do not summarise it; the constraints
   sections are what stop the model inventing its own architecture.
3. Save what comes back to the file paths the brief names.
4. Run the acceptance command printed at the bottom of the brief.
5. If it fails, paste the failure output back to the model verbatim and say
   "this test fails, fix the implementation, do not change the test."
6. When green, commit on a `feat/st-NN-...` branch and open a pull request.

**Rule 6 matters most.** Models faced with a failing test will often edit the test.
The tests encode the project plan. If a test looks wrong, that is a conversation for
the team, recorded in `docs/decisions.md` — not a silent edit.

## Ground rules that apply to every brief

These are repeated inside each brief so they survive being pasted alone:

- **Python 3.9.** Ryu 4.34 requires it. No `match` statements, no `X | Y` unions at
  runtime (`from __future__ import annotations` is already used everywhere, so
  annotations are fine).
- **Pinned dependencies only.** Whatever is in `requirements.txt`. If the model wants
  a new library, that is a decision for the team, not an import.
- **The intent grammar is frozen.** Five constraint types, three violation actions,
  priority 1–5. See `src/intent_manager/schema.json` and ADR-002. Never widen it.
- **`topology/topology_spec.py` is the single source of truth for the network.**
  Never hard-code an edge, a bandwidth or a delay anywhere else.
- **Anything touching Mininet, Open vSwitch or Ryu runs only inside the container.**
- **No new architecture.** Six modules, M1–M6, as described in the README. A brief
  that asks for M3 gets M3, not a refactor of M1.

## Status

| Brief | Subtask | Dates | State |
|---|---|---|---|
| `ST-02_topology.md` | Topology, B0 baseline, flow-table pilot | 14–20 Aug | ready |
| ST-03 | Interfaces frozen | 21–27 Aug | to write |
| ST-04 | M1 + M3 first light | 28 Aug–3 Sep | to write |
| ST-05 | M4 direct install | 4–10 Sep | to write |
| ST-06 | M5 telemetry | 11–17 Sep | to write |
| ST-07 | Close the control loop | 18–24 Sep | to write |
| ST-08 | M2 admission | 25 Sep–1 Oct | to write |
| ST-09 | Preemption + hysteresis | 2–8 Oct | to write |
| ST-10 | Two-phase update | 9–15 Oct | to write |
| ST-11 | Dashboard + audit log | 16–22 Oct | to write |
| ST-12 | Evaluation run 1 | 23–29 Oct | to write |
| ST-13 | Evaluation run 2 + figures | 30 Oct–5 Nov | to write |
| ST-14 | Report, demo, buffer | 6–12 Nov | to write |
