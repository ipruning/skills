#!/usr/bin/env bash

set -euo pipefail

# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/task-common.sh"

task_summary_start "Format"

task_summary_run "uv sync --locked" uv sync --locked

task_summary_run "ruff format ." uv run --locked ruff format .

task_summary_run "ruff check . --fix" uv run --locked ruff check . --fix

task_summary_run "tombi format ." tombi format .

task_summary_run "biome format . --write" biome format . --write

task_summary_run "autocorrect --fix ." autocorrect --fix .

if [[ "${CI:-}" == "true" ]]; then
    task_summary_run "working tree clean" bash -c 'git diff --exit-code'
fi

task_summary_print
