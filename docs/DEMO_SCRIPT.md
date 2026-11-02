# Team 16 live demonstration

Allow approximately eight to ten minutes for the presentation after the image has built. Image download and compilation time is preparation time. Run only one Mininet scenario at a time. In Windows PowerShell, begin in the repository:

```powershell
cd 'C:\Users\Admin\Documents\Software Defined Networks\SDN'
```

On this machine Docker Engine runs inside WSL Ubuntu-22.04. Use the WSL commands below if Windows `docker` cannot reach an engine. Keep a separate WSL terminal open during the demo so the distribution stays active. If Docker Desktop is working instead, run the inner `docker compose` command directly from the repository. The Linux repository path below is the WSL mount of the same checkout.

## Preparation before presenting

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd '/mnt/c/Users/Admin/Documents/Software Defined Networks/SDN' && docker compose up --build -d"
wsl -d Ubuntu-22.04 -- bash -lc "cd '/mnt/c/Users/Admin/Documents/Software Defined Networks/SDN' && docker compose ps -a && docker compose logs --tail 16 seed-demo-intents"
```

Expected: the SDN, API, and dashboard services are running. The seed job can exit successfully after writing or finding the demo intents. A failed build or unavailable Docker engine is a stop condition for the live portion; use the recorded fallback below.

## Explain the dashboard and data labels

Open `http://localhost:8080`. If the WSL localhost forwarder is unavailable, the API can still be checked inside its container:

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd '/mnt/c/Users/Admin/Documents/Software Defined Networks/SDN' && docker compose exec -T dashboard curl -s http://localhost:8080/api/dashboard"
```

Select INT-010 through INT-013. Explain the application labels, priority, computed path, and audit entry. Point directly at the SIMULATED DEMO TELEMETRY notice. These illustrative values make the interface demonstrable before a collector is started; they are not evaluation results. A computed route is not proof of activation on OVS. Reserve about one minute for this distinction.

Show an actual API rejection without changing the network:

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd '/mnt/c/Users/Admin/Documents/Software Defined Networks/SDN' && docker compose exec -T intent-api curl -sS -i -X POST http://127.0.0.1:8000/intent -H 'Content-Type: text/plain' --data-binary @intents/invalid/bad_sixth_constraint.yaml"
```

Expected: HTTP 422 and a reason naming the unsupported guarantee field. The exact response is preserved in the final verification recordings.

## Show the baseline request and validation

```powershell
Get-Content intents/s1_urllc_baseline.yaml
python demo_st4.py
```

Explain: endpoints identify the traffic, guarantees state the desired service, and consistency selects the update procedure. The software demo shows acceptance, path planning, an infeasible request, and invalid grammar. Its path estimates are not live measurements. Run `python demo_st4.py` only if the host dependencies are installed; otherwise use `docker compose exec -T sdn python3.9 demo_st4.py` through the WSL wrapper. Reserve about two minutes.

## Show actual installation and queue binding

Use a new isolated database for the scenario so the dashboard seed job cannot change the experiment's reservations or qdiscs. This live run temporarily uses a separate store; the dashboard's simulated examples continue to use the regular demo store.

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd '/mnt/c/Users/Admin/Documents/Software Defined Networks/SDN' && sed 's/\r$//' experiments/scenarios/s1_single_intent.sh | docker compose exec -T -e TEAM16_DB_PATH=/tmp/team16-presentation-s1.db sdn bash -s"
```

Expected: HTTP 201, matching-cookie flow verification, HTB queue attachment, route verification, live samples, and persisted measurements. The script cleans up its network when it exits. To inspect the rules directly, run this command in a second PowerShell tab while the first tab is collecting telemetry:

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd '/mnt/c/Users/Admin/Documents/Software Defined Networks/SDN' && docker compose exec -T sdn ovs-ofctl -O OpenFlow13 dump-flows s1"
```

Point out the cookie, IPv4/UDP match, `set_queue:1`, and output port in the actual flow dump. If the script has already cleaned up, rerun the installation step before inspecting. Do not present an empty post-cleanup switch as a failed installation. Reserve about one minute.

## Inject delay and show closed-loop recovery

The B3 scenario automates the delay fault, collector, persisted violation, strict replacement, and post-update UDP check. It uses a latency-focused fixture to isolate recovery from bandwidth offered-load effects. Its result prefix keeps this presentation out of the published n=10 dataset.

```powershell
wsl -d Ubuntu-22.04 -- bash -lc "cd '/mnt/c/Users/Admin/Documents/Software Defined Networks/SDN' && sed 's/\r$//' experiments/scenarios/s1_single_intent.sh | docker compose exec -T -e TEAM16_DB_PATH=/tmp/team16-presentation-b3.db -e TEAM16_RESULT_TAG=regression_presentation_b3 sdn bash -s -- --b3"
wsl -d Ubuntu-22.04 -- bash -lc "cd '/mnt/c/Users/Admin/Documents/Software Defined Networks/SDN' && docker compose exec -T sdn cat /var/log/team16/telemetry.log"
wsl -d Ubuntu-22.04 -- bash -lc "cd '/mnt/c/Users/Admin/Documents/Software Defined Networks/SDN' && docker compose exec -T -e TEAM16_DB_PATH=/tmp/team16-presentation-b3.db sdn python3.9 scripts/show_demo_audit.py"
```

Expected: the injected primary-link delay is reported; live samples confirm `sla.violated`; Ryu installs the middle route; the post-reroute probe succeeds. The read-only audit command then shows the stored path revisions, recent events, and complete event counts from that scenario's isolated database. Numerical timings vary with the host. Explain that strict update costs include staging, synchronization, and draining. The log shows that the measurements are collected during execution; printing the log afterward is replaying that saved output. Reserve about two minutes.

## Show the evidence and limitations

```powershell
Start-Process experiments/figures/e4_packet_loss.png
Start-Process experiments/figures/e6_oscillation.png
python experiments/verify_summaries.py
```

Explain the zero-loss/reordering tradeoff in E4 and the damping tradeoff in E6 using the plotted labels and intervals. The verifier checks registered raw-derived summaries. Distinguish measured data, calculated intervals, simulated dashboard examples, and unresolved historical accounting. Reserve about one minute.

## Fallback when live Mininet fails

Use `docs/demo_assets/` for saved command output from the final verification, with the run date and revision recorded alongside it. Open the final E4/E6 figures and the saved smoke output. Say: “This is recorded output from the documented run; the live engine is unavailable today.” Do not draw a terminal screenshot or claim a recording is a fresh execution. If a recorded asset is absent, state that it is unavailable and show only the committed raw CSV and summary evidence.

If an API service is unavailable, `demo_st4.py` still demonstrates software validation and path computation when its dependencies are installed. That fallback does not demonstrate live rule installation. The presentation must retain that distinction.
