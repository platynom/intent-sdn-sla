#!/usr/bin/env bash
set -euo pipefail

# flow_table_pilot.sh – thin wrapper that invokes the Python driver.
# Generates dummy flows on s1, sweeps flow‑limit, records metrics, prints verdict.
# Writes CSV to experiments/results/raw/flow_table_pilot_<timestamp>.csv

RESULT_DIR="experiments/results/raw"
mkdir -p "${RESULT_DIR}"
TIMESTAMP=$(date +"%Y%m%d%H%M%S")
CSV_FILE="${RESULT_DIR}/flow_table_pilot_${TIMESTAMP}.csv"

# Run the driver which prints CSV rows and a verdict line.
python -m experiments.scenarios._driver flowpilot > "${CSV_FILE}"

echo "Flow‑table pilot results written to ${CSV_FILE}"
