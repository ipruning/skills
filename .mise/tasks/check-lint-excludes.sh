#!/usr/bin/env bash
#MISE description="Verify lint config excludes match the non-_ .metadata.json entries"

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" \
    || { echo "ERROR not in a git repo" >&2; exit 1; }
cd "$repo_root"

if [[ ! -f .metadata.json ]]; then
    echo "ERROR missing .metadata.json" >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR jq is required to read .metadata.json" >&2
    exit 1
fi

entries_file="$(mktemp)"
trap 'rm -f "$entries_file"' EXIT
jq -r '.entries | keys[] | select(startswith("_") | not)' .metadata.json | sort >"$entries_file"

failures=0

fail() {
    echo "ERROR $1" >&2
    failures=$((failures + 1))
}

# Print the body of one pyproject.toml [section] (exact header match).
pyproject_section() {
    awk -v h="$1" '$0 == h { in_section = 1; next } /^\[/ { in_section = 0 } in_section' pyproject.toml
}

# Direction 1: every non-_ .metadata.json entry must be excluded in all six
# config files (eight places). Avoid grep -q in pipelines: early exit would
# SIGPIPE the producer and turn a match into a false failure under pipefail.
while IFS= read -r entry; do
    grep -F "\"$entry/\"" .typos.toml >/dev/null \
        || fail "missing in .typos.toml [files].extend-exclude: \"$entry/\""
    grep -F "\"$entry/\"" .markdownlint-cli2.yaml >/dev/null \
        || fail "missing in .markdownlint-cli2.yaml ignores: \"$entry/\""
    grep -F "\"!!$entry\"" biome.jsonc >/dev/null \
        || fail "missing in biome.jsonc files.includes: \"!!$entry\""
    pyproject_section "[tool.ruff]" | grep -F "\"$entry/\"" >/dev/null \
        || fail "missing in pyproject.toml [tool.ruff].exclude: \"$entry/\""
    pyproject_section "[tool.ty.src]" | grep -F "\"$entry/\"" >/dev/null \
        || fail "missing in pyproject.toml [tool.ty.src].exclude: \"$entry/\""
    pyproject_section "[tool.tombi.files]" | grep -F "\"$entry/**\"" >/dev/null \
        || fail "missing in pyproject.toml [tool.tombi.files].exclude: \"$entry/**\""
    sed -n 's/^exclude *= *"\(.*\)"$/\1/p' prek.toml | tr '|' '\n' | grep -F "^$entry/" >/dev/null \
        || fail "missing in prek.toml top-level exclude: ^$entry/"
    grep -x -F "$entry/" .autocorrectignore >/dev/null \
        || fail "missing in .autocorrectignore: $entry/"
done <"$entries_file"

# Direction 2: no stale skill exclude may outlive its .metadata.json entry.
# `_`-prefixed directories are gitignored (never checked in) and dot-prefixed
# entries are unrelated tool excludes; both are skipped.
check_stale() {
    local config_desc="$1"
    local name
    while IFS= read -r name; do
        if [[ -z "$name" || "$name" == _* || "$name" == .* ]]; then
            continue
        fi
        grep -x -F "$name" "$entries_file" >/dev/null \
            || fail "stale in $config_desc: $name has no non-_ .metadata.json entry"
    done
}

extract_quoted_dirs() {
    grep -o '"[^"]*/"' | sed 's/^"//; s|/"$||'
}

check_stale ".typos.toml [files].extend-exclude" < <(
    awk '$0 == "[files]" { f = 1; next } /^\[/ { f = 0 } f' .typos.toml | extract_quoted_dirs
)
check_stale ".markdownlint-cli2.yaml ignores" < <(
    awk '/^ignores:/ { f = 1; next } f && $0 !~ /^[[:space:]]*-/ { f = 0 } f' .markdownlint-cli2.yaml \
        | extract_quoted_dirs
)
check_stale "biome.jsonc files.includes" < <(
    grep -o '"!![^"]*"' biome.jsonc | sed 's/^"!!//; s/"$//'
)
check_stale "pyproject.toml [tool.ruff].exclude" < <(
    pyproject_section "[tool.ruff]" | extract_quoted_dirs
)
check_stale "pyproject.toml [tool.ty.src].exclude" < <(
    pyproject_section "[tool.ty.src]" | extract_quoted_dirs
)
check_stale "pyproject.toml [tool.tombi.files].exclude" < <(
    pyproject_section "[tool.tombi.files]" | grep -o '"[^"]*/\*\*"' | sed 's/^"//; s|/\*\*"$||'
)
check_stale "prek.toml top-level exclude" < <(
    sed -n 's/^exclude *= *"\(.*\)"$/\1/p' prek.toml | tr '|' '\n' | sed 's/^\^//; s|/$||'
)
check_stale ".autocorrectignore" < <(
    sed -n 's|/$||p' .autocorrectignore
)

entry_count="$(wc -l <"$entries_file" | tr -d ' ')"
if [[ "$failures" -gt 0 ]]; then
    echo "Lint exclude check failed with $failures problem(s) for $entry_count metadata entr(y/ies)." >&2
    echo "Add or remove the literals above; see 'Excluding external skills from linting' in AGENTS.md." >&2
    exit 1
fi

echo "Lint excludes match all $entry_count non-_ .metadata.json entr(y/ies) across six config files."
