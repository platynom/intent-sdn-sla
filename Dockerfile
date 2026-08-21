# Team 16 - Intent-Based SDN for 5G SLA Enforcement
# Pinned per ADR-001. Do not bump these versions without a whole-team decision.
#
# Why Python 3.9: Ryu 4.34 depends on eventlet, which breaks on Python 3.10+
# (the `ssl.wrap_socket` removal). Pinning inside the container means the host
# Python is irrelevant. Never pip install ryu on the host.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ---- system packages -------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates curl git sudo \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.9 python3.9-dev python3.9-distutils \
        openvswitch-switch openvswitch-common \
        mininet iproute2 iputils-ping net-tools tcpdump iperf3 \
        build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*

# make python3.9 the default python inside the container
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.9 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.9 1

# ---- python dependencies ---------------------------------------------------
COPY requirements.txt /tmp/requirements.txt
RUN python3.9 -m pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY . /app

# OVS needs its databases initialised before ovs-vswitchd will start.
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash"]
