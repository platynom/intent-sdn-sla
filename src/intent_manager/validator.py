"""
M1 - Intent Manager: validation.

Definition of done for this module (project plan, Section 8):
    "Rejects malformed intents with a precise error path. Never crashes on bad input."

Both halves matter. `validate()` never raises on user input - it returns a result
object. The only exceptions that escape are programming errors on our side, such as
a missing schema file.
"""

from __future__ import annotations

import json
import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name("schema.json")

# The five frozen constraint types. Duplicated here deliberately: if someone edits
# the schema without updating this list, test_grammar_frozen fails loudly.
FROZEN_CONSTRAINTS = frozenset(
    {
        "min_bandwidth_mbps",
        "max_latency_ms",
        "max_loss_pct",
        "isolate_from",
        "avoid_links",
    }
)
FROZEN_ACTIONS = frozenset({"reroute", "degrade", "alert_only"})


@dataclass(frozen=True)
class ValidationError:
    """One problem with one intent, located precisely enough to fix it."""

    path: str  # e.g. "intent.guarantee.max_latency_ms"
    message: str
    kind: str = "schema"  # "schema" | "semantic"

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.path}: {self.message}"


@dataclass
class ValidationResult:
    ok: bool
    intent: dict[str, Any] | None = None
    errors: list[ValidationError] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok

    def report(self) -> str:
        if self.ok:
            return "valid"
        return "\n".join(f"  - {e}" for e in self.errors)


def _load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


_VALIDATOR = Draft202012Validator(_load_schema())


def _json_path(err) -> str:
    """Turn a jsonschema error into a dotted path a human can act on."""
    parts = [str(p) for p in err.absolute_path]
    return ".".join(parts) if parts else "(root)"


def _semantic_checks(doc: dict[str, Any]) -> list[ValidationError]:
    """
    Rules the JSON Schema cannot express.

    Schema validation has already passed by the time this runs, so the shape is
    known good and we can index without guarding every access.
    """
    errors: list[ValidationError] = []
    intent = doc["intent"]
    match = intent["match"]
    guarantee = intent["guarantee"]

    # A flow from a prefix to itself is almost always a typo, and it makes path
    # computation degenerate.
    if match["src"] == match["dst"]:
        errors.append(
            ValidationError(
                "intent.match", "src and dst are identical; nothing to route", "semantic"
            )
        )

    # dport is meaningless without a transport protocol that has ports.
    if "dport" in match and match.get("proto", "any") not in ("tcp", "udp"):
        errors.append(
            ValidationError(
                "intent.match.dport",
                f"dport requires proto tcp or udp, got {match.get('proto', 'any')!r}",
                "semantic",
            )
        )

    # Well-formed but unroutable addresses.
    for side in ("src", "dst"):
        try:
            net = ipaddress.ip_network(match[side], strict=False)
            if net.is_multicast or net.is_reserved:
                errors.append(
                    ValidationError(
                        f"intent.match.{side}",
                        f"{match[side]} is multicast or reserved; not a valid endpoint",
                        "semantic",
                    )
                )
        except ValueError as exc:  # schema pattern should prevent this
            errors.append(
                ValidationError(f"intent.match.{side}", str(exc), "semantic")
            )

    # avoid_links must be canonical (lower-numbered switch first) so that string
    # comparison against topology edges is reliable in M3.
    for i, link in enumerate(guarantee.get("avoid_links", [])):
        a, b = link.split("-")
        if int(a[1:]) > int(b[1:]):
            errors.append(
                ValidationError(
                    f"intent.guarantee.avoid_links[{i}]",
                    f"{link!r} is not canonical; write it as {b}-{a}",
                    "semantic",
                )
            )

    # An intent that avoids nothing, isolates from nothing and guarantees nothing
    # is not actionable. minProperties in the schema catches the empty case, but
    # a guarantee of only isolate_from: [] is empty in substance.
    substantive = {
        k: v
        for k, v in guarantee.items()
        if not (isinstance(v, list) and len(v) == 0)
    }
    if not substantive:
        errors.append(
            ValidationError(
                "intent.guarantee",
                "no substantive constraint; every field is empty",
                "semantic",
            )
        )

    # A best-effort intent (priority 5) asking for a hard latency bound is a
    # contradiction worth surfacing early rather than at admission time.
    if intent["priority"] == 5 and "max_latency_ms" in guarantee:
        errors.append(
            ValidationError(
                "intent.priority",
                "priority 5 is best-effort but a max_latency_ms guarantee was given; "
                "raise the priority or drop the latency bound",
                "semantic",
            )
        )

    return errors


def validate(doc: Any) -> ValidationResult:
    """
    Validate one already-parsed intent document.

    Never raises on bad input. Returns a ValidationResult whose `errors` list is
    empty if and only if `ok` is True.
    """
    if not isinstance(doc, dict):
        return ValidationResult(
            ok=False,
            errors=[
                ValidationError(
                    "(root)", f"expected a mapping, got {type(doc).__name__}"
                )
            ],
        )

    schema_errors = [
        ValidationError(_json_path(e), e.message)
        for e in sorted(_VALIDATOR.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]
    if schema_errors:
        return ValidationResult(ok=False, errors=schema_errors)

    semantic_errors = _semantic_checks(doc)
    if semantic_errors:
        return ValidationResult(ok=False, errors=semantic_errors)

    return ValidationResult(ok=True, intent=doc["intent"])


def validate_yaml(text: str) -> ValidationResult:
    """Parse YAML then validate. Malformed YAML is an error, not a crash."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return ValidationResult(
            ok=False,
            errors=[ValidationError("(root)", f"invalid YAML: {exc}", "schema")],
        )
    return validate(doc)


def validate_file(path: str | Path) -> ValidationResult:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return ValidationResult(
            ok=False, errors=[ValidationError("(file)", str(exc), "schema")]
        )
    return validate_yaml(text)
