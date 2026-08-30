#!/usr/bin/env python3
"""Team16 topology built from topology_spec.

This module can be imported without Mininet installed; all Mininet imports are
guarded so the test suite (which only uses topology_spec) can import the package
on a plain Python environment.
"""

from __future__ import annotations

# Guard Mininet imports – they are only required when the script is executed
# inside the Docker container that provides Mininet, OVS and the controller.
try:
    from mininet.topo import Topo
    from mininet.link import TCLink
    from mininet.net import Mininet
    from mininet.node import RemoteController, OVSSwitch
    from mininet.cli import CLI
    from mininet.log import setLogLevel, info
    MININET_AVAILABLE = True
except ImportError:  # pragma: no cover
    MININET_AVAILABLE = False
    # Provide dummy placeholders so type checkers are happy when the module is
    # imported in an environment without Mininet.
    Topo = object  # type: ignore
    TCLink = object  # type: ignore
    Mininet = object  # type: ignore
    RemoteController = object  # type: ignore
    OVSSwitch = object  # type: ignore
    CLI = lambda *a, **kw: None  # type: ignore
    setLogLevel = lambda *a, **kw: None  # type: ignore
    info = print  # type: ignore

# Import the single source of truth for the network.
from topology.topology_spec import SWITCHES, HOSTS, LINKS


class Team16Topo(Topo):
    """Topology generated directly from :pymod:`topology_spec`.

    * Switches are added from ``SWITCHES``.
    * Hosts are added from ``HOSTS`` – each host receives its IP with a ``/24``
      mask as required by the tests.
    * Switch‑to‑switch links use :class:`TCLink` so that bandwidth and delay are
      enforced. ``max_queue_size`` and ``use_htb`` are set according to the
      enforcement module's expectations.
    * Host‑access links are left unconstrained – no ``bw`` or ``delay`` args are
      passed.
    """

    def __init__(self, *args, **kwargs):
        # Initialise the parent ``Topo`` only when Mininet is present.
        if MININET_AVAILABLE:
            super().__init__(*args, **kwargs)
        else:
            return

        # Add all switches.
        for sw in SWITCHES:
            self.addSwitch(sw)

        # Add hosts and attach them to their designated switches.
        for host in HOSTS:
            ip_cidr = f"{host.ip}/24"
            self.addHost(host.name, ip=ip_cidr)
            self.addLink(host.name, host.switch)  # unconstrained host link

        # Add fabric links with bandwidth / delay constraints.
        for link in LINKS:
            self.addLink(
                link.a,
                link.b,
                cls=TCLink,
                bw=link.bw_mbps,
                delay=f"{link.delay_ms}ms",
                max_queue_size=1000,
                use_htb=True,
            )


def _print_link_summary():
    """Print a compact table of each switch‑to‑switch link and its budget."""
    info("\nLink summary (name  bw_Mbps  delay_ms)\n")
    for link in LINKS:
        info(f"{link.name:12s}  {link.bw_mbps:7d}  {link.delay_ms:8d}\n")


def main():  # pragma: no cover
    """Entry point for ``python topology/team16_topo.py``.

    Optional arguments:
    * ``--no-cli`` – run without dropping into the Mininet CLI.
    * ``--controller-ip`` / ``--controller-port`` – remote controller address.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Team16 Mininet topology")
    parser.add_argument("--no-cli", action="store_true", help="skip CLI")
    parser.add_argument("--controller-ip", default="127.0.0.1", help="controller IP")
    parser.add_argument("--controller-port", type=int, default=6653, help="controller port")
    args = parser.parse_args()

    if not MININET_AVAILABLE:
        raise RuntimeError("Mininet is not available in this environment")

    setLogLevel("info")

    net = Mininet(
        topo=Team16Topo(),
        switch=OVSSwitch,
        controller=None,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=True,
    )

    net.addController(
        "c0",
        controller=RemoteController,
        ip=args.controller_ip,
        port=args.controller_port,
    )

    info("*** Starting network\n")
    net.start()

    _print_link_summary()

    info("*** Running pingAll\n")
    net.pingAll()

    if not args.no_cli:
        info("*** Launching Mininet CLI\n")
        CLI(net)

    info("*** Stopping network\n")
    net.stop()


if __name__ == "__main__":
    main()
