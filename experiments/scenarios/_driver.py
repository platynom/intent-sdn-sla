#!/usr/bin/env python3
"""Driver for experiment scripts.
Provides two subcommands:
  baseline --runs N   Run the B0 baseline measurement.
  flowpilot           Run the flow‑table pressure pilot.
Both commands print CSV rows to stdout with columns:
run_id,timestamp,metric,value,unit (or appropriate for flowpilot).
"""
import argparse
import sys
import time
import csv
from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.link import TCLink
from topology.team16_topo import Team16Topo

def set_static_forwarding(net):
    """Configure each switch for standalone learning (no controller)."""
    for sw in net.switches:
        sw.cmd(f"ovs-vsctl set-fail-mode {sw.name} standalone")

def parse_ping(ping_output):
    # loss percentage
    loss_line = [line for line in ping_output.splitlines() if "packet loss" in line]
    loss = 0
    if loss_line:
        part = loss_line[0].split(',')[2].strip()
        loss = part.split('%')[0]
    # rtt stats line
    stats_line = [line for line in ping_output.splitlines() if "rtt min/avg/max/mdev" in line]
    rtt_vals = ("0","0","0","0")
    if stats_line:
        stats = stats_line[0].split('=')[1].strip().split('/')
        rtt_vals = tuple(v.strip() for v in stats)
        # Strip trailing ' ms' from the mdev entry (fourth element)
        rtt_vals = (rtt_vals[0], rtt_vals[1], rtt_vals[2], rtt_vals[3].split()[0])
    return loss, rtt_vals

def baseline(runs):
    net = Mininet(topo=Team16Topo(), switch=OVSSwitch, link=TCLink, controller=None)
    net.start()
    set_static_forwarding(net)
    h1 = net.get('h1')
    h2 = net.get('h2')
    for i in range(1, runs+1):
        ts = int(time.time())
        # ping
        ping_out = h1.cmd('ping -c 100 -i 0.1 10.0.0.2')
        loss, (rtt_min, rtt_avg, rtt_max, rtt_mdev) = parse_ping(ping_out)
        # iperf3 server in background
        h2.cmd('iperf3 -s -1 &')
        time.sleep(1)
        iperf_out = h1.cmd('iperf3 -c 10.0.0.2 -t 30 -f m')
        # extract throughput (Mbits/sec) from last line
        thr = '0'
        for line in iperf_out.splitlines():
            if 'Mbits/sec' in line:
                thr = line.split()[-2]
        # output csv rows
        writer = csv.writer(sys.stdout)
        writer.writerow([i, ts, 'loss', loss, '%'])
        writer.writerow([i, ts, 'rtt_min', rtt_min, 'ms'])
        writer.writerow([i, ts, 'rtt_avg', rtt_avg, 'ms'])
        writer.writerow([i, ts, 'rtt_max', rtt_max, 'ms'])
        writer.writerow([i, ts, 'rtt_mdev', rtt_mdev, 'ms'])
        writer.writerow([i, ts, 'throughput', thr, 'Mbits/s'])
    net.stop()

def flowpilot():
    net = Mininet(topo=Team16Topo(), switch=OVSSwitch, link=TCLink, controller=None)
    net.start()
    set_static_forwarding(net)
    s1 = net.get('s1')
    limits = ["100", "500", "1000", "2000", "5000", "unlimited"]
    requested = 2000
    enforceable = False
    writer = csv.writer(sys.stdout)
    writer.writerow(['limit','requested_rules','installed_rules','rejected','install_seconds'])
    for lim in limits:
        # Clean any existing Flow_Table rows before setting new limit
        s1.cmd("ovs-vsctl -- --all destroy Flow_Table")
        s1.cmd("ovs-vsctl clear bridge {s1.name} flow_tables")
        if lim != "unlimited":
            # set OpenFlow flow table limit
            s1.cmd(f"ovs-vsctl -- set bridge {s1.name} flow_tables:0=@t -- --id=@t create Flow_Table flow_limit={lim} overflow_policy=refuse")
        else:
            s1.cmd(f"ovs-vsctl clear bridge {s1.name} flow_tables")
        # create dummy flow file
        flow_file = '/tmp/dummy_flows.txt'
        with open(flow_file, 'w') as f:
            for _ in range(requested):
                f.write('priority=1,ipv4,actions=drop\n')
        start = time.time()
        result = s1.cmd(f"ovs-ofctl add-flows {s1.name} {flow_file}")
        end = time.time()
        rejected = 'yes' if 'error' in result.lower() else 'no'
        installed = int(s1.cmd(f"ovs-ofctl dump-flows {s1.name} | grep -c 'cookie='").strip())
        install_secs = f"{end - start:.3f}"
        writer.writerow([lim, requested, installed, rejected, install_secs])
        if lim != "unlimited" and installed < requested:
            enforceable = True
        # clean up flow table rows to avoid accumulation
        s1.cmd(f"ovs-ofctl del-flows {s1.name}")
    # verdict line printed to stdout after CSV (not part of CSV)
    verdict = ("VERDICT: flow-table limit is enforceable - metric E5 is viable"
               if enforceable else
               "VERDICT: flow-table limit had no effect - metric E5 will be flat, see ADR-003")
    print(verdict)

def main():
    parser = argparse.ArgumentParser(description='Experiment driver')
    subparsers = parser.add_subparsers(dest='cmd')
    baseline_parser = subparsers.add_parser('baseline', help='Run B0 baseline')
    baseline_parser.add_argument('--runs', type=int, default=10, help='Number of runs')
    subparsers.add_parser('flowpilot', help='Run flow‑table pressure pilot')
    args = parser.parse_args()
    if args.cmd == 'baseline':
        baseline(args.runs)
    elif args.cmd == 'flowpilot':
        flowpilot()
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()
