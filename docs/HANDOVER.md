# Project handover

## What this project does

An operator describes a network promise as a YAML intent: which traffic matters
and the bandwidth, latency, loss, isolation or link-avoidance requirement it must
meet. The system validates that request, decides whether it is feasible, computes
a suitable path, generates OpenFlow enforcement, measures the delivered service
and is intended to re-plan when a real SLA breach persists. It is a compact,
reproducible reference implementation for 5G-style service assurance, not a claim
of a novel networking algorithm.

## The six modules

| Module | Question it answers | Responsibility |
|---|---|---|
| M1 Intent Manager | What does the user want? | Validate and store machine-readable intents; expose the REST API. |
| M2 Admission and Conflict | Can we provide it? | Decide whether capacity exists and resolve competing requests. |
| M3 Path Computation | How can we provide it? | Compute and prune candidate paths, then choose deterministically. |
| M4 Enforcement | Can we make the network do it? | Generate OpenFlow 1.3 rules and OVS HTB queue commands. |
| M5 Telemetry and SLA Monitor | Is it actually working? | Collect measurements and distinguish persistent breaches from noise. |
| M6 Dashboard and Audit | What is happening, and why? | Present status and preserve the causal explanation of every action. |

## Current state

**Done: ST-1 through ST-6.** The software-only suite passes, and Scenario S1 has
been executed successfully inside the project container against Mininet, Open
vSwitch and Ryu. The live run installed the INT-001 OpenFlow rules and 20 Mbps HTB
queue, sent matching UDP traffic along `s1-s2-s3-s7`, collected five one-hertz
samples and persisted all five measurements. Run the acceptance commands below to
obtain the current test total rather than copying a stale count into reports.

**Next: ST-7, closing the control loop.** This is the single most important
remaining step: subscribe to confirmed M5 violation events, compute an alternative
path and safely ask M4 to install it. The implementation brief and acceptance tests
are in `prompts/ST-07_close_the_loop.md`.

## What is not true yet

1. The feedback loop is not closed, so traffic does not reroute automatically yet.
2. The dashboard is not implemented; it remains ST-11 work.
3. The live result is from containerized Mininet and Open vSwitch, not physical
   switching hardware.

## Acceptance commands

```bash
docker compose build
docker compose up -d
docker compose exec -T sdn pytest tests -q
docker compose exec -T sdn ruff check src tests topology experiments
docker compose exec -T sdn bash experiments/scenarios/s1_single_intent.sh
```

## Read these first

1. `SETUP.md` - install, verify and run the software-only workflow.
2. `docs/architecture.md` - topology, routes and why alternatives are mandatory.
3. `docs/decisions.md` - frozen design decisions and the ONOS fallback.
4. `prompts/` - bounded implementation briefs, beginning with ST-7.
