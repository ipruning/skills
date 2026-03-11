#!/usr/bin/env bash
#MISE description="运行格式化"

# shellcheck source=_task.sh
source "$(dirname "$0")/_task.sh"

task_summary_start "Format"

task_summary_run "uv sync --python 3.13 --frozen" uv sync --python 3.13 --frozen

task_summary_run "ruff format ." uv run ruff format .

task_summary_run "ruff check . --fix" uv run ruff check . --fix

task_summary_run "tombi format ." uvx tombi format .

task_summary_run "biome format . --write" biome format . --write

task_summary_run "autocorrect --fix ." autocorrect --fix . .agents/ .mise/

if [[ "${CI:-}" == "true" ]]; then
    task_summary_run "working tree clean" bash -c 'git diff --exit-code'
fi

task_summary_print
