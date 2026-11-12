# Environment & Configuration Setup (`SETUP.md`)

## 1. Runtime Architecture

The project runs inside an Ubuntu 22.04 container (`team16/intent-sdn-sla:dev`) hosting Open vSwitch, Mininet, Ryu (Python 3.9), FastAPI/Uvicorn, and SQLite (WAL mode).

Start the container from WSL (`Ubuntu-22.04`):

```bash
docker compose up -d
```

Run unit and regression tests on the host or inside the container:

```bash
pytest tests -q
```

Verify experimental summaries and artifact integrity:

```bash
python experiments/verify_summaries.py
python experiments/artifact_manifest.py verify
```

---

## 2. Environment Variables

The controller, API, and telemetry processes support the following configuration environment variables:

| Environment variable | Default | Read in | Effect |
|---|---|---|---|
| `TEAM16_DB_PATH` | `experiments/results/state.db` | `src/common/db.py` | Path of the SQLite state database shared by the API, controller, telemetry and dashboard. Point it at a scratch file for isolated runs. |
| `TEAM16_API_TOKENS` | unset (access control off) | `src/intent_manager/api.py` | `tenant=token` pairs separated by commas or semicolons, e.g. `hospital-a=tok-1,factory-b=tok-2`. When set, creating and withdrawing intents requires `Authorization: Bearer <token>`; a missing or unknown token returns 401 and acting on another tenant's intent returns 403. Never commit a real token. |
| `TEAM16_DEGRADE_FACTOR` | `0.5` | `src/telemetry/loop.py`, `src/common/db.py` | Fraction of `min_bandwidth_mbps` kept when an intent with `on_violation: degrade` is degraded. |
| `TEAM16_RETENTION_MAX_ROWS` (alias `TEAM16_RETENTION_ROWS`) | unset (no pruning) | `src/common/db.py` | When set, `prune_retention()` keeps at most this many newest rows in `measurements` and `events`. |
| `TEAM16_RETENTION_SECONDS` | unset (no pruning) | `src/common/db.py` | When set, `prune_retention()` deletes `measurements` and `events` rows older than this many seconds. |
| `TEAM16_TABLE_MISS_METER` | `1` | `src/enforcement/controller.py` | Binds the table-miss rule to OpenFlow meter 1 (drop band, 50 packets/s, burst 10) when the switch supports meters. Any other value leaves packet-in unmetered. |
| `TEAM16_BARRIER_TIMEOUT_S` | `2.0` | `src/enforcement/controller.py` | Seconds to wait for each barrier reply during a two-phase update before failing closed. |
| `TEAM16_EXPERIMENT_MODE` | unset | `src/intent_manager/api.py` | `b2` selects the B2 ablation: reservation, conflict and match-overlap checks are bypassed. Experiments only. |
| `TEAM16_DISABLE_SET_QUEUE` | unset | `src/enforcement/flowmod.py` | `1` omits the `SET_QUEUE` action (the O3 unbound control). Experiments only. |

The request body limit for `POST /intent` is fixed at 64 KiB (HTTP 413 beyond it) and is not configurable.
