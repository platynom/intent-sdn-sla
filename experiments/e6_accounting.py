"""Complete durable event counts for a measurement run, without UI pagination."""


def counts_for_run(conn, intent_id: str, run_start: float) -> dict:
    """Count every matching event type in SQLite rather than a bounded list."""
    return dict(conn.execute(
        "SELECT type, COUNT(*) FROM events WHERE intent_id = ? AND at >= ? GROUP BY type",
        (intent_id, run_start),
    ).fetchall())
