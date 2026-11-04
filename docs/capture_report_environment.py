"""Collect the runtime versions used by the report inside the SDN container."""
import importlib.metadata
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from mininet.net import VERSION


def main():
    evidence = {
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "ryu": importlib.metadata.version("ryu"),
        "mininet": VERSION,
        "ovs": subprocess.check_output(["ovs-vsctl", "--version"], text=True).splitlines()[0],
        "kernel": platform.release(),
    }
    path = Path("docs/report_assets/environment.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
