"""Print retained scenario paths and audit events without changing its database."""
import json
import os
import sqlite3
from pathlib import Path


def main():
    path = Path(os.environ["TEAM16_DB_PATH"]).resolve()
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        output = {"database": str(path), "mode": "read-only",
                  "paths": [dict(row) for row in conn.execute("SELECT * FROM paths ORDER BY id")],
                  "recent_events": [dict(row) for row in conn.execute(
                      "SELECT * FROM events ORDER BY at DESC LIMIT 20")],
                  "complete_event_counts": [dict(row) for row in conn.execute(
                      "SELECT intent_id, type, COUNT(*) AS count FROM events GROUP BY intent_id, type")]}
        print(json.dumps(output, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
