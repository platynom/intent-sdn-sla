"""Standards-derived input policy must preserve the evaluated grammar and pipeline."""
import ast
import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from starlette.requests import Request

from src.common import db
from src.intent_manager import api, profiles
from src.intent_manager.validator import validate
from src.dashboard import app as dashboard

ROOT = Path(__file__).resolve().parents[1]
MATCH = {"src": "10.0.0.1/32", "dst": "10.0.0.2/32", "proto": "udp", "dport": 5001}
CLASSES = ("urllc", "v2x", "smart_grid", "embb", "mmtc")


def parameters(name):
    return dict(service_class=name, intent_id="INT-901", tenant="profile-test", match=MATCH)


def request(data):
    async def receive():
        return {"type": "http.request", "body": json.dumps(data).encode(), "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/intent/from-profile",
                    "headers": [(b"content-type", b"application/json")]}, receive)


@pytest.mark.parametrize("name", CLASSES)
def test_generated_profile_uses_the_existing_grammar(name):
    """A profile bypassing the validator would install unsupported requirements."""
    generated = profiles.build_intent(**parameters(name))
    assert validate(generated).ok
    assert profiles.check_against_profile(generated, name) == []
    assert generated["intent"]["on_violation"] == "reroute"


def test_every_profile_preserves_source_and_rate_provenance():
    """Unattributed values could be presented falsely as standardized guarantees."""
    for profile in profiles.list_profiles():
        assert all(profile["source"].get(key) for key in ("spec", "version", "table", "clause", "note", "url"))
        assert profile["bandwidth_source"]["kind"] in ("assumption", "standard_example", "none")
        assert profile["transport_share_basis"].startswith("ASSUMPTION")


def test_profile_facts_match_the_pinned_release_seventeen_rows():
    """A wrong QoS mapping would silently assign a different service's budget."""
    expected = {"urllc": (82, 10, 1, 0.0001, 19), "v2x": (86, 5, 2, 0.0001, 18),
                "smart_grid": (85, 5, 2, 0.00001, 21), "embb": (2, 150, 20, 0.001, 40),
                "mmtc": (9, 300, 20, 0.000001, 90)}
    for profile in profiles.list_profiles():
        assert tuple(profile[k] for k in ("five_qi", "pdb_ms", "cn_pdb_ms", "per", "standard_priority")) == expected[profile["service_class"]]


def test_budget_comparison_is_separate_from_the_default():
    """Using the radio-side comparison as the default would change admission policy."""
    for profile in profiles.list_profiles():
        assert profile["transport_target_a_ms"] == profile["cn_pdb_ms"]
        assert profile["transport_target_b_ms"] == pytest.approx(
            (profile["pdb_ms"] - profile["cn_pdb_ms"]) * profile["transport_share"])
        document = profiles.build_intent(**parameters(profile["service_class"]))
        assert document["intent"]["guarantee"]["max_latency_ms"] == profile["cn_pdb_ms"]


def test_looser_overrides_and_update_policy_are_reported():
    """Operators must see when overrides weaken the selected profile."""
    generated = profiles.build_intent(**parameters("urllc"), priority=3, consistency="relaxed",
                                     overrides={"max_latency_ms": 20, "max_loss_pct": 1,
                                                "min_bandwidth_mbps": 10})
    warnings = profiles.check_against_profile(generated, "urllc")
    assert len(warnings) == 5
    assert all(any(key in warning for warning in warnings)
               for key in ("max_latency_ms", "max_loss_pct", "min_bandwidth_mbps"))


def test_unknown_profile_is_not_silently_substituted():
    """A misspelled service class must not activate an unrelated service policy."""
    with pytest.raises(ValueError, match="Unknown service class"):
        profiles.build_intent(**parameters("unknown"))


def test_overrides_cannot_widen_the_frozen_grammar():
    """Profile overrides must not smuggle unsupported jitter constraints into M1."""
    with pytest.raises(ValueError, match="max_jitter_ms"):
        profiles.build_intent(**parameters("embb"), overrides={"max_jitter_ms": 2})


def test_non_gbr_profile_does_not_invent_a_guaranteed_rate():
    """Treating non-GBR metadata as a standardized GBR rate would mislead users."""
    generated = profiles.build_intent(**parameters("mmtc"))["intent"]
    assert "min_bandwidth_mbps" not in generated["guarantee"]
    assert generated["priority"] == 4  # Existing priority-5 latency rule remains intact.
    assert generated["consistency"] == "relaxed"


@pytest.mark.parametrize("name", ("urllc", "v2x", "smart_grid"))
def test_infeasible_profile_has_the_normal_explained_refusal(name):
    """The emulator must refuse unattainable budgets instead of weakening the SLA."""
    conn = db.connect(":memory:")
    db.init_db(conn)
    try:
        response = asyncio.run(api.create_from_profile(request(parameters(name)), conn))
        result = json.loads(response.body)
        assert response.status_code == 201
        assert result["state"] == "rejected"
        assert "max_latency_ms" in result["reasons"]["admission"]
        assert db.current_path(conn, "INT-901") is None
    finally:
        conn.close()


@pytest.mark.parametrize("name", ("embb", "mmtc"))
def test_feasible_profile_displays_through_the_existing_dashboard(name):
    """A generated record must remain readable by M6 without a dashboard redesign."""
    conn = db.connect(":memory:")
    db.init_db(conn)
    try:
        response = asyncio.run(api.create_from_profile(request(parameters(name)), conn))
        result = json.loads(response.body)
        assert result["state"] == "admitted"
        assert result["switches"] == ["s1", "s2", "s3", "s7"]
        snapshot = dashboard._snapshot(conn, "INT-901")
        assert snapshot["path"]["switches"] == result["switches"]
        assert snapshot["telemetry_source"] == "none"
    finally:
        conn.close()


def test_unknown_profile_api_returns_422_without_storing_an_intent():
    """Bad profile input must fail before admission or persistence side effects."""
    conn = db.connect(":memory:")
    db.init_db(conn)
    try:
        response = asyncio.run(api.create_from_profile(request(parameters("unknown")), conn))
        assert response.status_code == 422
        assert conn.execute("SELECT COUNT(*) FROM intents").fetchone()[0] == 0
    finally:
        conn.close()


def test_profile_routes_are_exposed_by_fastapi():
    """Helpers without registered HTTP routes would be unusable by operators."""
    routes = {route.path: route.methods for route in api.app.routes}
    assert "GET" in routes["/profiles"]
    assert "POST" in routes["/intent/from-profile"]


def test_schema_sha256_matches_the_untouched_baseline():
    """Profiles must never expand the grammar that the experiments evaluated."""
    content = (ROOT / "src/intent_manager/schema.json").read_bytes().replace(b"\r\n", b"\n")
    # Git baseline bytes; CRLF checkout conversion is not a grammar edit.
    assert hashlib.sha256(content).hexdigest() == "6181eb5198e39a96b6fee65e28415c792e648cfb22805e3992bffd82df51003e"


def test_original_intent_handler_is_unchanged_from_baseline():
    """The new front end must not alter the already evaluated admission endpoint."""
    before = subprocess.check_output(["git", "show", "73e6b57:src/intent_manager/api.py"], cwd=ROOT).decode()
    after = (ROOT / "src/intent_manager/api.py").read_text(encoding="utf-8")
    def handler(source):
        return ast.dump(next(node for node in ast.parse(source).body
                             if isinstance(node, ast.AsyncFunctionDef) and node.name == "create_intent"))
    assert handler(before) == handler(after)
