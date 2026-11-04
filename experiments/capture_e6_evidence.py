"""Preserve the completed accounting rerun's real logs before container recreation."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


def main():
    raw = Path("experiments/results/raw")
    runs = sorted(raw.glob("e6accounting_oscillation_b2_*.csv"))
    if len(runs) != 10:
        raise RuntimeError(f"Expected ten completed accounting runs, found {len(runs)}")
    destination = Path("docs/demo_assets/e6_accounting")
    destination.mkdir(parents=True, exist_ok=True)
    output = []
    for path in runs:
        with path.open(newline="") as stream:
            metrics = {row["metric"]: float(row["value"]) for row in csv.DictReader(stream)}
        if metrics["duration_s"] != 600 or metrics["measurement_count"] != 600:
            raise RuntimeError(f"Incomplete requested measurement window: {path}")
        if metrics["raw_reroute_count"] != metrics["violations_emitted"]:
            raise RuntimeError(f"Unreconciled event accounting: {path}")
        output.append({"file": path.name, "metrics": metrics})
    copied = []
    persistence_errors = []
    log_paths = [Path(f"/var/log/team16/telemetry-e6-b2-{index}.log")
                 for index in range(1, 11)]
    log_paths += [Path("/var/log/team16/ryu-e6.log"), Path("/var/log/team16/api-e6.log")]
    pattern = re.compile(r"database is locked|database is busy|sqlite\w*\.(?:Operational|Integrity)Error|Traceback", re.I)
    for source in log_paths:
        target = destination / source.name
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise RuntimeError(f"Refusing to overwrite different retained log {target}")
        shutil.copyfile(source, target)
        copied.append({"file": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        for line in target.read_text(encoding="utf-8").splitlines():
            if pattern.search(line):
                persistence_errors.append({"file": str(target), "line": line})
    snapshots = []
    for path in sorted(Path("experiments/results/diagnostics").glob("e6accounting_*_accounting.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not payload["reconciles_with_csv"]:
            raise RuntimeError(f"Observer missed a reset boundary: {path}")
        snapshots.append({"file": str(path), "full_event_counts": payload["full_event_counts"],
                          "latest_200_counts": payload["latest_200_counts"],
                          "path_count": payload["path_count"],
                          "measurement_count": payload["measurement_count"]})
    payload = {"captured_utc": datetime.now(timezone.utc).isoformat(), "runs": output,
               "logs": copied, "persistence_error_matches": persistence_errors,
               "observer_snapshots": snapshots,
               "historical_limit": "These logs describe the new rerun, not the unretained original early runs."}
    (destination / "evidence.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for row in output:
        values = row["metrics"]
        print(f"{row['file']}: paths={values['raw_reroute_count']:g}, "
              f"violations={values['violations_emitted']:g}, samples={values['measurement_count']:g}")
    print(f"Preserved {len(copied)} real logs and {len(snapshots)} read-only snapshots")
    print(f"Persistence-error/traceback matches: {len(persistence_errors)}")
    if persistence_errors:
        raise RuntimeError("Inspect retained error matches before accepting this rerun")


if __name__ == "__main__":
    main()
