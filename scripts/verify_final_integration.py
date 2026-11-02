"""Record final verification inside the SDN container.

Run one phase at a time. Do not run smoke/regression while E6 is active.
Generated text is verbatim subprocess output, not a drawn terminal image.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("software", "api", "smoke", "regression"))
    args = parser.parse_args()
    os.chdir(ROOT)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = ROOT / "docs/demo_assets"
    output_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="safe.directory", GIT_CONFIG_VALUE_0=str(ROOT))
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], env=env, text=True).strip()
    diff = subprocess.check_output(["git", "diff", "HEAD", "--binary"], env=env)
    diff_hash = hashlib.sha256(diff).hexdigest()
    records = []

    def run(label, argv, extra_env=None, capture_switch=False):
        process_env = dict(env)
        process_env.update(extra_env or {})
        process = subprocess.Popen(argv, env=process_env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        if capture_switch:
            deadline = time.monotonic() + 30
            while process.poll() is None and time.monotonic() < deadline:
                flow_argv = ["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", "s1"]
                flow = subprocess.run(flow_argv, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, check=False)
                if flow.returncode == 0 and "set_queue:" in flow.stdout:
                    flow_path = output_dir / f"{stamp}_{label}_flow_dump.txt"
                    flow_header = (f"Captured UTC: {datetime.now(timezone.utc).isoformat()}\n"
                                   f"Code revision: {revision}\nCommand argv: {json.dumps(flow_argv)}\n"
                                   f"Exit status: {flow.returncode}\n\n")
                    flow_path.write_text(flow_header + flow.stdout, encoding="utf-8")
                    records.append({"label": f"{label}_flow_dump", "file": str(flow_path.relative_to(ROOT)),
                                    "exit_status": flow.returncode})
                    break
                time.sleep(0.25)
        stdout, _ = process.communicate()
        path = output_dir / f"{stamp}_{label}.txt"
        header = (f"Captured UTC: {stamp}\nCode revision: {revision}\n"
                  f"Tracked worktree diff SHA-256: {diff_hash}\n"
                  f"Command argv: {json.dumps(argv)}\nExit status: {process.returncode}\n\n")
        path.write_text(header + stdout, encoding="utf-8")
        print(header + stdout, flush=True)
        records.append({"label": label, "file": str(path.relative_to(ROOT)),
                        "exit_status": process.returncode})
        if process.returncode:
            raise SystemExit(process.returncode)
        return stdout

    if args.phase == "software":
        run("pytest", ["python3.9", "-m", "pytest", "tests", "-q"])
        run("ruff", ["ruff", "check", "src", "tests", "topology", "experiments"])
        run("summaries", ["python3.9", "experiments/verify_summaries.py"])
        run("planning_demo", ["python3.9", "demo_st4.py"])
    elif args.phase == "api":
        # Run this phase in the intent-api service (Compose bridge network).
        rejection = run("invalid_intent", [
            "curl", "-sS", "-i", "-X", "POST", "http://127.0.0.1:8000/intent",
            "-H", "Content-Type: text/plain", "--data-binary", "@intents/invalid/bad_sixth_constraint.yaml",
        ])
        if "422 Unprocessable Entity" not in rejection:
            raise RuntimeError("invalid intent did not receive the expected HTTP 422")
        dashboard = run("dashboard_api", ["curl", "-sS", "http://dashboard:8080/api/dashboard"])
        intents = {row["id"]: row for row in json.loads(dashboard)["intents"]}
        for intent_id in ("INT-010", "INT-011", "INT-012", "INT-013"):
            if intent_id not in intents or intents[intent_id]["telemetry_source"] not in ("simulated", "live"):
                raise RuntimeError(f"missing or unlabelled dashboard intent {intent_id}")
    elif args.phase == "smoke":
        for label, path, flags in (
            ("s1", "s1_single_intent.sh", ""),
            ("st7", "s1_single_intent.sh", "--st7"),
            ("st9", "s9_preemption.sh", ""),
            ("st10", "s10_two_phase.sh", ""),
            ("b3_demo", "s1_single_intent.sh", "--b3"),
        ):
            database = str(Path(tempfile.mkdtemp(prefix=f"team16-{label}-")) / "state.db")
            command = f"set -o pipefail; sed 's/\\r$//' experiments/scenarios/{path} | bash -s -- {flags}"
            run(label, ["bash", "-lc", command],
                {"TEAM16_DB_PATH": database, "TEAM16_RESULT_TAG": "regression_demo_b3"},
                capture_switch=label == "s1")
            run(f"{label}_audit", ["python3.9", "scripts/show_demo_audit.py"],
                {"TEAM16_DB_PATH": database})
    else:
        raw = ROOT / "experiments/results/raw"
        before = set(raw.glob("regression_merge_*.csv"))
        for mode in ("b2", "b3"):
            database = str(Path(tempfile.mkdtemp(prefix=f"team16-e4-{mode}-")) / "state.db")
            command = ("set -o pipefail; sed 's/\\r$//' experiments/scenarios/e4_packet_loss.sh "
                       f"| bash -s -- --mode {mode} --runs 1")
            run(f"e4_{mode}", ["bash", "-lc", command],
                {"TEAM16_DB_PATH": database, "E4_RESULT_PREFIX": "regression_merge"})
        new_files = sorted(set(raw.glob("regression_merge_*.csv")) - before)
        if len(new_files) != 2:
            raise RuntimeError(f"expected two regression CSV files, found {new_files}")
        summary = ROOT / "experiments/results/summary/e4_current_packet_loss_summary.csv"
        with summary.open(newline="") as stream:
            published = {(r["group"], r["metric"]): (float(r["min"]), float(r["max"]))
                         for r in csv.DictReader(stream)}
        comparisons = []
        for path in new_files:
            group = "B2" if "_b2_" in path.name else "B3"
            with path.open(newline="") as stream:
                values = {r["metric"]: float(r["value"]) for r in csv.DictReader(stream)}
            for metric in ("packets_lost", "packets_reordered"):
                low, high = published[(group, metric)]
                value = values[metric]
                comparisons.append({"file": path.name, "group": group, "metric": metric,
                                    "value": value, "published_min": low, "published_max": high,
                                    "within_published_range": low <= value <= high})
        result_path = output_dir / f"{stamp}_e4_regression_comparison.json"
        result_path.write_text(json.dumps(comparisons, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(comparisons, indent=2))
        if not all(row["within_published_range"] for row in comparisons):
            raise RuntimeError("merged E4 regression fell outside a published range; inspect the retained evidence")
    (output_dir / f"{stamp}_{args.phase}_index.json").write_text(
        json.dumps({"revision": revision, "captured_utc": stamp, "commands": records}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
