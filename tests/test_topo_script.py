"""
Acceptance tests for `topology/team16_topo.py` itself.

Added after the first ST-2 review: the original suite only exercised
`topology_spec.py`, so a topology script that crashed on every run still showed a
green test suite. These tests close that hole.

They must pass on a machine with **no Mininet installed**, so they exercise only the
parts that do not need it: import safety, formatting helpers, and the guarantee that
a missing Mininet is loud rather than silent.
"""

from __future__ import annotations

import importlib
import io
import contextlib

import pytest

MODULE = "topology.team16_topo"


def _mod():
    return importlib.import_module(MODULE)


def test_module_imports_without_mininet():
    """The unit suite runs outside the container, so import must not explode."""
    mod = _mod()
    assert hasattr(mod, "Team16Topo")


def test_exposes_mininet_availability_flag():
    mod = _mod()
    assert isinstance(mod.MININET_AVAILABLE, bool)


@pytest.mark.skipif(
    getattr(_mod(), "MININET_AVAILABLE", False),
    reason="Mininet is installed; the absent-Mininet contract does not apply",
)
def test_constructing_without_mininet_raises_loudly():
    """
    A topology object that silently builds nothing is worse than a crash: the
    network comes up empty and the failure surfaces much later, somewhere else.
    Constructing without Mininet must raise.
    """
    mod = _mod()
    with pytest.raises(Exception) as exc:
        mod.Team16Topo()
    assert "mininet" in str(exc.value).lower(), (
        "the error must name Mininet so the cause is obvious from the message alone"
    )


def test_link_summary_does_not_crash_on_float_budgets():
    """
    Regression test. Bandwidths and delays in topology_spec are floats (100.0, 2.0).
    Formatting them with an integer format code raises ValueError at runtime, after
    the network has already started.
    """
    mod = _mod()
    fn = getattr(mod, "_print_link_summary", None)
    if fn is None:
        pytest.skip("no _print_link_summary helper in this implementation")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()  # must not raise


def test_link_summary_mentions_every_link():
    mod = _mod()
    fn = getattr(mod, "_print_link_summary", None)
    if fn is None:
        pytest.skip("no _print_link_summary helper in this implementation")

    from topology.topology_spec import LINKS

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    out = buf.getvalue()
    for link in LINKS:
        assert link.name in out, f"{link.name} missing from the link summary"


def test_topology_is_built_from_the_spec_not_hard_coded():
    """
    Cheap structural guard: the script must not contain literal topology values.
    Everything comes from topology_spec.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "topology" / "team16_topo.py").read_text(
        encoding="utf-8"
    )
    code_lines = [
        ln for ln in src.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    code = "\n".join(code_lines)

    for forbidden in ('"10.0.0.', "'10.0.0.", '"s1"', "'s1'"):
        assert forbidden not in code, (
            f"{forbidden!r} is hard-coded in team16_topo.py; "
            "topology data must come from topology_spec"
        )


def test_registers_a_mininet_custom_topo_entry():
    """`sudo mn --custom topology/team16_topo.py --topo team16` must work."""
    mod = _mod()
    assert hasattr(mod, "topos"), "missing the `topos` dict Mininet's --custom expects"
    assert "team16" in mod.topos
    assert callable(mod.topos["team16"])
