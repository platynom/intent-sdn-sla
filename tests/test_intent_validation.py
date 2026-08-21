"""
ST-1 gate test: the intent grammar is frozen and the validator enforces it.

This suite is the executable half of the ST-1 gate ("Frozen: stack + intent
grammar"). If someone widens the grammar without a team decision, these fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.intent_manager.validator import (
    FROZEN_ACTIONS,
    FROZEN_CONSTRAINTS,
    SCHEMA_PATH,
    validate,
    validate_file,
    validate_yaml,
)

REPO = Path(__file__).resolve().parents[1]
INTENTS = REPO / "intents"
VALID = sorted(INTENTS.glob("s*.yaml"))
INVALID = sorted((INTENTS / "invalid").glob("*.yaml"))


# --------------------------------------------------------------------------- #
# The grammar is frozen
# --------------------------------------------------------------------------- #

def test_schema_is_parseable():
    json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_exactly_five_constraint_types():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    props = schema["properties"]["intent"]["properties"]["guarantee"]["properties"]
    assert set(props) == FROZEN_CONSTRAINTS, (
        "The guarantee block must contain exactly the five frozen constraint types. "
        "Adding a sixth requires whole-team sign-off (ADR-002)."
    )


def test_exactly_three_violation_actions():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    actions = schema["properties"]["intent"]["properties"]["on_violation"]["enum"]
    assert set(actions) == FROZEN_ACTIONS


def test_priority_scale_is_one_to_five():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    pri = schema["properties"]["intent"]["properties"]["priority"]
    assert (pri["minimum"], pri["maximum"]) == (1, 5)


def test_unknown_fields_are_rejected_everywhere():
    """additionalProperties:false at every level, or the freeze is cosmetic."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    intent = schema["properties"]["intent"]
    for node in (schema, intent, intent["properties"]["match"],
                 intent["properties"]["guarantee"]):
        assert node.get("additionalProperties") is False


# --------------------------------------------------------------------------- #
# Every shipped example is valid
# --------------------------------------------------------------------------- #

def test_there_is_an_example_per_scenario():
    assert len(VALID) == 8, f"expected 8 scenario intents, found {len(VALID)}"


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_shipped_intents_are_valid(path):
    result = validate_file(path)
    assert result.ok, f"{path.name} should be valid:\n{result.report()}"


# --------------------------------------------------------------------------- #
# Every deliberately bad example is rejected, precisely
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.name)
def test_bad_intents_are_rejected(path):
    result = validate_file(path)
    assert not result.ok, f"{path.name} should have been rejected"
    assert result.errors, "rejection must carry at least one error"
    for err in result.errors:
        assert err.path, "every error needs a path a human can act on"
        assert err.message


def test_sixth_constraint_is_named_in_the_error():
    result = validate_file(INTENTS / "invalid" / "bad_sixth_constraint.yaml")
    assert not result.ok
    assert any("max_jitter_ms" in e.message for e in result.errors), result.report()


def test_noncanonical_link_suggests_the_fix():
    result = validate_file(INTENTS / "invalid" / "bad_noncanonical_link.yaml")
    assert not result.ok
    assert any("s3-s4" in e.message for e in result.errors), result.report()


# --------------------------------------------------------------------------- #
# "Never crashes on bad input"
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "junk",
    [
        None, 42, 3.14, "", "not a mapping", [], [1, 2, 3], {},
        {"intent": None}, {"intent": []}, {"intent": {}},
        {"wrong_root": {"id": "INT-001"}},
        {"intent": {"id": "INT-001"}},                       # missing required
        {"intent": {"id": "nope", "tenant": "t", "priority": 1,
                    "match": {"src": "10.0.0.1/32", "dst": "10.0.0.2/32"},
                    "guarantee": {"min_bandwidth_mbps": 1}}},  # bad id pattern
    ],
)
def test_never_raises_on_junk(junk):
    result = validate(junk)
    assert result.ok is False
    assert result.errors


@pytest.mark.parametrize(
    "text",
    ["", "   ", "\n\n", "[1,2,3", "a: b: c", "\t- broken", "%YAML 9.9\n---\nx: 1"],
)
def test_never_raises_on_bad_yaml(text):
    result = validate_yaml(text)
    assert result.ok is False
    assert result.errors


def test_missing_file_is_an_error_not_a_crash():
    result = validate_file(REPO / "intents" / "does_not_exist.yaml")
    assert not result.ok


# --------------------------------------------------------------------------- #
# Semantic rules the schema cannot express
# --------------------------------------------------------------------------- #

def _base(**overrides):
    doc = {
        "intent": {
            "id": "INT-100",
            "tenant": "test-tenant",
            "priority": 2,
            "match": {"src": "10.0.0.1/32", "dst": "10.0.0.2/32"},
            "guarantee": {"min_bandwidth_mbps": 10},
        }
    }
    doc["intent"].update(overrides)
    return doc


def test_src_equal_to_dst_is_rejected():
    doc = _base(match={"src": "10.0.0.1/32", "dst": "10.0.0.1/32"})
    result = validate(doc)
    assert not result.ok
    assert any(e.path == "intent.match" for e in result.errors)


def test_dport_without_tcp_or_udp_is_rejected():
    doc = _base(match={"src": "10.0.0.1/32", "dst": "10.0.0.2/32",
                       "proto": "icmp", "dport": 80})
    result = validate(doc)
    assert not result.ok
    assert any(e.path == "intent.match.dport" for e in result.errors)


def test_best_effort_with_latency_bound_is_rejected():
    doc = _base(priority=5, guarantee={"max_latency_ms": 10})
    result = validate(doc)
    assert not result.ok
    assert any(e.path == "intent.priority" for e in result.errors)


def test_guarantee_of_only_empty_lists_is_rejected():
    doc = _base(guarantee={"isolate_from": [], "avoid_links": []})
    result = validate(doc)
    assert not result.ok
    assert any(e.path == "intent.guarantee" for e in result.errors)


def test_minimal_valid_intent_passes():
    assert validate(_base()).ok


def test_defaults_are_not_required():
    """consistency, on_violation and dwell_seconds are optional; M1 applies defaults."""
    doc = _base()
    for key in ("consistency", "on_violation", "dwell_seconds"):
        assert key not in doc["intent"]
    assert validate(doc).ok
