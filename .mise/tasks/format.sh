#!/usr/bin/env bash
#MISE description="Run formatters"

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" \
    || { echo "ERROR not in a git repo"; exit 1; }
cd "$repo_root"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

readonly COLOR_BLUE=4
readonly COLOR_GREEN=2
readonly COLOR_YELLOW=3
readonly COLOR_RED=1
readonly SPINNER_STYLE="${SPINNER_STYLE:-minidot}"
readonly RUN_CMD_TAIL_LINES="${RUN_CMD_TAIL_LINES:-200}"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log_info()  { echo "$(gum style --foreground $COLOR_GREEN  --bold '✓') $*"; }
log_warn()  { echo "$(gum style --foreground $COLOR_YELLOW --bold '!') $*"; }
log_error() { echo "$(gum style --foreground $COLOR_RED    --bold '✗') $*"; }

section() {
    echo ""
    gum style \
        --foreground $COLOR_BLUE \
        --border rounded \
        --border-foreground $COLOR_BLUE \
        --padding "0 1" \
        "$1"
}

# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

_now_ms() {
    if [[ -n "${EPOCHREALTIME:-}" ]]; then
        local sec="${EPOCHREALTIME%.*}"
        local frac="${EPOCHREALTIME#*.}"
        frac="${frac:0:3}"
        echo "$((10#$sec * 1000 + 10#$frac))"
        return 0
    fi
    local ms
    ms="$(date +%s%3N 2>/dev/null || true)"
    if [[ -n "$ms" && "$ms" =~ ^[0-9]+$ ]]; then
        echo "$ms"
        return 0
    fi
    echo "$((SECONDS * 1000))"
}

_fmt_ms() {
    local ms="$1"
    awk -v ms="$ms" 'BEGIN { printf "%.1fs", (ms / 1000.0) }'
}

# ---------------------------------------------------------------------------
# run_cmd — execute a command with spinner, timing, and auto-logging
# ---------------------------------------------------------------------------

RUN_CMD_LAST_DURATION=""

run_cmd() {
    local title="$1"
    shift
    local _rc_log exit_code=0
    _rc_log=$(mktemp)

    local start_ms end_ms dur_ms dur
    start_ms="$(_now_ms)"

    if [[ -t 1 ]]; then
        # shellcheck disable=SC2016
        _RC_LOG="$_rc_log" gum spin --spinner "$SPINNER_STYLE" \
            --spinner.foreground $COLOR_BLUE --title.foreground $COLOR_BLUE \
            --title "$title" -- bash -c '"$@" >"$_RC_LOG" 2>&1' _ "$@" || exit_code=$?
    else
        "$@" >"$_rc_log" 2>&1 || exit_code=$?
    fi

    end_ms="$(_now_ms)"
    dur_ms="$((end_ms - start_ms))"
    dur="$(_fmt_ms "$dur_ms")"
    RUN_CMD_LAST_DURATION="$dur"

    if [[ $exit_code -eq 0 ]]; then
        log_info "$title ($dur)"
        rm -f "$_rc_log"
        return 0
    fi

    log_error "$title ($dur)"
    local total_lines
    total_lines=$(wc -l < "$_rc_log")
    if [[ $total_lines -gt $RUN_CMD_TAIL_LINES ]]; then
        echo "  ... ($((total_lines - RUN_CMD_TAIL_LINES)) lines truncated)"
        tail -n "$RUN_CMD_TAIL_LINES" "$_rc_log"
        log_warn "Full log: $_rc_log"
    else
        cat "$_rc_log"
        rm -f "$_rc_log"
    fi
    return $exit_code
}

# ---------------------------------------------------------------------------
# Task summary harness
# ---------------------------------------------------------------------------

_TASK_SUMMARY_NAME=""
_TASK_SUMMARY_START_MS=0
_TASK_SUMMARY_TITLES=()
_TASK_SUMMARY_RCS=()
_TASK_SUMMARY_DURS=()

task_summary_start() {
    _TASK_SUMMARY_NAME="${1:-Summary}"
    _TASK_SUMMARY_START_MS="$(_now_ms)"
    _TASK_SUMMARY_TITLES=()
    _TASK_SUMMARY_RCS=()
    _TASK_SUMMARY_DURS=()
}

task_summary_run() {
    local title="$1"
    shift
    local rc=0
    if run_cmd "$title" "$@"; then
        rc=0
    else
        rc=$?
    fi
    _TASK_SUMMARY_TITLES+=("$title")
    _TASK_SUMMARY_RCS+=("$rc")
    _TASK_SUMMARY_DURS+=("${RUN_CMD_LAST_DURATION:-}")
    return 0
}

task_summary_print() {
    local end_ms total_ms total_dur
    end_ms="$(_now_ms)"
    total_ms="$((end_ms - _TASK_SUMMARY_START_MS))"
    total_dur="$(_fmt_ms "$total_ms")"

    echo ""
    local any_fail=0
    for i in "${!_TASK_SUMMARY_TITLES[@]}"; do
        if [[ "${_TASK_SUMMARY_RCS[$i]}" -ne 0 ]]; then
            any_fail=1
            break
        fi
    done

    if [[ "$any_fail" -eq 0 ]]; then
        log_info "${_TASK_SUMMARY_NAME}: all passed ($total_dur)"
    else
        section "${_TASK_SUMMARY_NAME} summary"
        for i in "${!_TASK_SUMMARY_TITLES[@]}"; do
            local t="${_TASK_SUMMARY_TITLES[$i]}"
            local d="${_TASK_SUMMARY_DURS[$i]}"
            if [[ "${_TASK_SUMMARY_RCS[$i]}" -eq 0 ]]; then
                log_info "$t ($d)"
            else
                log_error "$t ($d)"
            fi
        done
        echo ""
        log_error "${_TASK_SUMMARY_NAME}: some checks failed ($total_dur)"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

task_summary_start "Format"

task_summary_run "uv sync --frozen" uv sync --frozen

task_summary_run "ruff format ." uv run ruff format .

task_summary_run "ruff check . --fix" uv run ruff check . --fix

task_summary_run "tombi format ." uvx tombi format .

task_summary_run "biome format . --write" biome format . --write

task_summary_run "autocorrect --fix ." autocorrect --fix . .agents/ .mise/

if [[ "${CI:-}" == "true" ]]; then
    task_summary_run "working tree clean" bash -c 'git diff --exit-code'
fi

task_summary_print
