#!/usr/bin/env bash
# Common preamble for mise task scripts.
# Usage: source "$(dirname "$0")/_task.sh"

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" \
    || { echo "ERROR not in a git repo"; exit 1; }
cd "$repo_root"

# shellcheck source=_lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"
