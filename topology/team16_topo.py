#!/usr/bin/env python3
"""Team16 topology built from topology_spec.

This module can be imported without Mininet installed; all Mininet imports are
guarded so the test suite (which only uses topology_spec) can import the package
on a plain Python environment.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Mininet imports – guarded to keep the module importable without Mininet.
# ---------------------------------------------------------------------------
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
    class _Stub:
        def __call__(self, *args, **kwargs):
            raise RuntimeError("Mininet is not available in this environment")
    Topo = _Stub
    TCLink = _Stub
    Mininet = _Stub
    RemoteController = _Stub
    OVSSwitch = _Stub
    def CLI(*args, **kwargs):
        """Placeholder CLI – does nothing when Mininet is absent."""
        pass
    def setLogLevel(*args, **kwargs):
        """Placeholder log level setter – no‑op without Mininet."""
        pass
    def info(msg):
        """Placeholder for mininet.log.info – prints to stdout."""
        print(msg)

# Load the single source of truth for the network.
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
        if not MININET_AVAILABLE:
            raise RuntimeError(
                "Mininet is not available in this environment; run this inside the container (docker compose exec sdn ...)"
            )
        super().__init__(*args, **kwargs)
        for sw in SWITCHES:
            self.addSwitch(sw)
        for host in HOSTS:
            ip_cidr = f"{host.ip}/24"
            self.addHost(host.name, ip=ip_cidr)
            self.addLink(host.name, host.switch)
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
    """Print a compact table of each switch‑to‑switch link and its budget.
    Floats are displayed with one decimal place.
    """
    # Use stdout directly so the summary is capturable in automation as well as
    # visible in the interactive Mininet console. Mininet's info() logger binds
    # its output stream at import time and bypasses redirect_stdout.
    print("\nLink summary (name        bw_Mbps  delay_ms)")
    for link in LINKS:
        print(f"{link.name:12s}  {link.bw_mbps:7.1f}  {link.delay_ms:8.1f}")


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
        # autoStaticArp=False  # ARP will be handled by the SDN controller.
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

# Register the topology for ``mn --custom`` usage.
topos = {"team16": (lambda: Team16Topo())}

if __name__ == "__main__":
    main()
