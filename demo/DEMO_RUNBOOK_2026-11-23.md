# Team 16 final review demo - runbook (23 Nov 2026)

## Before the review (15 min early)
1. Laptop on charger, sleep off, Wi-Fi not needed.
2. Open a WSL terminal: `wsl -d Ubuntu-22.04`, then
   `cd "/mnt/c/Users/Admin/Documents/Software Defined Networks/intent-sdn-sla"`
3. `docker compose up -d` and `docker compose ps` (sdn, intent-api, dashboard running).
4. Open http://localhost:8080 in the browser and keep it in a second window.
5. Optional warm-up: `bash demo/final_demo.sh --auto` (about 4 min) and check it ends
   with "Failed steps: 0".

## During the review
Run `bash demo/final_demo.sh`. It pauses before each act and prints a SAY line.

| Act | What it shows | About |
|---|---|---|
| 0 | Stack is up | 0.5 min |
| 1 | Dashboard with four seeded intents | 1 min |
| 2 | API: 422 invalid, 201 accepted, 409 duplicate, 204 withdrawn | 1.5 min |
| 3 | Deterministic planning and refusal | 1 min |
| 4 | Live fault, confirmed violation, two-phase reroute, audit trail | 2 min |
| 5 | Preemption and two-phase update | 2 min |
| 6 | E4, E6, E10, E11 figures; results check | 1.5 min |
| 7 | GitHub link | 0.5 min |

## If something fails live
- Mininet stuck: `docker compose exec -T sdn mn -c`, then rerun that act's command.
- Docker not working: open `demo/transcripts/final_demo_20261122T141952Z.txt` (passing rehearsal) and
  the figures. Say: "This is the recorded output of our rehearsal run; the live
  engine is unavailable right now."
