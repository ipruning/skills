#!/usr/bin/env bash
#MISE description="运行 Lint 流程"

# shellcheck source=_task.sh
source "$(dirname "$0")/_task.sh"

task_summary_start "Lint"

# uv sync is the only step NOT covered by prek.toml
task_summary_run "uv sync" uv sync --python 3.13 --frozen

# All other checks are configured in prek.toml with priority-based parallelism.
# Running prek instead of serial steps cuts lint time roughly in half.
#
# Checks delegated to prek:
#   ruff format --check, ruff check, ty check, tombi lint,
#   check-no-any-kwargs, biome check, ripsecrets, markdownlint-cli2,
#   autocorrect --lint, typos, shellcheck, ls-lint, djlint
task_summary_run "prek run --all-files (pre-commit)" env SKIP=no-commit-to-branch prek run --all-files --hook-stage pre-commit
task_summary_run "prek run --all-files (pre-push)" prek run --all-files --hook-stage pre-push

task_summary_print
