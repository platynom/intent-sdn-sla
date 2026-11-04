"""Standards-derived project profiles in front of the unchanged intent grammar."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.intent_manager.validator import validate

CATALOG = Path(__file__).with_name("profiles.yaml")


def list_profiles() -> List[dict]:
    """Return source metadata, assumptions, and both candidate transport targets."""
    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    share = catalog["transport_share"]
    if isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 < share <= 1:
        raise ValueError("transport_share must be a fraction greater than 0 and at most 1")
    result = []
    for name, original in catalog["profiles"].items():
        profile = deepcopy(original)
        profile.update(
            service_class=name,
            transport_share=share,
            transport_share_basis="ASSUMPTION (not standardized)",
            transport_target_a_ms=profile["cn_pdb_ms"],
            transport_target_b_ms=float((Decimal(str(profile["pdb_ms"]))
                                         - Decimal(str(profile["cn_pdb_ms"]))) * Decimal(str(share))),
            max_loss_pct=float(Decimal(str(profile["per"])) * 100),
            loss_mapping="PER times 100 is a project IP-loss proxy, not metric equivalence",
            consistency="strict" if profile["resource_type"] == "Delay-critical GBR" else "relaxed",
        )
        result.append(profile)
    return result


def _profile(service_class: str) -> dict:
    for profile in list_profiles():
        if profile["service_class"] == service_class:
            return profile
    raise ValueError(f"Unknown service class {service_class!r}; choose "
                     + ", ".join(row["service_class"] for row in list_profiles()))


def build_intent(service_class: str, intent_id: str, tenant: str, match: dict,
                 priority: Optional[int] = None, overrides: Optional[dict] = None,
                 consistency: Optional[str] = None) -> Dict[str, Any]:
    """Generate a normal validated document using method A; overrides are guarantees.

    A None override removes that guarantee, which can produce a looser-profile
    warning. Unsupported fields still fail the existing frozen validator.
    """
    profile = _profile(service_class)
    guarantee = {"max_latency_ms": profile["transport_target_a_ms"],
                 "max_loss_pct": profile["max_loss_pct"]}
    if profile["min_bandwidth_mbps"] is not None:
        guarantee["min_bandwidth_mbps"] = profile["min_bandwidth_mbps"]
    if overrides is not None:
        if not isinstance(overrides, dict):
            raise ValueError("overrides must be a mapping of guarantee fields")
        for key, value in overrides.items():
            if value is None and key in guarantee:
                guarantee.pop(key)
            else:
                guarantee[key] = value
    document = {"intent": {
        "id": intent_id, "tenant": tenant,
        "priority": profile["project_priority"] if priority is None else priority,
        "match": deepcopy(match), "guarantee": guarantee,
        "consistency": profile["consistency"] if consistency is None else consistency,
        "on_violation": "reroute", "dwell_seconds": 10,
    }}
    result = validate(document)
    if not result.ok:
        raise ValueError("; ".join(f"{error.path}: {error.message}" for error in result.errors))
    return document


def check_against_profile(intent_dict: dict, service_class: str) -> List[str]:
    """Warn about relaxed bounds or policy without claiming standards compliance."""
    profile = _profile(service_class)
    intent = intent_dict.get("intent", intent_dict)
    guarantee = intent.get("guarantee", {})
    warnings = []
    for key, reference, lower_is_looser in (
        ("max_latency_ms", profile["transport_target_a_ms"], False),
        ("max_loss_pct", profile["max_loss_pct"], False),
        ("min_bandwidth_mbps", profile["min_bandwidth_mbps"], True),
    ):
        if reference is None:
            continue
        actual = guarantee.get(key)
        if actual is None or (actual < reference if lower_is_looser else actual > reference):
            warnings.append(f"{key}={actual!r} is looser than profile {reference}")
    if intent.get("priority", profile["project_priority"]) > profile["project_priority"]:
        warnings.append("Project priority is lower than the profile's project policy")
    if profile["consistency"] == "strict" and intent.get("consistency", "strict") != "strict":
        warnings.append("Relaxed consistency weakens the delay-critical profile's update policy")
    return warnings
