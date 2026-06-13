#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="${0##*/}"

DEFAULT_PORT="14180"
DEFAULT_JOURNAL_SINCE="10 min ago"
DEFAULT_SSH_USER="root"

PORT="$DEFAULT_PORT"
JOURNAL_SINCE="$DEFAULT_JOURNAL_SINCE"
SSH_USER="$DEFAULT_SSH_USER"
LOG_DIR=""
SNELL_VERSION=""
HAVE_CUSTOM_SERVERS=false

TMP_SERVERS=""

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} [options]

Audit Snell VPS health over SSH.

Output:
  stdout: one JSON object per host
  stderr: progress, diagnostics, and validation errors
  exit 0: all hosts are ok or warning-only
  exit 1: at least one host has failed checks or SSH/audit failure

Options:
  --server <name=ip>       Add one server to audit. May be repeated.
  --server-file <path>     Read servers from a file. Lines: "name ip" or "name=ip".
  --port <port>            Snell port to check (default: ${DEFAULT_PORT})
  --journal-since <time>   Journal window for warning counters (default: "${DEFAULT_JOURNAL_SINCE}")
  --ssh-user <user>        SSH user (default: ${DEFAULT_SSH_USER})
  --log-dir <dir>          Directory for raw per-host audit logs
  --snell-version <ver>    Probe the matching Snell download URL during outbound checks
  --help                   Show this help

Examples:
  ${SCRIPT_NAME} --server-file /path/to/snell-servers.txt --snell-version <version>
  ${SCRIPT_NAME} --server my-snell-vps=203.0.113.10 --journal-since "30 min ago"
EOF
}

die() {
  printf '[ERROR] %s\n' "$1" >&2
  exit 1
}

log() {
  printf '[INFO] %s\n' "$1" >&2
}

trap 'if [ -n "$TMP_SERVERS" ] && [ -f "$TMP_SERVERS" ]; then rm -f "$TMP_SERVERS"; fi' EXIT

shell_quote() {
  printf "'"
  printf '%s' "$1" | sed "s/'/'\\\\''/g"
  printf "'"
}

json_escape() {
  printf '%s' "$1" | awk '
    BEGIN { ORS = "" }
    {
      gsub(/\\/, "\\\\")
      gsub(/"/, "\\\"")
      gsub(/\t/, "\\t")
      gsub(/\r/, "\\r")
      printf "%s", $0
    }
  '
}

safe_filename_part() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'
}

validate_port() {
  case "$PORT" in
  '' | *[!0-9]*)
    die "Port must be a number: $PORT"
    ;;
  esac

  if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    die "Port must be between 1 and 65535: $PORT"
  fi
}

validate_snell_version() {
  if [ -z "$SNELL_VERSION" ]; then
    return
  fi

  case "$SNELL_VERSION" in
  *[!A-Za-z0-9._-]*)
    die "--snell-version contains unsupported characters: $SNELL_VERSION"
    ;;
  esac
}

add_server() {
  local input=$1
  local name
  local ip

  case "$input" in
  *=*)
    name=${input%%=*}
    ip=${input#*=}
    ;;
  *)
    die "Server must be name=ip: $input"
    ;;
  esac

  [ -n "$name" ] || die "Server name is empty: $input"
  [ -n "$ip" ] || die "Server IP is empty: $input"
  printf '%s %s\n' "$name" "$ip" >>"$TMP_SERVERS"
  HAVE_CUSTOM_SERVERS=true
}

append_server_file() {
  local file=$1
  local first
  local second
  local line
  local name
  local ip

  [ -r "$file" ] || die "Cannot read server file: $file"

  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
    '' | '#'*)
      continue
      ;;
    *=*)
      add_server "$line"
      ;;
    *)
      first=${line%%[ 	]*}
      second=${line#"$first"}
      second=$(printf '%s' "$second" | awk '{ print $1 }')
      name=$first
      ip=$second
      [ -n "$name" ] || continue
      [ -n "$ip" ] || die "Invalid server line in $file: $line"
      printf '%s %s\n' "$name" "$ip" >>"$TMP_SERVERS"
      HAVE_CUSTOM_SERVERS=true
      ;;
    esac
  done <"$file"
}

parse_args() {
  TMP_SERVERS="$(mktemp)"
  : >"$TMP_SERVERS"

  while [ "$#" -gt 0 ]; do
    case "$1" in
    --server)
      [ "$#" -ge 2 ] || die "--server requires a value"
      add_server "$2"
      shift 2
      ;;
    --server-file)
      [ "$#" -ge 2 ] || die "--server-file requires a value"
      append_server_file "$2"
      shift 2
      ;;
    --port)
      [ "$#" -ge 2 ] || die "--port requires a value"
      PORT=$2
      shift 2
      ;;
    --journal-since)
      [ "$#" -ge 2 ] || die "--journal-since requires a value"
      JOURNAL_SINCE=$2
      shift 2
      ;;
    --ssh-user)
      [ "$#" -ge 2 ] || die "--ssh-user requires a value"
      SSH_USER=$2
      shift 2
      ;;
    --log-dir)
      [ "$#" -ge 2 ] || die "--log-dir requires a value"
      LOG_DIR=$2
      shift 2
      ;;
    --snell-version)
      [ "$#" -ge 2 ] || die "--snell-version requires a value"
      SNELL_VERSION=$2
      shift 2
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

  if [ "$HAVE_CUSTOM_SERVERS" != true ]; then
    die "Provide at least one --server or --server-file entry"
  fi
}

default_log_dir() {
  local stamp
  stamp="$(date +%Y%m%d%H%M%S)"
  printf '/tmp/snell-audit-%s' "$stamp"
}

remote_audit() {
  local ip=$1
  local out_file=$2
  local remote_env

  remote_env="SNELL_AUDIT_PORT=$(shell_quote "$PORT") SNELL_AUDIT_JOURNAL_SINCE=$(shell_quote "$JOURNAL_SINCE") SNELL_AUDIT_SNELL_VERSION=$(shell_quote "$SNELL_VERSION")"

  ssh -o BatchMode=yes -o ConnectTimeout=10 "${SSH_USER}@${ip}" "$remote_env bash -s" >"$out_file" 2>&1 <<'REMOTE'
set -u

PORT=${SNELL_AUDIT_PORT:-14180}
JOURNAL_SINCE=${SNELL_AUDIT_JOURNAL_SINCE:-10 min ago}
SNELL_VERSION=${SNELL_AUDIT_SNELL_VERSION:-}
CONFIG=/etc/snell/snell-server.conf
SERVICE=snell-server
BIN=/usr/local/bin/snell-server

section() {
  printf '\n## %s\n' "$1"
}

section identity
printf 'hostname=%s\n' "$(hostname -f 2>/dev/null || hostname 2>/dev/null || printf unknown)"
printf 'date=%s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || date)"
printf 'kernel=%s\n' "$(uname -a)"
if [ -r /etc/os-release ]; then
  sed -n 's/^PRETTY_NAME=/os=/p' /etc/os-release | tr -d '"'
fi

section resources
uptime || true
free -h 2>/dev/null || true
df -h / /tmp 2>/dev/null || true
swapon --show 2>/dev/null || true

section snell_binary
if [ -x "$BIN" ]; then
  "$BIN" -v 2>&1 || true
  sha256sum "$BIN" 2>/dev/null || shasum -a 256 "$BIN" 2>/dev/null || true
  ls -l "$BIN"
else
  printf 'missing %s\n' "$BIN"
fi

section snell_config
if [ -r "$CONFIG" ]; then
  ls -l "$CONFIG"
  sed -n '1,80p' "$CONFIG"
else
  printf 'missing/unreadable %s\n' "$CONFIG"
fi

section snell_user
getent passwd snell 2>/dev/null || true
getent group snell 2>/dev/null || true

section service_state
systemctl show "$SERVICE" -p ActiveState -p SubState -p Result -p NRestarts -p ExecMainPID -p ExecMainStartTimestamp -p Restart -p RestartUSec -p LimitNOFILE 2>/dev/null || true
systemctl is-enabled "$SERVICE" 2>/dev/null || true

section service_files
systemctl cat "$SERVICE" 2>/dev/null || true

section listeners
ss -lntup 2>/dev/null | awk -v port=":$PORT" '$0 ~ port { print }' || true

section firewall_ufw
if command -v ufw >/dev/null 2>&1; then
  ufw status verbose
else
  printf 'ufw not installed\n'
fi

section firewall_iptables
if command -v iptables >/dev/null 2>&1; then
  iptables -S 2>/dev/null | awk -v port="$PORT" '$0 ~ port || $0 ~ /REJECT|DROP|INPUT|OUTPUT|FORWARD/ { print }'
else
  printf 'iptables not installed\n'
fi

section firewall_nft
if command -v nft >/dev/null 2>&1; then
  nft list ruleset 2>/dev/null | awk -v port="$PORT" '$0 ~ port || $0 ~ /reject|drop|chain input|chain output|hook input|hook output/ { print }' | sed -n '1,180p'
else
  printf 'nft not installed\n'
fi

section fail2ban
if command -v fail2ban-client >/dev/null 2>&1; then
  fail2ban-client status 2>/dev/null || true
  fail2ban-client status sshd 2>/dev/null || true
  fail2ban-client status snell 2>/dev/null || true
else
  printf 'fail2ban not installed\n'
fi

section apt_sources_check
duplicate_security_sources=0
if [ -f /etc/apt/sources.list.d/debian-security-autofix.list ] &&
  [ -f /etc/apt/sources.list ] &&
  grep -q 'security.debian.org/debian-security' /etc/apt/sources.list.d/debian-security-autofix.list &&
  grep -q 'security.debian.org/debian-security' /etc/apt/sources.list; then
  duplicate_security_sources=1
fi
printf 'duplicate_security_sources=%s\n' "$duplicate_security_sources"

section dns
cat /etc/resolv.conf 2>/dev/null || true
getent hosts apple.com google.com cloudflare.com 2>/dev/null || true

section outbound
for url in https://www.apple.com/library/test/success.html https://icanhazip.com; do
  printf '%s ' "$url"
  curl -4fsS --max-time 8 --output /dev/null --write-out 'http=%{http_code} time=%{time_total}\n' "$url" 2>&1 || true
done

download_version=$SNELL_VERSION
if [ -z "$download_version" ] && [ -x "$BIN" ]; then
  download_version="$("$BIN" -v 2>&1 | sed -n 's/^.*snell-server \([A-Za-z0-9._-][A-Za-z0-9._-]*\).*$/\1/p' | head -1)"
fi

if [ -n "$download_version" ]; then
  url="https://dl.nssurge.com/snell/snell-server-v${download_version}-linux-amd64.zip"
  printf '%s ' "$url"
  curl -4fsS --max-time 8 --output /dev/null --write-out 'http=%{http_code} time=%{time_total}\n' "$url" 2>&1 || true
else
  printf 'snell_download_url skipped: no requested version and no detected local version\n'
fi

section journal_recent
journalctl -u "$SERVICE" --since "$JOURNAL_SINCE" --no-pager 2>/dev/null |
  awk '/WARN|ERROR|assert|Failed|failed|exited|signal 6|Decryption failed|DNS error|connect error/ { print }' |
  tail -120 || true

section decryption_top
journalctl -u "$SERVICE" --since "$JOURNAL_SINCE" --no-pager 2>/dev/null |
  awk '/Decryption failed/ { count[$NF]++ } END { for (ip in count) print count[ip], ip }' |
  sort -nr |
  sed -n '1,20p' || true

section kernel_recent
dmesg -T 2>/dev/null |
  awk 'tolower($0) ~ /oom|killed|segfault|snell|denied|blocked/ { print }' |
  tail -80 || true

section summary_kv
version="$("$BIN" -v 2>&1 | sed -n 's/^.*snell-server /snell-server /p' | head -1)"
active="$(systemctl show "$SERVICE" -p ActiveState --value 2>/dev/null || true)"
sub="$(systemctl show "$SERVICE" -p SubState --value 2>/dev/null || true)"
restarts="$(systemctl show "$SERVICE" -p NRestarts --value 2>/dev/null || true)"
nofile="$(systemctl show "$SERVICE" -p LimitNOFILE --value 2>/dev/null || true)"
tcp_listen="$(ss -lntup 2>/dev/null | awk -v port=":$PORT" '$0 ~ port && $1 == "tcp" { found=1 } END { print found ? "yes" : "no" }')"
udp_listen="$(ss -lntup 2>/dev/null | awk -v port=":$PORT" '$0 ~ port && $1 == "udp" { found=1 } END { print found ? "yes" : "no" }')"
hardening_mentions="$(systemctl cat "$SERVICE" 2>/dev/null | awk '
  /^[[:space:]]*#/ { next }
  /^[[:space:]]*(PrivateDevices|ProtectSystem|RestrictAddressFamilies|CapabilityBoundingSet)[[:space:]=]/ { count++ }
  END { print count + 0 }
')"
apt_duplicate_sources="$duplicate_security_sources"
decryption_total="$(journalctl -u "$SERVICE" --since "$JOURNAL_SINCE" --no-pager 2>/dev/null | awk '/Decryption failed/ { count++ } END { print count + 0 }')"
udp_crash_markers="$(journalctl -u "$SERVICE" --since "$JOURNAL_SINCE" --no-pager 2>/dev/null | awk '/UDP socket send error|uv_close|signal 6|Main process exited|Failed with result/ { count++ } END { print count + 0 }')"
top_decryption="$(journalctl -u "$SERVICE" --since "$JOURNAL_SINCE" --no-pager 2>/dev/null | awk '/Decryption failed/ { count[$NF]++ } END { topc=0; topip="-"; for (ip in count) if (count[ip] > topc) { topc=count[ip]; topip=ip } print topc ":" topip }')"
printf 'version=%s\n' "$version"
printf 'active=%s\n' "$active"
printf 'sub=%s\n' "$sub"
printf 'restarts=%s\n' "$restarts"
printf 'nofile=%s\n' "$nofile"
printf 'tcp_listen=%s\n' "$tcp_listen"
printf 'udp_listen=%s\n' "$udp_listen"
printf 'hardening_mentions=%s\n' "$hardening_mentions"
printf 'apt_duplicate_sources=%s\n' "$apt_duplicate_sources"
printf 'decryption_total=%s\n' "$decryption_total"
printf 'top_decryption=%s\n' "$top_decryption"
printf 'udp_crash_markers=%s\n' "$udp_crash_markers"
REMOTE
}

summary_value() {
  local key=$1
  local file=$2

  awk -F= -v key="$key" '
    $1 == key {
      value=$0
      sub("^[^=]*=", "", value)
      print value
      exit
    }
  ' "$file"
}

append_failed_check() {
  if [ -n "$failed_checks" ]; then
    failed_checks="${failed_checks},"
  fi
  failed_checks="${failed_checks}\"$1\""
}

append_warning_check() {
  if [ -n "$warning_checks" ]; then
    warning_checks="${warning_checks},"
  fi
  warning_checks="${warning_checks}\"$1\""
}

nonzero() {
  [ -n "$1" ] && [ "$1" != "0" ]
}

print_result_json() {
  local name=$1
  local ip=$2
  local file=$3
  local active
  local sub
  local restarts
  local version
  local tcp_listen
  local udp_listen
  local hardening
  local apt_dupes
  local decryption
  local top_decryption
  local crashes
  local status
  local failed_checks
  local warning_checks

  failed_checks=""
  warning_checks=""

  if ! grep -q '^## summary_kv$' "$file"; then
    failed_checks='"ssh_or_audit_failed"'
    printf '{"name":"%s","ip":"%s","status":"fail","failed_checks":[%s],"warning_checks":[],"log_path":"%s","values":{}}\n' \
      "$(json_escape "$name")" "$(json_escape "$ip")" "$failed_checks" "$(json_escape "$file")"
    return 1
  fi

  active="$(summary_value active "$file")"
  sub="$(summary_value sub "$file")"
  restarts="$(summary_value restarts "$file")"
  version="$(summary_value version "$file")"
  tcp_listen="$(summary_value tcp_listen "$file")"
  udp_listen="$(summary_value udp_listen "$file")"
  hardening="$(summary_value hardening_mentions "$file")"
  apt_dupes="$(summary_value apt_duplicate_sources "$file")"
  decryption="$(summary_value decryption_total "$file")"
  top_decryption="$(summary_value top_decryption "$file")"
  crashes="$(summary_value udp_crash_markers "$file")"

  [ "$active" = "active" ] || append_failed_check "service_inactive"
  [ "$sub" = "running" ] || append_failed_check "service_not_running"
  [ "$tcp_listen" = "yes" ] || append_failed_check "tcp_not_listening"
  [ "$udp_listen" = "yes" ] || append_failed_check "udp_not_listening"
  nonzero "$hardening" && append_failed_check "systemd_hardening_present"
  nonzero "$apt_dupes" && append_failed_check "apt_duplicate_security_sources"
  nonzero "$crashes" && append_failed_check "udp_crash_markers_present"
  nonzero "$decryption" && append_warning_check "decryption_failed_seen"

  status="ok"
  if [ -n "$failed_checks" ]; then
    status="issue"
  elif [ -n "$warning_checks" ]; then
    status="warn"
  fi

  printf '{"name":"%s","ip":"%s","status":"%s","failed_checks":[%s],"warning_checks":[%s],"log_path":"%s","values":{' \
    "$(json_escape "$name")" "$(json_escape "$ip")" "$status" "$failed_checks" "$warning_checks" "$(json_escape "$file")"
  printf '"version":"%s"' "$(json_escape "$version")"
  printf ',"active":"%s"' "$(json_escape "$active")"
  printf ',"sub":"%s"' "$(json_escape "$sub")"
  printf ',"restarts":"%s"' "$(json_escape "$restarts")"
  printf ',"nofile":"%s"' "$(json_escape "$(summary_value nofile "$file")")"
  printf ',"tcp_listen":"%s"' "$(json_escape "$tcp_listen")"
  printf ',"udp_listen":"%s"' "$(json_escape "$udp_listen")"
  printf ',"hardening_mentions":"%s"' "$(json_escape "$hardening")"
  printf ',"apt_duplicate_sources":"%s"' "$(json_escape "$apt_dupes")"
  printf ',"decryption_total":"%s"' "$(json_escape "$decryption")"
  printf ',"top_decryption":"%s"' "$(json_escape "$top_decryption")"
  printf ',"udp_crash_markers":"%s"' "$(json_escape "$crashes")"
  printf '}}\n'

  [ "$status" != "issue" ]
}

main() {
  local name
  local ip
  local out_file
  local safe_name
  local safe_ip
  local overall_rc=0

  parse_args "$@"
  validate_port
  validate_snell_version

  if [ -z "$LOG_DIR" ]; then
    LOG_DIR="$(default_log_dir)"
  fi

  mkdir -p "$LOG_DIR"
  log "Writing raw audit logs to $LOG_DIR"

  while read -r name ip; do
    [ -n "$name" ] || continue
    safe_name="$(safe_filename_part "$name")"
    safe_ip="$(safe_filename_part "$ip")"
    out_file="${LOG_DIR}/${safe_name}_${safe_ip}.txt"
    log "Auditing $name ($ip)"
    remote_audit "$ip" "$out_file" || true
    if ! print_result_json "$name" "$ip" "$out_file"; then
      overall_rc=1
    fi
  done <"$TMP_SERVERS"

  exit "$overall_rc"
}

main "$@"
