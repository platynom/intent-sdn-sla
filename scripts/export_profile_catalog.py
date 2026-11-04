"""Export checked profile/configuration data for dependency-light report builds."""
import hashlib
import json
from pathlib import Path

from src.intent_manager.profiles import CATALOG, list_profiles
from topology.topology_spec import path_bottleneck_mbps, path_delay_ms

ROOT = Path(__file__).resolve().parents[1]


def main():
    routes = {}
    for name, switches in (("north", ["s1", "s2", "s3", "s7"]),
                           ("middle", ["s1", "s4", "s5", "s7"]),
                           ("south", ["s1", "s6", "s7"])):
        routes[name] = {"switches": switches, "delay_ms": path_delay_ms(switches),
                        "bandwidth_mbps": path_bottleneck_mbps(switches)}
    profiles = list_profiles()
    for profile in profiles:
        profile["feasibility"] = {
            method: {name: route["delay_ms"] <= profile[f"transport_target_{method}_ms"]
                     and (profile["min_bandwidth_mbps"] is None
                          or route["bandwidth_mbps"] >= profile["min_bandwidth_mbps"])
                     for name, route in routes.items()}
            for method in ("a", "b")
        }
    source_paths = [CATALOG, ROOT / "src/intent_manager/profiles.py", ROOT / "topology/topology_spec.py"]
    payload = {"kind": "standards-derived configuration and calculated feasibility, not measurements",
               "source_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(
                   path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for path in source_paths},
               "profiles": profiles, "routes": routes}
    target = ROOT / "docs/report_assets/service_profiles.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("Exported docs/report_assets/service_profiles.json from catalogue and topology")


if __name__ == "__main__":
    main()
