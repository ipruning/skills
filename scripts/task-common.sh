#!/usr/bin/env bash

# Shared by lint.sh and format.sh; callers enable strict shell options.
repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" \
    || { echo "ERROR not in a git repo" >&2; exit 1; }
cd "$repo_root" || exit 1

TASK_NAME=""
TASK_STARTED=0
TASK_FAILURES=()

task_summary_start() {
    TASK_NAME="$1"
    TASK_STARTED=$SECONDS
    TASK_FAILURES=()
}

task_summary_run() {
    local title="$1"
    shift
    local log_file exit_code=0 started=$SECONDS
    log_file="$(mktemp)"

    "$@" >"$log_file" 2>&1 || exit_code=$?
    if [[ "$exit_code" -eq 0 ]]; then
        printf '✓ %s (%ss)\n' "$title" "$((SECONDS - started))"
        rm -f "$log_file"
    else
        printf '✗ %s (%ss, exit %s)\n' "$title" "$((SECONDS - started))" "$exit_code"
        TASK_FAILURES+=("$title")
        local total_lines tail_lines="${RUN_CMD_TAIL_LINES:-200}"
        total_lines="$(wc -l < "$log_file")"
        if [[ "$total_lines" -gt "$tail_lines" ]]; then
            tail -n "$tail_lines" "$log_file"
            printf 'Full log: %s\n' "$log_file"
        else
            cat "$log_file"
            rm -f "$log_file"
        fi
    fi
    # Run the remaining checks before reporting overall failure.
    return 0
}

task_summary_print() {
    if [[ "${#TASK_FAILURES[@]}" -eq 0 ]]; then
        printf '\n✓ %s: all passed (%ss)\n' "$TASK_NAME" "$((SECONDS - TASK_STARTED))"
        return 0
    fi
    printf '\n✗ %s: failed checks (%ss)\n' "$TASK_NAME" "$((SECONDS - TASK_STARTED))"
    printf '  - %s\n' "${TASK_FAILURES[@]}"
    return 1
}
