"""
Eight-host, seven-switch topology with three link-disjoint paths h1 -> h2.

Three disjoint paths are mandatory: without alternatives there is nothing to
re-plan to and the closed loop is untestable.

Filled in at ST-2. Runs only inside the container (needs root + OVS).
"""
