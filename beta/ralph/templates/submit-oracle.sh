#!/bin/bash
# Submit run-oracle.sh to pueue and write tracking env file.
#
# Usage:
#   bash ./templates/submit-oracle.sh WORK_DIR OUT GROUP
#
# Outputs: $WORK_DIR/pueue-env.txt with GROUP and PUEUE_ID.
set -euo pipefail

WORK_DIR="${1:?Usage: submit-oracle.sh WORK_DIR OUT GROUP}"
OUT="${2:?Usage: submit-oracle.sh WORK_DIR OUT GROUP}"
GROUP="${3:?Usage: submit-oracle.sh WORK_DIR OUT GROUP}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$SCRIPT_DIR/run-oracle.sh" "$WORK_DIR/run-oracle.sh"
chmod +x "$WORK_DIR/run-oracle.sh"

pueue status &>/dev/null || pueued -d

pueue group add "$GROUP" 2>/dev/null || true
PUEUE_ID=$(pueue add --group "$GROUP" --print-task-id -- \
  env WORK_DIR="$WORK_DIR" OUT="$OUT" bash "$WORK_DIR/run-oracle.sh")
printf 'GROUP=%s\nPUEUE_ID=%s\n' "$GROUP" "$PUEUE_ID" > "$WORK_DIR/pueue-env.txt"
echo "submitted group=$GROUP task=$PUEUE_ID"
