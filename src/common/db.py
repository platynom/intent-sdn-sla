"""
SQLite schema and access. FROZEN at ST-3.

One file, no server, committed alongside the raw CSV. That is the whole
reproducibility argument: a reviewer clones the repository and has both the
results and the state that produced them.

Concurrency note: M1's REST API, M5's collector and M6's dashboard all touch this
database from different threads. SQLite handles that with WAL mode and a busy
timeout, both set in `connect()`. Do not share a Connection between threads —
call `connect()` in each, or rely on check_same_thread=False for the FastAPI
case where a dependency-injected connection crosses the threadpool boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .events import Event, EventType, Severity
from .models import (
    Consistency,
    Guarantee,
    IntentRecord,
    IntentState,
    Match,
    OnViolation,
    PathPlan,
)

DEFAULT_DB_PATH = Path("experiments/results/state.db")

SCHEMA_VERSION = 1

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per intent ever submitted, including rejected ones. Rejected intents
-- are kept because "why was this refused" is a question the audit log must be
-- able to answer weeks later.
CREATE TABLE IF NOT EXISTS intents (
    id             TEXT PRIMARY KEY,
    tenant         TEXT    NOT NULL,
    priority       INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
    match_json     TEXT    NOT NULL,
    guarantee_json TEXT    NOT NULL,
    consistency    TEXT    NOT NULL,
    on_violation   TEXT    NOT NULL,
    dwell_seconds  INTEGER NOT NULL,
    state          TEXT    NOT NULL,
    created_at     REAL    NOT NULL,
    updated_at     REAL    NOT NULL,
    last_replan_at REAL
);

CREATE INDEX IF NOT EXISTS idx_intents_state    ON intents(state);
CREATE INDEX IF NOT EXISTS idx_intents_priority ON intents(priority);

-- Every path ever installed, not just the current one. Superseded rows are kept
-- so a reroute is visible as a pair of rows rather than an overwrite, which is
-- what makes metric E6 (reroute count) countable straight from the database.
CREATE TABLE IF NOT EXISTS paths (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id     TEXT    NOT NULL REFERENCES intents(id) ON DELETE CASCADE,
    switches_json TEXT    NOT NULL,
    links_json    TEXT    NOT NULL,
    est_latency_ms   REAL NOT NULL,
    bottleneck_mbps  REAL NOT NULL,
    version       INTEGER,
    computed_at   REAL    NOT NULL,
    superseded_at REAL
);

CREATE INDEX IF NOT EXISTS idx_paths_intent  ON paths(intent_id);
CREATE INDEX IF NOT EXISTS idx_paths_current ON paths(intent_id, superseded_at);

-- Raw telemetry. High volume: 1 Hz per active intent. Kept in the database
-- rather than only in CSV so the dashboard can draw a chart without parsing files.
CREATE TABLE IF NOT EXISTS measurements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id       TEXT NOT NULL REFERENCES intents(id) ON DELETE CASCADE,
    at              REAL NOT NULL,
    delay_ms        REAL,
    jitter_ms       REAL,
    loss_pct        REAL,
    throughput_mbps REAL
);

CREATE INDEX IF NOT EXISTS idx_measurements_intent_at ON measurements(intent_id, at);

-- The audit log. Append-only by convention; nothing in the codebase updates or
-- deletes a row here.
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    severity     TEXT NOT NULL,
    intent_id    TEXT,
    at           REAL NOT NULL,
    message      TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_at     ON events(at);
CREATE INDEX IF NOT EXISTS idx_events_intent ON events(intent_id, at);
CREATE INDEX IF NOT EXISTS idx_events_type   ON events(type);

CREATE TABLE IF NOT EXISTS intent_queues (
    intent_id  TEXT    NOT NULL,
    switch     TEXT    NOT NULL,
    port       TEXT    NOT NULL,
    queue_id   INTEGER NOT NULL,
    min_bps    INTEGER NOT NULL,
    max_bps    INTEGER NOT NULL,
    updated_at REAL    NOT NULL,
    PRIMARY KEY (intent_id, switch, port),
    UNIQUE (switch, port, queue_id)
);

CREATE INDEX IF NOT EXISTS idx_intent_queues_port ON intent_queues(switch, port);

CREATE TRIGGER IF NOT EXISTS trg_intents_delete_queues
AFTER DELETE ON intents
BEGIN
    DELETE FROM intent_queues WHERE intent_id = OLD.id;
END;

CREATE TABLE IF NOT EXISTS link_states (
    link       TEXT PRIMARY KEY,
    up         INTEGER NOT NULL,
    updated_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS degraded_rates (
    intent_id          TEXT PRIMARY KEY REFERENCES intents(id) ON DELETE CASCADE,
    original_min_mbps  REAL NOT NULL,
    effective_min_mbps REAL NOT NULL,
    updated_at         REAL NOT NULL
);
"""


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Open a connection with the settings the rest of the system assumes.

    WAL lets the dashboard read while the collector writes. The busy timeout
    stops a 1 Hz writer from raising "database is locked" the moment a human
    refreshes a page.
    """
    db_path = Path(path) if path is not None else Path(os.environ.get("TEAM16_DB_PATH", str(DEFAULT_DB_PATH)))
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False because FastAPI dispatches sync endpoints to a
    # threadpool: the connection is created on one thread and used on another.
    # WAL plus the busy timeout make concurrent access safe.
    conn = sqlite3.connect(str(db_path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema. Safe to call on an existing database."""
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'version'"
    ).fetchone()
    return int(row["value"]) if row else None


# --------------------------------------------------------------------------- #
# Intents
# --------------------------------------------------------------------------- #

def save_intent(conn: sqlite3.Connection, rec: IntentRecord) -> None:
    """Insert or update. The intent id is the primary key, so re-saving updates."""
    conn.execute(
        """
        INSERT INTO intents (id, tenant, priority, match_json, guarantee_json,
                             consistency, on_violation, dwell_seconds, state,
                             created_at, updated_at, last_replan_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            tenant=excluded.tenant,
            priority=excluded.priority,
            match_json=excluded.match_json,
            guarantee_json=excluded.guarantee_json,
            consistency=excluded.consistency,
            on_violation=excluded.on_violation,
            dwell_seconds=excluded.dwell_seconds,
            state=excluded.state,
            updated_at=excluded.updated_at,
            last_replan_at=excluded.last_replan_at
        """,
        (
            rec.id,
            rec.tenant,
            rec.priority,
            json.dumps(_match_to_dict(rec.match), sort_keys=True),
            json.dumps(_guarantee_to_dict(rec.guarantee), sort_keys=True),
            rec.consistency.value,
            rec.on_violation.value,
            rec.dwell_seconds,
            rec.state.value,
            rec.created_at,
            rec.updated_at,
            rec.last_replan_at,
        ),
    )
    conn.commit()


def load_intent(conn: sqlite3.Connection, intent_id: str) -> Optional[IntentRecord]:
    row = conn.execute("SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
    return _row_to_intent(row) if row else None


def active_intents(conn: sqlite3.Connection) -> List[IntentRecord]:
    """
    Intents M2 must consider when testing feasibility of a new request.

    Ordered by priority then creation time, which is also the preemption order:
    lowest priority first, and among equals the most recently admitted goes first
    because the plan says the first admitted keeps its resources.
    """
    rows = conn.execute(
        """
        SELECT * FROM intents
        WHERE state IN ('admitted', 'active', 'degraded')
        ORDER BY priority ASC, created_at ASC
        """
    ).fetchall()
    return [_row_to_intent(r) for r in rows]


def _match_to_dict(m: Match) -> Dict[str, Any]:
    return {"src": m.src, "dst": m.dst, "proto": m.proto, "dport": m.dport}


def _guarantee_to_dict(g: Guarantee) -> Dict[str, Any]:
    return {
        "min_bandwidth_mbps": g.min_bandwidth_mbps,
        "max_latency_ms": g.max_latency_ms,
        "max_loss_pct": g.max_loss_pct,
        "isolate_from": list(g.isolate_from),
        "avoid_links": list(g.avoid_links),
    }


def _row_to_intent(row: sqlite3.Row) -> IntentRecord:
    m = json.loads(row["match_json"])
    g = json.loads(row["guarantee_json"])
    return IntentRecord(
        id=row["id"],
        tenant=row["tenant"],
        priority=row["priority"],
        match=Match(src=m["src"], dst=m["dst"], proto=m["proto"], dport=m["dport"]),
        guarantee=Guarantee(
            min_bandwidth_mbps=g["min_bandwidth_mbps"],
            max_latency_ms=g["max_latency_ms"],
            max_loss_pct=g["max_loss_pct"],
            isolate_from=tuple(g["isolate_from"]),
            avoid_links=tuple(g["avoid_links"]),
        ),
        consistency=Consistency(row["consistency"]),
        on_violation=OnViolation(row["on_violation"]),
        dwell_seconds=row["dwell_seconds"],
        state=IntentState(row["state"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_replan_at=row["last_replan_at"],
    )


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

def save_path(conn: sqlite3.Connection, plan: PathPlan) -> int:
    """
    Record a newly installed path and supersede the previous one.

    Both happen in one transaction: an intent must never appear to have two
    current paths, because M2's capacity accounting would then double-count it.
    """
    now = time.time()
    with conn:
        conn.execute(
            "UPDATE paths SET superseded_at = ? "
            "WHERE intent_id = ? AND superseded_at IS NULL",
            (now, plan.intent_id),
        )
        cur = conn.execute(
            """
            INSERT INTO paths (intent_id, switches_json, links_json,
                               est_latency_ms, bottleneck_mbps, version, computed_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                plan.intent_id,
                json.dumps(list(plan.switches)),
                json.dumps(list(plan.links)),
                plan.est_latency_ms,
                plan.bottleneck_mbps,
                plan.version,
                plan.computed_at,
            ),
        )
    return int(cur.lastrowid)


def current_path(conn: sqlite3.Connection, intent_id: str) -> Optional[PathPlan]:
    row = conn.execute(
        "SELECT * FROM paths WHERE intent_id = ? AND superseded_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (intent_id,),
    ).fetchone()
    if row is None:
        return None
    return PathPlan(
        intent_id=row["intent_id"],
        switches=tuple(json.loads(row["switches_json"])),
        links=tuple(json.loads(row["links_json"])),
        est_latency_ms=row["est_latency_ms"],
        bottleneck_mbps=row["bottleneck_mbps"],
        version=row["version"],
        computed_at=row["computed_at"],
    )


def reroute_count(conn: sqlite3.Connection, intent_id: str) -> int:
    """
    How many times this intent has been moved. Metric E6 reads this directly.

    The first installation is not a reroute, hence the subtraction.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM paths WHERE intent_id = ?", (intent_id,)
    ).fetchone()
    return max(0, int(row["n"]) - 1)


# --------------------------------------------------------------------------- #
# Measurements and events
# --------------------------------------------------------------------------- #

def save_measurement(
    conn: sqlite3.Connection,
    intent_id: str,
    at: float,
    delay_ms: Optional[float] = None,
    jitter_ms: Optional[float] = None,
    loss_pct: Optional[float] = None,
    throughput_mbps: Optional[float] = None,
) -> None:
    conn.execute(
        "INSERT INTO measurements (intent_id, at, delay_ms, jitter_ms, loss_pct, "
        "throughput_mbps) VALUES (?,?,?,?,?,?)",
        (intent_id, at, delay_ms, jitter_ms, loss_pct, throughput_mbps),
    )
    prune_retention(conn)
    conn.commit()


def save_event(conn: sqlite3.Connection, event: Event) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO events (id, type, severity, intent_id, at, message, "
        "payload_json) VALUES (?,?,?,?,?,?,?)",
        (
            event.id,
            event.type.value,
            event.severity.value,
            event.intent_id,
            event.at,
            event.message,
            json.dumps(event.payload, sort_keys=True),
        ),
    )
    prune_retention(conn)
    conn.commit()


def events_for(
    conn: sqlite3.Connection, intent_id: Optional[str] = None, limit: int = 200
) -> List[Event]:
    """Most recent first. This is what M6's event stream renders."""
    if intent_id is None:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY at DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM events WHERE intent_id = ? ORDER BY at DESC LIMIT ?",
            (intent_id, limit),
        ).fetchall()
    return [
        Event(
            type=EventType(r["type"]),
            message=r["message"],
            intent_id=r["intent_id"],
            severity=Severity(r["severity"]),
            payload=json.loads(r["payload_json"]),
            at=r["at"],
            id=r["id"],
        )
        for r in rows
    ]


def measurements_for(
    conn: sqlite3.Connection, intent_id: str, since: float = 0.0
) -> Iterable[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM measurements WHERE intent_id = ? AND at >= ? ORDER BY at ASC",
        (intent_id, since),
    ).fetchall()


# --------------------------------------------------------------------------- #
# Retention, Per-intent Queues, Link State, and Degraded Rates
# --------------------------------------------------------------------------- #


def prune_retention(conn: sqlite3.Connection) -> None:
    """Prune old measurements and events when retention env vars are explicitly set."""
    max_rows_raw = os.environ.get("TEAM16_RETENTION_MAX_ROWS") or os.environ.get(
        "TEAM16_RETENTION_ROWS"
    )
    max_sec_raw = os.environ.get("TEAM16_RETENTION_SECONDS")
    if not max_rows_raw and not max_sec_raw:
        return

    if max_sec_raw:
        try:
            max_sec = float(max_sec_raw)
        except ValueError:
            max_sec = 0.0
        if max_sec > 0:
            cutoff = time.time() - max_sec
            conn.execute("DELETE FROM measurements WHERE at < ?", (cutoff,))
            conn.execute("DELETE FROM events WHERE at < ?", (cutoff,))

    if max_rows_raw:
        try:
            max_rows = int(max_rows_raw)
        except ValueError:
            max_rows = 0
        if max_rows > 0:
            conn.execute(
                "DELETE FROM measurements WHERE id NOT IN ("
                "SELECT id FROM measurements ORDER BY at DESC, id DESC LIMIT ?"
                ")",
                (max_rows,),
            )
            conn.execute(
                "DELETE FROM events WHERE rowid NOT IN ("
                "SELECT rowid FROM events ORDER BY at DESC, rowid DESC LIMIT ?"
                ")",
                (max_rows,),
            )


def _ensure_aux_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS intent_queues (
            intent_id  TEXT    NOT NULL,
            switch     TEXT    NOT NULL,
            port       TEXT    NOT NULL,
            queue_id   INTEGER NOT NULL,
            min_bps    INTEGER NOT NULL,
            max_bps    INTEGER NOT NULL,
            updated_at REAL    NOT NULL,
            PRIMARY KEY (intent_id, switch, port),
            UNIQUE (switch, port, queue_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS link_states (
            link       TEXT PRIMARY KEY,
            up         INTEGER NOT NULL,
            updated_at REAL    NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS degraded_rates (
            intent_id          TEXT PRIMARY KEY REFERENCES intents(id) ON DELETE CASCADE,
            original_min_mbps  REAL NOT NULL,
            effective_min_mbps REAL NOT NULL,
            updated_at         REAL NOT NULL
        )
        """
    )


def allocate_queue_id(
    conn: sqlite3.Connection,
    intent_id: str,
    switch: str,
    port: str,
    min_bps: int = 0,
    max_bps: int = 0,
) -> int:
    """Allocate or retrieve a deterministic, collision-checked queue ID per intent and egress port."""
    _ensure_aux_tables(conn)
    now = time.time()
    existing = conn.execute(
        "SELECT queue_id FROM intent_queues WHERE intent_id = ? AND switch = ? AND port = ?",
        (intent_id, switch, port),
    ).fetchone()
    if existing is not None:
        qid = int(existing["queue_id"])
        conn.execute(
            "UPDATE intent_queues SET min_bps = ?, max_bps = ?, updated_at = ? "
            "WHERE intent_id = ? AND switch = ? AND port = ?",
            (int(min_bps), int(max_bps), now, intent_id, switch, port),
        )
        conn.commit()
        return qid

    port_used = {
        int(row["queue_id"])
        for row in conn.execute(
            "SELECT queue_id FROM intent_queues WHERE switch = ? AND port = ?",
            (switch, port),
        ).fetchall()
    }
    intent_existing = conn.execute(
        "SELECT queue_id FROM intent_queues WHERE intent_id = ? ORDER BY queue_id ASC LIMIT 1",
        (intent_id,),
    ).fetchone()
    if intent_existing is not None and int(intent_existing["queue_id"]) not in port_used:
        candidate = int(intent_existing["queue_id"])
    else:
        global_used = {
            int(row["queue_id"])
            for row in conn.execute("SELECT DISTINCT queue_id FROM intent_queues").fetchall()
        } | port_used
        candidate = 1
        while candidate in global_used:
            candidate += 1

    conn.execute(
        "INSERT INTO intent_queues (intent_id, switch, port, queue_id, min_bps, max_bps, updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (intent_id, switch, port, candidate, int(min_bps), int(max_bps), now),
    )
    conn.commit()
    return candidate


def intent_queues_for(conn: sqlite3.Connection, intent_id: str) -> List[Dict[str, Any]]:
    """Return all persisted queue allocations for an intent."""
    _ensure_aux_tables(conn)
    rows = conn.execute(
        "SELECT intent_id, switch, port, queue_id, min_bps, max_bps, updated_at "
        "FROM intent_queues WHERE intent_id = ? ORDER BY switch, port",
        (intent_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_intent_queues(
    conn: sqlite3.Connection,
    intent_id: str,
    keep_ports: Optional[Iterable[Tuple[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Delete queue rows for intent_id (except keep_ports) and return the deleted rows."""
    _ensure_aux_tables(conn)
    keep = set(keep_ports or ())
    current = intent_queues_for(conn, intent_id)
    removed = [row for row in current if (row["switch"], row["port"]) not in keep]
    for row in removed:
        conn.execute(
            "DELETE FROM intent_queues WHERE intent_id = ? AND switch = ? AND port = ?",
            (intent_id, row["switch"], row["port"]),
        )
    if removed:
        conn.commit()
    return removed


def set_link_state(conn: sqlite3.Connection, link: str, up: bool) -> None:
    """Persist link operational state so admission and reroute never select a down link."""
    _ensure_aux_tables(conn)
    conn.execute(
        "INSERT OR REPLACE INTO link_states (link, up, updated_at) VALUES (?, ?, ?)",
        (link, 1 if up else 0, time.time()),
    )
    conn.commit()


def down_links(conn: sqlite3.Connection) -> Set[str]:
    """Return canonical link names currently marked down in SQLite."""
    try:
        rows = conn.execute("SELECT link FROM link_states WHERE up = 0").fetchall()
        return {str(r["link"]) for r in rows}
    except sqlite3.OperationalError:
        return set()


def set_degraded_rate(
    conn: sqlite3.Connection,
    intent_id: str,
    original_min_mbps: float,
    effective_min_mbps: float,
) -> None:
    """Record a degraded bandwidth reservation for an intent."""
    _ensure_aux_tables(conn)
    conn.execute(
        "INSERT OR REPLACE INTO degraded_rates "
        "(intent_id, original_min_mbps, effective_min_mbps, updated_at) VALUES (?, ?, ?, ?)",
        (intent_id, float(original_min_mbps), float(effective_min_mbps), time.time()),
    )
    conn.commit()


def clear_degraded_rate(
    conn: sqlite3.Connection, intent_id: str
) -> Optional[Tuple[float, float]]:
    """Remove degraded rate record and return (original_min_mbps, effective_min_mbps) if present."""
    _ensure_aux_tables(conn)
    row = conn.execute(
        "SELECT original_min_mbps, effective_min_mbps FROM degraded_rates WHERE intent_id = ?",
        (intent_id,),
    ).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM degraded_rates WHERE intent_id = ?", (intent_id,))
    conn.commit()
    return float(row["original_min_mbps"]), float(row["effective_min_mbps"])


def effective_min_bandwidth_mbps(conn: sqlite3.Connection, rec: IntentRecord) -> float:
    """Return the active bandwidth reservation for an intent, accounting for M1 degradation."""
    base = float(rec.guarantee.min_bandwidth_mbps or 0.0)
    if base <= 0.0 or rec.state is not IntentState.DEGRADED:
        return base
    try:
        row = conn.execute(
            "SELECT effective_min_mbps FROM degraded_rates WHERE intent_id = ?",
            (rec.id,),
        ).fetchone()
        if row is not None:
            return float(row["effective_min_mbps"])
    except sqlite3.OperationalError:
        pass
    factor = float(os.environ.get("TEAM16_DEGRADE_FACTOR", "0.5"))
    return round(base * factor, 6)
