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

| Environment Variable | Default | Module | Description |
|---|---|---|---|
| `TEAM16_DB_PATH` | `state.db` | `src/common/db.py` | Path to the SQLite state database shared by M1–M6. Set to a scratch path (e.g. `/tmp/live_demo.db`) for isolated live runs so historical `state.db` is untouched. |
| `TEAM16_API_TOKENS` | *(unset / empty)* | `src/intent_manager/api.py` | Comma-separated list of bearer tokens (or `tenant:token` pairs, e.g. `hospital-a:tok-1,factory-b:tok-2`). When unset or empty, authentication is disabled so existing experiment scripts run unchanged. When set, mutating endpoints (`POST /intent`, `DELETE /intent/{id}`, `POST /profiles/{name}/instantiate`) require `Authorization: Bearer <token>`; missing/invalid tokens return `401 Unauthorized`, and tenant mismatches return `403 Forbidden`. |
| `TEAM16_MAX_BODY_BYTES` | `65536` (64 KiB) | `src/intent_manager/api.py` | Maximum HTTP request body size accepted by the API middleware before returning `413 Content Too Large`. |
| `TEAM16_DEGRADE_FACTOR` | `0.5` | `src/telemetry/loop.py`, `src/enforcement/controller.py` | Multiplier in `(0, 1]` applied to an intent's `min_bandwidth_mbps` HTB queue floor when `action_on_violation` is `DEGRADE` (or when `REROUTE_OR_DEGRADE` finds no feasible alternate path). |
| `TEAM16_RETENTION_MAX_ROWS` | `50000` | `src/common/db.py` | Maximum rows retained per high-volume telemetry table (`measurements`, `events`, `audit_log`) before `prune_old_records` trims the oldest entries. |
| `TEAM16_RETENTION_MAX_SECONDS` | `604800` (7 days) | `src/common/db.py` | Maximum age in seconds for rows in `measurements`, `events`, and `audit_log` when `prune_old_records` executes during telemetry collection. |
| `TEAM16_TABLE_MISS_METER` | `1` | `src/enforcement/controller.py` | Installs OpenFlow 1.3 meter 1 (`100 pktps` `DROP` band) on the priority-0 table-miss rule so unmatched packet floods cannot saturate the controller with `OFPPacketIn` messages. Set to `0` to install a direct drop-by-default table-miss rule on switches without meter support. |
| `TEAM16_ADMISSION_MODE` | `full` | `src/intent_manager/api.py` | Admission policy mode (`full` uses M2 residual-capacity + bidirectional tenant isolation + single-victim preemption; `b2_no_conflict` is used by the B2 ablation script). |
