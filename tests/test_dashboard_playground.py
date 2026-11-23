"""Hands-on playground: dry-run planning never writes; submit/withdraw proxy to M1."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest
from fastapi import HTTPException

from src.common import db
from src.common.models import Guarantee, IntentRecord, IntentState, Match, PathPlan
from src.dashboard import app as dashboard_app
from src.dashboard import playground

URLLC = """
intent:
  id: INT-101
  tenant: guest-urllc
  priority: 2
  match: {src: 10.0.0.1/32, dst: 10.0.0.2/32, proto: udp, dport: 5701}
  guarantee: {min_bandwidth_mbps: 20, max_latency_ms: 20, max_loss_pct: 0.5}
  consistency: strict
  on_violation: reroute
"""


class _Out:
    def __init__(self, status_code, data=None, text=""):
        self.status_code, self._data, self.text = status_code, data, text

    def json(self):
        return self._data


class _Client:
    """Calls the endpoint functions directly (no httpx needed in CI)."""

    def _call(self, fn, *args):
        try:
            return _Out(200, fn(*args))
        except HTTPException as exc:
            return _Out(exc.status_code, {"detail": exc.detail})

    def get(self, url):
        if url == "/try":
            return _Out(200, text=playground.try_page())
        if url == "/":
            return _Out(200, text=dashboard_app.dashboard())
        return self._call(playground.try_topology)

    def post(self, url, json=None):
        if url == "/api/try/plan":
            return self._call(playground.try_plan, playground.PlanRequest(**json))
        if url == "/api/try/submit":
            return self._call(playground.try_submit, playground.SubmitRequest(**json))
        return self._call(playground.try_withdraw, url.rsplit("/", 1)[1])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    path = tmp_path / "playground.db"
    real_connect = db.connect
    conn = real_connect(path)
    db.init_db(conn)
    conn.close()
    monkeypatch.setattr(db, "connect", lambda path_arg=None: real_connect(path_arg or path))
    monkeypatch.delenv("TEAM16_DASHBOARD_READONLY", raising=False)
    return _Client(), path


def _row_counts(path):
    conn = db.connect(path)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("intents", "paths", "events", "measurements")}
    finally:
        conn.close()


def _add_active(path, intent_id, tenant, priority, bw, switches, dport):
    conn = db.connect(path)
    rec = IntentRecord(id=intent_id, tenant=tenant, priority=priority,
                       match=Match("10.0.0.1/32", "10.0.0.2/32", "udp", dport),
                       guarantee=Guarantee(min_bandwidth_mbps=bw), state=IntentState.ACTIVE)
    db.save_intent(conn, rec)
    db.save_path(conn, PathPlan(intent_id=intent_id, switches=tuple(switches),
                                links=PathPlan.links_for(switches), est_latency_ms=6,
                                bottleneck_mbps=100, version=1))
    conn.close()


def test_page_and_topology(client):
    c, _ = client
    page = c.get("/try").text
    assert "Try an intent" in page and "/api/try/plan" in page
    assert "/try" in c.get("/").text
    topo = c.get("/api/try/topology").json()
    assert len(topo["links"]) == 8 and len(topo["hosts"]) == 8
    assert all(link["residual_mbps"] == link["capacity_mbps"] for link in topo["links"])


def test_plan_admits_on_fast_path_without_writing(client):
    c, path = client
    before = _row_counts(path)
    plan = c.post("/api/try/plan", json={"yaml": URLLC}).json()
    assert plan["ok"] and plan["decision"]["verdict"] == "admit"
    assert plan["chosen"]["switches"] == ["s1", "s2", "s3", "s7"]
    assert len(plan["candidates"]) == 3 and plan["would_be_status"] == 201
    assert _row_counts(path) == before


def test_what_if_fault_moves_the_path(client):
    c, _ = client
    down = c.post("/api/try/plan", json={"yaml": URLLC,
                                         "faults": [{"link": "s2-s3", "mode": "down"}]}).json()
    assert down["chosen"]["switches"] == ["s1", "s4", "s5", "s7"]
    slow = c.post("/api/try/plan", json={"yaml": URLLC, "faults": [
        {"link": "s1-s2", "mode": "delay", "extra_delay_ms": 40}]}).json()
    assert slow["chosen"]["switches"] == ["s1", "s4", "s5", "s7"]
    rejected = [cand for cand in slow["candidates"] if not cand["feasible"]]
    assert any("exceeds max_latency_ms" in cand["reason"] for cand in rejected)
    bad = c.post("/api/try/plan", json={"yaml": URLLC, "faults": [{"link": "s1-s9"}]})
    assert bad.status_code == 422


def test_plan_reports_rejection_and_invalid_grammar(client):
    c, _ = client
    infeasible = URLLC.replace("min_bandwidth_mbps: 20", "min_bandwidth_mbps: 500")
    plan = c.post("/api/try/plan", json={"yaml": infeasible}).json()
    assert plan["decision"]["verdict"] == "reject" and plan["chosen"] is None
    assert not any(cand["feasible"] for cand in plan["candidates"])
    assert "insufficient bandwidth: 100 < 500" in plan["decision"]["reason"]
    invalid = URLLC.replace("max_loss_pct: 0.5", "max_jitter_ms: 5")
    bad = c.post("/api/try/plan", json={"yaml": invalid}).json()
    assert bad["ok"] is False and bad["would_be_status"] == 422 and bad["errors"]
    broken = c.post("/api/try/plan", json={"yaml": "intent: [unclosed"}).json()
    assert broken["stage"] == "parse"


def test_plan_uses_residual_capacity_and_flags_conflicts(client):
    c, path = client
    _add_active(path, "INT-050", "video", 3, 90, ["s1", "s2", "s3", "s7"], 6000)
    plan = c.post("/api/try/plan", json={"yaml": URLLC}).json()
    # 10 Mbit/s left on the fast path, so the 20 Mbit/s request moves to the middle path.
    assert plan["chosen"]["switches"] == ["s1", "s4", "s5", "s7"]
    topo = c.get("/api/try/topology").json()
    assert {x["name"]: x["residual_mbps"] for x in topo["links"]}["s1-s2"] == 10
    dup = URLLC.replace("INT-101", "INT-050")
    assert c.post("/api/try/plan", json={"yaml": dup}).json()["would_be_status"] == 409
    overlap = URLLC.replace("dport: 5701", "dport: 6000")
    assert c.post("/api/try/plan", json={"yaml": overlap}).json()["would_be_status"] == 409


class _Resp(io.BytesIO):
    def __init__(self, status, body):
        super().__init__(json.dumps(body).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_submit_and_withdraw_forward_to_intent_api(client, monkeypatch):
    c, _ = client
    seen = []

    def fake_urlopen(request, timeout):
        seen.append((request.get_method(), request.full_url, request.data))
        if request.get_method() == "DELETE":
            raise urllib.error.HTTPError(request.full_url, 404, "nf", {},
                                         io.BytesIO(b'{"detail": "Intent INT-101 not found"}'))
        return _Resp(201, {"id": "INT-101", "state": "admitted", "switches": ["s1", "s2"]})

    monkeypatch.setattr(playground.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("TEAM16_INTENT_API_URL", "http://api.test:8000")
    r = c.post("/api/try/submit", json={"yaml": URLLC}).json()
    assert r == {"status": 201, "body": {"id": "INT-101", "state": "admitted", "switches": ["s1", "s2"]}}
    assert seen[0][0] == "POST" and seen[0][1] == "http://api.test:8000/intent"
    assert seen[0][2] == URLLC.encode()
    w = c.post("/api/try/withdraw/INT-101").json()
    assert w["status"] == 404 and seen[1][:2] == ("DELETE", "http://api.test:8000/intent/INT-101")
    assert c.post("/api/try/withdraw/..%2Fhealth").status_code == 422
    assert c.post("/api/try/withdraw/INT-1x").status_code == 422


def test_read_only_mode_and_unreachable_api(client, monkeypatch):
    c, _ = client
    monkeypatch.setenv("TEAM16_DASHBOARD_READONLY", "1")
    assert c.post("/api/try/submit", json={"yaml": URLLC}).status_code == 403
    assert c.post("/api/try/withdraw/INT-101").status_code == 403
    assert c.get("/api/try/topology").json()["read_only"] is True
    monkeypatch.delenv("TEAM16_DASHBOARD_READONLY")

    def down(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(playground.urllib.request, "urlopen", down)
    assert c.post("/api/try/submit", json={"yaml": URLLC}).status_code == 502
    big = "#" * (64 * 1024 + 1)
    assert c.post("/api/try/plan", json={"yaml": big}).status_code == 413


def test_review_module_lists_every_red_item():
    from src.dashboard import review
    data = review.review_data()
    red = [i for i in data["items"] if i["group"] == "red"]
    assert [i["id"] for i in red] == ["C1", "C2"] + [f"J{n}" for n in range(1, 13)]
    assert sum(i["status"] == "done" for i in red) == 12
    assert len([i for i in data["items"] if i["group"] == "stale"]) == 5
    page = review.review_page()
    assert "Sir's review" in page and '"C1"' in page and "__DATA__" not in page
    assert review.RESPONSE_PDF.is_file()
    assert "tab-review" in dashboard_app.dashboard()
