#!/usr/bin/env bash
# Bring up Open vSwitch inside the container, then hand over to the command.
set -euo pipefail

if [ ! -f /etc/openvswitch/conf.db ]; then
    ovsdb-tool create /etc/openvswitch/conf.db /usr/share/openvswitch/vswitch.ovsschema
fi

mkdir -p /var/run/openvswitch
ovsdb-server /etc/openvswitch/conf.db \
    --remote=punix:/var/run/openvswitch/db.sock \
    --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
    --pidfile --detach --log-file
ovs-vsctl --no-wait init
ovs-vswitchd --pidfile --detach --log-file

# Mininet leaves stale namespaces around after an unclean exit.
mn -c >/dev/null 2>&1 || true

exec "$@"
