#!/usr/bin/env bash

set -euo pipefail

# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/task-common.sh"

task_summary_start "Lint"

task_summary_run "uv sync --locked" uv sync --locked

task_summary_run "prek run --all-files (pre-commit)" prek run --all-files --stage pre-commit
task_summary_run "prek run --all-files (pre-push)" prek run --all-files --stage pre-push

task_summary_print
