r"""
Single source of truth for the test topology.

Both the Mininet script (topology/team16_topo.py) and the unit tests
(tests/test_topology.py) import from here, so the graph the tests reason about is
by construction the graph Mininet builds. Nothing else may hard-code an edge.

This module is pure Python with no Mininet import, so it runs anywhere.

--------------------------------------------------------------------------------
INTERPRETATION NOTE  (raised at ST-2, resolved here)

The project plan draws the topology as ASCII art and lists tc budgets for six
links only. The art is ambiguous about two edges: whether the bottom rail closes
s6-s7, and whether the right-hand column closes s3-s7. Without both, only one
path exists from s1 and the plan's own claim of "three disjoint h1->h2 paths:
via s2, via s4-s5, via s6" cannot hold.

We therefore read the topology as below, which is the reading that makes the
plan's disjoint-path claim true. The two inferred edges are marked `inferred`
and inherit the budget of the link they continue. test_topology.py proves the
three disjoint paths exist rather than assuming it.
--------------------------------------------------------------------------------

            h1  h3                h5                 h7
              \  |                 |                  |
            [ s1 ]---------------[ s2 ]-------------[ s3 ]
              | \                                       |
              |  \---[ s4 ]---[ s5 ]                    |
              |        |         |                      |
            [ s6 ]-----+---------+--------------------[ s7 ]
              |                                        |  \
              h6                                      h2   h8
"""

from __future__ import annotations

from dataclasses import dataclass

SWITCHES: tuple[str, ...] = ("s1", "s2", "s3", "s4", "s5", "s6", "s7")


@dataclass(frozen=True)
class Link:
    """One bidirectional switch-to-switch link and its tc/HTB budget."""

    a: str
    b: str
    bw_mbps: float
    delay_ms: float
    inferred: bool = False  # not given a budget in the plan; see note above

    @property
    def name(self) -> str:
        """Canonical `sX-sY` identifier, lower-numbered switch first.

        Matches the `avoid_links` grammar in the intent schema.
        """
        lo, hi = sorted((self.a, self.b), key=lambda s: int(s[1:]))
        return f"{lo}-{hi}"


# The three routes from s1 to s7, and the links each one uses:
#   via s2      : s1-s2, s2-s3, s3-s7
#   via s4-s5   : s1-s4, s4-s5, s5-s7
#   via s6      : s1-s6, s6-s7
LINKS: tuple[Link, ...] = (
    # --- northern route, high bandwidth, low delay ---
    Link("s1", "s2", 100.0, 2.0),
    Link("s2", "s3", 100.0, 2.0),
    Link("s3", "s7", 100.0, 2.0, inferred=True),   # continues the s2-s3 rail
    # --- middle route, medium bandwidth and delay ---
    Link("s1", "s4", 50.0, 5.0),
    Link("s4", "s5", 50.0, 5.0),
    Link("s5", "s7", 50.0, 5.0),
    # --- southern route, low bandwidth, high delay ---
    Link("s1", "s6", 40.0, 12.0),
    Link("s6", "s7", 40.0, 12.0, inferred=True),   # continues the s1-s6 rail
)


@dataclass(frozen=True)
class Host:
    name: str
    ip: str
    switch: str
    role: str


# IPs are 10.0.0.<n> for h<n>, matching Mininet's default allocation and the
# addresses used in intents/*.yaml. Do not renumber without updating both.
HOSTS: tuple[Host, ...] = (
    Host("h1", "10.0.0.1", "s1", "URLLC source"),
    Host("h2", "10.0.0.2", "s7", "URLLC destination"),
    Host("h3", "10.0.0.3", "s4", "cross-traffic source, middle route"),
    Host("h4", "10.0.0.4", "s5", "cross-traffic sink, middle route"),
    Host("h5", "10.0.0.5", "s2", "eMBB source"),
    Host("h6", "10.0.0.6", "s6", "eMBB destination"),
    Host("h7", "10.0.0.7", "s3", "IoT / mMTC source"),
    Host("h8", "10.0.0.8", "s7", "IoT / mMTC destination"),
)

# The pair whose SLA the closed loop protects. Everything in the evaluation is
# measured on this pair, so it is the pair that needs disjoint alternatives.
CRITICAL_PAIR: tuple[str, str] = ("h1", "h2")

# The plan requires at least this many link-disjoint paths between the critical
# pair. Fewer means there is nothing to re-plan to and the loop is untestable.
REQUIRED_DISJOINT_PATHS: int = 3


def host_by_name(name: str) -> Host:
    for h in HOSTS:
        if h.name == name:
            return h
    raise KeyError(f"no such host: {name}")


def link_names() -> tuple[str, ...]:
    return tuple(link.name for link in LINKS)


def build_graph():
    """Return a NetworkX graph of the switch fabric.

    Imported lazily so that this module stays dependency-free for the Mininet
    script, which does not need NetworkX.
    """
    import networkx as nx

    g = nx.Graph()
    g.add_nodes_from(SWITCHES)
    for link in LINKS:
        g.add_edge(
            link.a,
            link.b,
            name=link.name,
            bw_mbps=link.bw_mbps,
            delay_ms=link.delay_ms,
            inferred=link.inferred,
        )
    return g


def path_delay_ms(switch_path: list[str]) -> float:
    """Sum of one-way link delays along a switch path. Ignores host access links."""
    budgets = {link.name: link.delay_ms for link in LINKS}
    total = 0.0
    for a, b in zip(switch_path, switch_path[1:]):
        lo, hi = sorted((a, b), key=lambda s: int(s[1:]))
        total += budgets[f"{lo}-{hi}"]
    return total


def path_bottleneck_mbps(switch_path: list[str]) -> float:
    """Narrowest link along a switch path, i.e. the most bandwidth it can carry."""
    budgets = {link.name: link.bw_mbps for link in LINKS}
    caps = []
    for a, b in zip(switch_path, switch_path[1:]):
        lo, hi = sorted((a, b), key=lambda s: int(s[1:]))
        caps.append(budgets[f"{lo}-{hi}"])
    return min(caps) if caps else float("inf")
