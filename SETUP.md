# Setup and teammate handover

This guide takes a new contributor from one downloaded zip to the software-only
demonstration and test suite. Start with the no-Docker path. Docker is needed only
when you are ready to run Mininet, Open vSwitch and Ryu as a live network.

## 1. Install the prerequisites

1. Install [Git](https://git-scm.com/downloads).
2. Install [Python](https://www.python.org/downloads/) 3.9 or newer. Python 3.9 is
   required for Ryu, but Ryu is not required by the software-only workflow.
3. For live-network work only, install
   [Docker Desktop](https://www.docker.com/products/docker-desktop/) on Windows or
   macOS, or [Docker Engine](https://docs.docker.com/engine/install/) on Linux.
4. Windows live-network users must enable
   [WSL2](https://learn.microsoft.com/windows/wsl/install). Mininet uses Linux
   network namespaces and cannot run directly in Windows.

Check the tools:

```text
git --version
python --version
docker --version
```

Git and Python should print version numbers. Docker may be absent if you are doing
only software development.

## 2. Obtain the repository

### Option A: unzip the Google Drive release

Download `intent-sdn-sla_YYYYMMDD.zip`, then extract it. Replace `YYYYMMDD` with
the date in the downloaded filename.

Linux, macOS or WSL:

```bash
unzip intent-sdn-sla_YYYYMMDD.zip -d intent-sdn-sla
cd intent-sdn-sla
```

Windows PowerShell:

```powershell
Expand-Archive .\intent-sdn-sla_YYYYMMDD.zip -DestinationPath .\intent-sdn-sla
Set-Location .\intent-sdn-sla
```

### Option B: clone from GitHub

This checkout currently has no Git remote configured, so obtain the real URL from
the team instead of guessing it:

```bash
git clone TEAM_GITHUB_REPOSITORY_URL intent-sdn-sla
cd intent-sdn-sla
```

In either case, verify that `README.md`, `Dockerfile`, `requirements.txt`, `src/`,
`topology/` and `tests/` are present.

## 3. No-Docker path - use this first

This path works on Windows, macOS and Linux. It requires no root access and no
Docker. It exercises intent validation, path computation, the REST API and the
ST-6 detector. A contributor can be fully productive on ST-7 using only this path.

Create the environment and install the pinned dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate with:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

Run the verifier, tests and demonstration:

```bash
python tools/verify_setup.py
python -m pytest tests -q
python demo_st4.py
```

Correct output includes:

```text
217 passed
Setup OK - you can start on ST-7
validation : accepted
chosen path: s1 -> s2 -> s3 -> s7
```

The precise demo computation time varies by machine. The selected path and the
accepted/rejected decisions should not vary.

## 4. Docker path - needed only for a live network

Run these commands from Linux, macOS or a WSL2-backed Docker Desktop installation:

```bash
docker compose build
docker compose up -d
docker compose exec sdn ovs-vsctl --version
docker compose exec sdn python -c "import ryu; print(ryu.version)"
docker compose exec sdn python topology/team16_topo.py --no-cli
```

The expected OVS version begins with `ovs-vsctl (Open vSwitch) 2.17`. The Ryu
command should print its installed version, and the topology command should show
seven switches and then stop cleanly.

The team has **not yet verified this Docker path**. It may fail on its first run.
If it fails, copy the exact command and complete error into an issue; do not hide
or work around it. That failure is the trigger for the documented ONOS fallback
decision in `docs/decisions.md`.

## 5. Run one test file and understand a failure

Run one area while developing:

```bash
python -m pytest tests/test_telemetry.py -v
```

A passing test ends in `PASSED`. For a failure, find the first line beginning
`FAILED`, then read the assertion and the captured output immediately above it.
Re-run only that test with its complete node ID, for example:

```bash
python -m pytest tests/test_telemetry.py::test_counter_reset_skips_interval -v
```

## 6. Branch and review policy

1. Create a branch named `feat/st-NN-short-name`, for example:

   ```bash
   git switch -c feat/st-07-close-loop
   ```

2. Commit the implementation and tests.
3. Open a pull request.
4. Obtain one reviewer approval.
5. Merge only after CI is green.

## 7. The rule that matters

**Never edit or delete a test merely to make it pass.** Tests encode the project
plan. Fix the production source. If a test appears incorrect, raise it with the
team and record the agreed outcome in `docs/decisions.md` before changing it.
