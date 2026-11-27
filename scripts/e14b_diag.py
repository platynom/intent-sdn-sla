"""Print what happened in the latest E14b live run: paths, delay samples, events."""
import glob
import json
import os
import sqlite3

dbs = sorted(glob.glob("/tmp/team16-e14live.*/state.db"), key=os.path.getmtime)
if not dbs:
    raise SystemExit("no E14b database found under /tmp/team16-e14live.*")
db = dbs[-1]
print("DB:", db)
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row
t0 = c.execute("SELECT MIN(at) FROM events").fetchone()[0] or 0

print("\n--- paths (all versions) ---")
for r in c.execute("SELECT intent_id, switches_json, est_latency_ms, version, computed_at, superseded_at "
                   "FROM paths ORDER BY intent_id, id"):
    sup = "current" if r["superseded_at"] is None else f"superseded +{r['superseded_at'] - t0:.1f}s"
    print(f"{r['intent_id']}  v{r['version']}  {'-'.join(json.loads(r['switches_json']))}  "
          f"est {r['est_latency_ms']:.1f} ms  +{r['computed_at'] - t0:.1f}s  {sup}")

print("\n--- delay samples per intent (ms) ---")
for (iid,) in c.execute("SELECT DISTINCT intent_id FROM measurements ORDER BY intent_id"):
    vals = [r[0] for r in c.execute("SELECT delay_ms FROM measurements WHERE intent_id=? ORDER BY at", (iid,))]
    print(iid, " ".join("-" if v is None else f"{v:.1f}" for v in vals))

print("\n--- events ---")
for r in c.execute("SELECT at, type, intent_id, message FROM events ORDER BY at"):
    print(f"+{r['at'] - t0:6.1f}s  {r['type']:22s} {r['intent_id'] or '':8s} {r['message'][:150]}")
