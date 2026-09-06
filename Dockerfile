# Team 16 - Intent-Based SDN for 5G SLA Enforcement
# Pinned per ADR-001. Do not bump these versions without a whole-team decision.
#
# Why Python 3.9: Ryu 4.34 depends on eventlet, which breaks on Python 3.10+
# (the `ssl.wrap_socket` removal). Pinning inside the container means the host
# Python is irrelevant. Never pip install ryu on the host.
FROM ubuntu:22.04

ARG PYTHON_VERSION=3.9.25
ARG MININET_VERSION=2.3.1b4
ARG MININET_COMMIT=88f14e946a05cd0895e1a127bf89da9b3fb1d98b

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/usr/lib/python3/dist-packages

# ---- system packages -------------------------------------------------------
# Deadsnakes no longer publishes Python 3.9 for Ubuntu 22.04. Building the
# final upstream 3.9 source release keeps OVS 2.17 from Jammy while retaining
# the interpreter required by Ryu 4.34.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git sudo \
        openvswitch-switch openvswitch-common \
        mininet iproute2 iputils-ping net-tools tcpdump iperf3 \
        build-essential pkg-config xz-utils \
        libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
        libsqlite3-dev libffi-dev liblzma-dev libgdbm-dev uuid-dev \
    && curl -fsSLO "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tar.xz" \
    && tar -xf "Python-${PYTHON_VERSION}.tar.xz" \
    && cd "Python-${PYTHON_VERSION}" \
    && ./configure --with-ensurepip=install \
    && make -j"$(nproc)" \
    && make altinstall \
    && cd / \
    && curl -fsSL \
        "https://github.com/mininet/mininet/archive/${MININET_COMMIT}.tar.gz" \
        -o mininet.tar.gz \
    && tar -xzf mininet.tar.gz \
    && python3.9 -m pip install --no-cache-dir --no-deps \
        "/mininet-${MININET_COMMIT}" \
    && test "$(python3.9 -c 'import mininet.net; print(mininet.net.VERSION)')" = "${MININET_VERSION}" \
    && rm -rf "mininet-${MININET_COMMIT}" mininet.tar.gz \
    && rm -rf "Python-${PYTHON_VERSION}" "Python-${PYTHON_VERSION}.tar.xz" \
    && rm -rf /var/lib/apt/lists/*

# make python3.9 the default python inside the container
RUN python3.9 -m pip install --no-cache-dir \
        pip==23.0.1 setuptools==58.2.0 wheel==0.38.4 \
    && update-alternatives --install /usr/bin/python python /usr/local/bin/python3.9 1 \
    && sed -i '1s|^#!python$|#!/usr/local/bin/python3.9|' /usr/local/bin/mn \
    && test "$(head -n 1 /usr/local/bin/mn)" = "#!/usr/local/bin/python3.9"

# ---- python dependencies ---------------------------------------------------
COPY requirements.txt /tmp/requirements.txt
# Ryu's setup hook calls setuptools' legacy easy_install.get_script_args.
# Disable build isolation so the compatible setuptools pin above is respected.
RUN python3.9 -m pip install --no-cache-dir --no-deps --no-build-isolation --no-use-pep517 ryu==4.34 \
    && python3.9 -m pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY . /app

# OVS needs its databases initialised before ovs-vswitchd will start.
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["bash"]
