#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="${0##*/}"

DEFAULT_ROUNDS="20"
DEFAULT_PARALLEL="4"

POLICY=""
ROUNDS="$DEFAULT_ROUNDS"
PARALLEL="$DEFAULT_PARALLEL"
LOG_DIR=""
SURGE_CLI=""
BANDWIDTH_DOWNLOAD=false
STARTED_AT=""

log() {
  printf '[INFO] %s\n' "$1" >&2
}

die() {
  printf '[ERROR] %s\n' "$1" >&2
  exit 1
}

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} --policy <name> [options]

Stress a Surge policy with repeated TCP/UDP/NAT/external-IP probes.

Output:
  stdout: one JSON summary object
  stderr: progress, diagnostics, and validation errors
  raw logs: per-command stdout/stderr/result files under --log-dir

Options:
  --policy <name>          Surge policy/proxy name to test
  --rounds <number>        Probe rounds (default: ${DEFAULT_ROUNDS})
  --parallel <number>      Max jobs per batch (default: ${DEFAULT_PARALLEL})
  --log-dir <dir>          Directory for raw command logs
  --surge-cli <path>       surge-cli path; auto-detected by default
  --bandwidth-download     Also run one download bandwidth diagnostic
  --help                   Show this help

Examples:
  bash ${SCRIPT_NAME} --policy my-snell-vps
  bash ${SCRIPT_NAME} --policy my-snell-vps --rounds 40 --parallel 8 --bandwidth-download
EOF
}

safe_filename_part() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'
}

validate_positive_int() {
  local name=$1
  local value=$2

  case "$value" in
  '' | *[!0-9]*)
    die "$name must be a positive integer: $value"
    ;;
  esac

  if [ "$value" -lt 1 ]; then
    die "$name must be at least 1: $value"
  fi
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
    --policy)
      [ "$#" -ge 2 ] || die "--policy requires a value"
      POLICY=$2
      shift 2
      ;;
    --rounds)
      [ "$#" -ge 2 ] || die "--rounds requires a value"
      ROUNDS=$2
      shift 2
      ;;
    --parallel)
      [ "$#" -ge 2 ] || die "--parallel requires a value"
      PARALLEL=$2
      shift 2
      ;;
    --log-dir)
      [ "$#" -ge 2 ] || die "--log-dir requires a value"
      LOG_DIR=$2
      shift 2
      ;;
    --surge-cli)
      [ "$#" -ge 2 ] || die "--surge-cli requires a value"
      SURGE_CLI=$2
      shift 2
      ;;
    --bandwidth-download)
      BANDWIDTH_DOWNLOAD=true
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
    esac
  done
}

resolve_surge_cli() {
  if [ -n "$SURGE_CLI" ]; then
    [ -x "$SURGE_CLI" ] || die "--surge-cli is not executable: $SURGE_CLI"
    return
  fi

  if command -v surge-cli >/dev/null 2>&1; then
    SURGE_CLI="$(command -v surge-cli)"
    return
  fi

  if [ -x /Applications/Surge.app/Contents/Applications/surge-cli ]; then
    SURGE_CLI=/Applications/Surge.app/Contents/Applications/surge-cli
    return
  fi

  die "surge-cli not found"
}

default_log_dir() {
  local stamp
  stamp="$(date +%Y%m%d%H%M%S)"
  printf '/tmp/surge-policy-stress-%s' "$stamp"
}

run_probe() {
  local kind=$1
  local iter=$2
  local prefix
  local stdout_file
  local stderr_file
  local result_file
  local start
  local end
  local rc
  local jq_ok
  local stdout_bytes
  local stderr_bytes
  local sample
  local error

  prefix="${LOG_DIR}/$(safe_filename_part "$kind")_${iter}"
  stdout_file="${prefix}.stdout.json"
  stderr_file="${prefix}.stderr.log"
  result_file="${prefix}.result.json"

  rc=0
  start="$(date +%s)"
  case "$kind" in
  tcp)
    "$SURGE_CLI" --raw test-policy "$POLICY" >"$stdout_file" 2>"$stderr_file" || rc=$?
    ;;
  udp)
    "$SURGE_CLI" --raw test-policy-udp "$POLICY" >"$stdout_file" 2>"$stderr_file" || rc=$?
    ;;
  external_ip)
    "$SURGE_CLI" --raw test-policy-external-ip "$POLICY" >"$stdout_file" 2>"$stderr_file" || rc=$?
    ;;
  nat_type)
    "$SURGE_CLI" --raw test-policy-nat-type "$POLICY" >"$stdout_file" 2>"$stderr_file" || rc=$?
    ;;
  bandwidth_download)
    "$SURGE_CLI" --raw test-policy-bandwidth download "$POLICY" >"$stdout_file" 2>"$stderr_file" || rc=$?
    ;;
  *)
    rc=127
    printf 'unknown probe kind: %s\n' "$kind" >"$stderr_file"
    : >"$stdout_file"
    ;;
  esac
  end="$(date +%s)"

  jq_ok=false
  if jq empty "$stdout_file" >/dev/null 2>&1; then
    jq_ok=true
  fi

  stdout_bytes="$(wc -c <"$stdout_file" | tr -d ' ')"
  stderr_bytes="$(wc -c <"$stderr_file" | tr -d ' ')"
  sample="$(head -c 240 "$stdout_file")"
  error="$(head -c 240 "$stderr_file")"

  jq -nc \
    --arg kind "$kind" \
    --argjson iter "$iter" \
    --argjson rc "$rc" \
    --argjson jq_ok "$jq_ok" \
    --argjson seconds "$((end - start))" \
    --argjson stdout_bytes "$stdout_bytes" \
    --argjson stderr_bytes "$stderr_bytes" \
    --arg stdout_file "$stdout_file" \
    --arg stderr_file "$stderr_file" \
    --arg sample "$sample" \
    --arg error "$error" \
    '{kind:$kind,iter:$iter,rc:$rc,jq_ok:$jq_ok,seconds:$seconds,stdout_bytes:$stdout_bytes,stderr_bytes:$stderr_bytes,stdout_file:$stdout_file,stderr_file:$stderr_file,sample:$sample,error:$error}' \
    >"$result_file"
}

main() {
  local i
  local jobs
  local finished_at
  local summary_file
  local summary_tmp

  parse_args "$@"
  [ -n "$POLICY" ] || die "--policy is required"
  validate_positive_int "--rounds" "$ROUNDS"
  validate_positive_int "--parallel" "$PARALLEL"
  command -v jq >/dev/null 2>&1 || die "jq is required"
  resolve_surge_cli

  if [ -z "$LOG_DIR" ]; then
    LOG_DIR="$(default_log_dir)"
  fi
  mkdir -p "$LOG_DIR"
  STARTED_AT="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  summary_file="${LOG_DIR}/summary.json"

  log "Writing raw stress logs to $LOG_DIR"
  log "Testing policy $POLICY with $ROUNDS rounds, parallel batch size $PARALLEL"

  jobs=0
  for i in $(seq 1 "$ROUNDS"); do
    run_probe tcp "$i" &
    jobs=$((jobs + 1))
    run_probe udp "$i" &
    jobs=$((jobs + 1))

    if [ $((i % 5)) -eq 0 ]; then
      run_probe external_ip "$i" &
      jobs=$((jobs + 1))
      run_probe nat_type "$i" &
      jobs=$((jobs + 1))
    fi

    if [ "$jobs" -ge "$PARALLEL" ]; then
      wait
      jobs=0
    fi
  done

  wait

  if [ "$BANDWIDTH_DOWNLOAD" = true ]; then
    log "Running one download bandwidth diagnostic"
    run_probe bandwidth_download 1
  fi

  finished_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  summary_tmp="${summary_file}.tmp.$$"

  jq -s \
    --arg policy "$POLICY" \
    --arg log_dir "$LOG_DIR" \
    --arg summary_file "$summary_file" \
    --arg surge_cli "$SURGE_CLI" \
    --arg started_at "$STARTED_AT" \
    --arg finished_at "$finished_at" \
    --argjson rounds "$ROUNDS" \
    --argjson parallel "$PARALLEL" \
    --argjson bandwidth_download "$BANDWIDTH_DOWNLOAD" \
    '{
      policy:$policy,
      log_dir:$log_dir,
      summary_file:$summary_file,
      surge_cli:$surge_cli,
      started_at:$started_at,
      finished_at:$finished_at,
      rounds:$rounds,
      parallel:$parallel,
      bandwidth_download:$bandwidth_download,
      total:length,
      by_kind:(group_by(.kind)|map({
        kind:.[0].kind,
        count:length,
        failures:map(select(.rc != 0 or .jq_ok != true))|length,
        stderr_events:map(select(.stderr_bytes > 0))|length,
        max_seconds:(map(.seconds)|max)
      })),
      failures:map(select(.rc != 0 or .jq_ok != true))[:20],
      stderr_events:map(select(.stderr_bytes > 0))[:20]
    }' "$LOG_DIR"/*.result.json >"$summary_tmp"
  mv "$summary_tmp" "$summary_file"
  cat "$summary_file"
}

main "$@"
