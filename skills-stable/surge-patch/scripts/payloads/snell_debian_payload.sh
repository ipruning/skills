#!/usr/bin/env bash
set -Eeuo pipefail

RUN_DIR="${RUN_DIR:-$(pwd)}"
INPUT_ENV="${RUN_DIR}/input.env"
LOG_DIR="${RUN_DIR}/logs"
RESULT_FILE="${RUN_DIR}/result.json"
STDOUT_JSON_EMITTED=false

BINARY_PATH="/usr/local/bin/snell-server"
CONFIG_DIR="/etc/snell"
CONFIG_FILE="${CONFIG_DIR}/snell-server.conf"
SERVICE_NAME="snell-server"
SERVICE_FILE="/etc/systemd/system/snell-server.service"
SWAP_FILE="/swapfile"

SURGE_PATCH_OPERATION=""
SNELL_PORT="14180"
SNELL_VERSION=""
SNELL_JOURNAL_SINCE="10 min ago"
SNELL_NAME=""
SNELL_PSK=""
SNELL_REPLACE_PSK=false
SNELL_SHA256=""
SNELL_OPEN_UFW=false
SNELL_ENSURE_SWAP=false
SNELL_SWAP_SIZE_GIB=4

mkdir -p "$LOG_DIR"

if [ -r "$INPUT_ENV" ]; then
  # shellcheck source=/dev/null
  . "$INPUT_ENV"
fi

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

json_bool() {
  if [ "$1" = true ]; then
    printf 'true'
  else
    printf 'false'
  fi
}

write_result() {
  local payload=$1
  printf '%s\n' "$payload" | tee "$RESULT_FILE"
  STDOUT_JSON_EMITTED=true
}

write_failure_result() {
  local status=$1
  local message=$2
  local payload
  payload=$(printf '{"status":"%s","operation":"%s","error":"%s"}' \
    "$(json_escape "$status")" \
    "$(json_escape "$SURGE_PATCH_OPERATION")" \
    "$(json_escape "$message")")
  printf '%s\n' "$payload" >"$RESULT_FILE"
  if [ "$STDOUT_JSON_EMITTED" != true ]; then
    printf '%s\n' "$payload"
    STDOUT_JSON_EMITTED=true
  fi
}

on_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ] && [ "$STDOUT_JSON_EMITTED" != true ]; then
    write_failure_result "failed" "payload exited with code ${rc}"
  fi
}

on_error() {
  local rc=$?
  local line=${BASH_LINENO[0]:-unknown}
  local command=${BASH_COMMAND:-unknown}
  printf '[ERROR] command failed at line %s: %s\n' "$line" "$command" >&2
  if [ "$STDOUT_JSON_EMITTED" != true ]; then
    write_failure_result "failed" "command failed at line ${line}: ${command}"
  fi
  exit "$rc"
}

trap on_error ERR
trap on_exit EXIT

die() {
  local message=$1
  printf '[ERROR] %s\n' "$message" >&2
  write_failure_result "failed" "$message"
  exit 1
}

log() {
  printf '[INFO] %s\n' "$1" >&2
}

validate_port() {
  case "$SNELL_PORT" in
  '' | *[!0-9]*)
    die "SNELL_PORT must be a number"
    ;;
  esac
  if [ "$SNELL_PORT" -lt 1 ] || [ "$SNELL_PORT" -gt 65535 ]; then
    die "SNELL_PORT must be between 1 and 65535"
  fi
}

validate_bool() {
  local name=$1
  local value=$2
  case "$value" in
  true | false)
    ;;
  *)
    die "${name} must be true or false"
    ;;
  esac
}

validate_common() {
  [ -r "$INPUT_ENV" ] || die "missing input.env"
  validate_port
  validate_bool SNELL_REPLACE_PSK "$SNELL_REPLACE_PSK"
  validate_bool SNELL_OPEN_UFW "$SNELL_OPEN_UFW"
  validate_bool SNELL_ENSURE_SWAP "$SNELL_ENSURE_SWAP"
  case "$SNELL_SWAP_SIZE_GIB" in
  '' | *[!0-9]*)
    die "SNELL_SWAP_SIZE_GIB must be a positive integer"
    ;;
  esac
  if [ "$SNELL_SWAP_SIZE_GIB" -lt 1 ]; then
    die "SNELL_SWAP_SIZE_GIB must be at least 1"
  fi
}

validate_snell_version_required() {
  [ -n "$SNELL_VERSION" ] || die "SNELL_VERSION is required"
  case "$SNELL_VERSION" in
  *[!A-Za-z0-9._-]*)
    die "SNELL_VERSION contains unsupported characters"
    ;;
  esac
}

validate_psk() {
  if [ -z "$SNELL_PSK" ]; then
    return
  fi
  case "$SNELL_PSK" in
  *','* | *' '* | *'	'*)
    die "SNELL_PSK must not contain commas or whitespace"
    ;;
  esac
}

require_root_debian_systemd() {
  [ "$(id -u)" -eq 0 ] || die "run as root"
  command -v apt-get >/dev/null 2>&1 || die "apt-get is required"
  command -v systemctl >/dev/null 2>&1 || die "systemd is required"
}

validate_architecture() {
  local arch
  arch="$(uname -m)"
  case "$arch" in
  x86_64 | amd64)
    ;;
  *)
    die "only x86_64/amd64 Snell server install is supported by this payload, got: $arch"
    ;;
  esac
}

major_version() {
  printf '%s' "${SNELL_VERSION%%.*}"
}

snell_binary_name() {
  printf 'snell-server-v%s-linux-amd64.zip' "$SNELL_VERSION"
}

snell_download_url() {
  printf 'https://dl.nssurge.com/snell/%s' "$(snell_binary_name)"
}

existing_config_value() {
  local key=$1
  [ -r "$CONFIG_FILE" ] || return 1
  awk -F= -v key="$key" '
    $1 ~ "^[[:space:]]*" key "[[:space:]]*$" {
      value=$2
      sub(/^[[:space:]]*/, "", value)
      sub(/[[:space:]]*$/, "", value)
      print value
      exit
    }
  ' "$CONFIG_FILE"
}

generate_psk() {
  od -An -N16 -tx1 /dev/urandom | tr -d ' \n'
}

choose_psk() {
  local existing_psk
  if [ -n "$SNELL_PSK" ]; then
    return
  fi
  if [ "$SNELL_REPLACE_PSK" != true ]; then
    existing_psk="$(existing_config_value psk || true)"
    if [ -n "$existing_psk" ]; then
      SNELL_PSK="$existing_psk"
      return
    fi
  fi
  SNELL_PSK="$(generate_psk)"
}

backup_file() {
  local path=$1
  if [ -f "$path" ]; then
    cp -a "$path" "${path}.bak.$(date +%Y%m%d%H%M%S)"
  fi
}

install_dependencies() {
  log "Installing Snell payload dependencies"
  DEBIAN_FRONTEND=noninteractive apt-get update -qq >&2
  DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl unzip >&2
}

download_snell() {
  local archive
  local temp_binary
  local tmp_dir
  local unpack_dir
  tmp_dir="$(mktemp -d)"
  archive="${tmp_dir}/$(snell_binary_name)"
  unpack_dir="${tmp_dir}/unpack"
  mkdir -p "$unpack_dir"

  log "Downloading $(snell_binary_name)"
  curl --fail --location --show-error --silent --connect-timeout 10 --retry 3 \
    --output "$archive" "$(snell_download_url)"

  if [ -n "$SNELL_SHA256" ]; then
    printf '%s  %s\n' "$SNELL_SHA256" "$archive" | sha256sum -c -
  fi

  unzip -q -o "$archive" -d "$unpack_dir"
  [ -f "${unpack_dir}/snell-server" ] || die "Snell archive did not contain snell-server"
  temp_binary="${BINARY_PATH}.new.$$"
  install -m 755 "${unpack_dir}/snell-server" "$temp_binary"
  mv -f "$temp_binary" "$BINARY_PATH"
  rm -rf "$tmp_dir"
}

ensure_snell_user() {
  if ! getent group snell >/dev/null 2>&1; then
    groupadd --system snell
  fi
  if ! id snell >/dev/null 2>&1; then
    useradd --system --gid snell --home-dir /nonexistent --shell /usr/sbin/nologin snell
  fi
}

write_config() {
  local temp_config
  ensure_snell_user
  install -d -m 750 -o root -g snell "$CONFIG_DIR"
  backup_file "$CONFIG_FILE"
  temp_config="${RUN_DIR}/snell-server.conf.$$"
  cat >"$temp_config" <<CONF
[snell-server]
listen = 0.0.0.0:${SNELL_PORT}
psk = ${SNELL_PSK}
ipv6 = false
CONF
  install -m 640 -o root -g snell "$temp_config" "$CONFIG_FILE"
  rm -f "$temp_config"
}

remove_incompatible_service_dropins() {
  local backup_path
  local dropin
  local dropin_dir
  dropin_dir="${SERVICE_FILE}.d"
  if [ ! -d "$dropin_dir" ]; then
    return 0
  fi
  for dropin in "$dropin_dir"/*.conf; do
    [ -f "$dropin" ] || continue
    if grep -Eq '^[[:space:]]*(PrivateDevices|ProtectSystem|RestrictAddressFamilies|CapabilityBoundingSet)[[:space:]=]' "$dropin"; then
      log "Removing incompatible systemd hardening drop-in: $dropin"
      backup_path="${dropin}.bak.$(date +%Y%m%d%H%M%S)"
      cp -a "$dropin" "$backup_path"
      rm -f "$dropin"
    fi
  done
  rmdir "$dropin_dir" 2>/dev/null || true
}

write_service() {
  local temp_service
  backup_file "$SERVICE_FILE"
  remove_incompatible_service_dropins
  temp_service="${RUN_DIR}/snell-server.service.$$"
  cat >"$temp_service" <<SERVICE
[Unit]
Description=Snell Proxy Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=snell
Group=snell
ExecStart=${BINARY_PATH} -c ${CONFIG_FILE}
Restart=always
RestartSec=2
LimitNOFILE=1048576
UMask=0077

[Install]
WantedBy=multi-user.target
SERVICE
  install -m 644 -o root -g root "$temp_service" "$SERVICE_FILE"
  rm -f "$temp_service"
}

configure_ufw() {
  local ssh_port
  local ssh_ports
  local ufw_status
  if [ "$SNELL_OPEN_UFW" != true ]; then
    return
  fi
  if ! command -v ufw >/dev/null 2>&1; then
    log "ufw is not installed; skipping firewall rule"
    return
  fi
  ssh_ports="$({ /usr/sbin/sshd -T 2>/dev/null || true; } | awk '$1 == "port" { print $2 }')"
  [ -n "$ssh_ports" ] || ssh_ports="22"
  for ssh_port in $ssh_ports; do
    ufw allow "${ssh_port}/tcp" comment ssh
  done
  ufw allow "${SNELL_PORT}/tcp" comment snell
  ufw allow "${SNELL_PORT}/udp" comment snell
  ufw_status="$(ufw status | awk '/^Status:/ { print $2; exit }')"
  if [ "$ufw_status" != "active" ]; then
    ufw --force enable
  fi
}

swap_is_active() {
  local path=$1
  awk -v path="$path" 'NR > 1 && $1 == path { found=1 } END { exit found ? 0 : 1 }' /proc/swaps
}

file_size_bytes() {
  local path=$1
  if [ -e "$path" ]; then
    stat -c '%s' "$path"
  else
    printf '0'
  fi
}

create_swap_file() {
  local path=$1
  rm -f "$path"
  if ! fallocate -l "${SNELL_SWAP_SIZE_GIB}G" "$path" 2>/dev/null; then
    dd if=/dev/zero of="$path" bs=1M count=$((SNELL_SWAP_SIZE_GIB * 1024)) status=none
  fi
  chmod 600 "$path"
  mkswap -f "$path" >/dev/null
}

ensure_fstab_swap() {
  local temp_fstab
  backup_file /etc/fstab
  temp_fstab="${RUN_DIR}/fstab.$$"
  awk -v path="$SWAP_FILE" '($1 == path && $3 == "swap") { next } { print }' /etc/fstab >"$temp_fstab"
  printf '%s none swap sw 0 0\n' "$SWAP_FILE" >>"$temp_fstab"
  install -m 644 -o root -g root "$temp_fstab" /etc/fstab
  rm -f "$temp_fstab"
}

configure_swap() {
  local current_size
  local required_size
  local temp_swap
  if [ "$SNELL_ENSURE_SWAP" != true ]; then
    return
  fi
  command -v mkswap >/dev/null 2>&1 || die "mkswap is required"
  command -v swapon >/dev/null 2>&1 || die "swapon is required"
  command -v swapoff >/dev/null 2>&1 || die "swapoff is required"
  required_size=$((SNELL_SWAP_SIZE_GIB * 1024 * 1024 * 1024))
  current_size="$(file_size_bytes "$SWAP_FILE")"
  if [ "$current_size" -lt "$required_size" ]; then
    temp_swap="${SWAP_FILE}.surge-patch-new"
    create_swap_file "$temp_swap"
    if swap_is_active "$SWAP_FILE"; then
      swapoff "$SWAP_FILE"
    fi
    rm -f "$SWAP_FILE"
    mv "$temp_swap" "$SWAP_FILE"
  fi
  chmod 600 "$SWAP_FILE"
  if ! swap_is_active "$SWAP_FILE"; then
    if ! swapon "$SWAP_FILE" 2>/dev/null; then
      mkswap -f "$SWAP_FILE" >/dev/null
      swapon "$SWAP_FILE"
    fi
  fi
  rm -f "${SWAP_FILE}.surge-patch-new"
  ensure_fstab_swap
}

start_service() {
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME" >/dev/null
  systemctl restart "$SERVICE_NAME"
}

verify_installation() {
  local attempt=0
  systemctl is-active --quiet "$SERVICE_NAME" || die "snell-server is not active"
  command -v ss >/dev/null 2>&1 || return
  while [ "$attempt" -lt 10 ]; do
    if ss -tuln | awk -v port=":${SNELL_PORT}" '$0 ~ port { found=1 } END { exit found ? 0 : 1 }'; then
      return
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  die "snell-server is active but port ${SNELL_PORT} was not found"
}

public_ip() {
  curl -4fsS --max-time 5 https://icanhazip.com 2>/dev/null ||
    hostname -I 2>/dev/null | awk '{ print $1 }' ||
    printf 'UNKNOWN_IP'
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

append_json_item() {
  local current=$1
  local item=$2
  if [ -n "$current" ]; then
    printf '%s," %s"' "$current" "$(json_escape "$item")" | sed 's/," /,"/'
  else
    printf '"%s"' "$(json_escape "$item")"
  fi
}

nonzero() {
  [ -n "$1" ] && [ "$1" != "0" ]
}

write_audit_raw() {
  local raw_file=$1
  {
    printf '## identity\n'
    hostname -f 2>/dev/null || hostname 2>/dev/null || true
    date -u '+%Y-%m-%dT%H:%M:%SZ' || true
    uname -a || true
    printf '\n## snell_binary\n'
    if [ -x "$BINARY_PATH" ]; then
      "$BINARY_PATH" -v 2>&1 || true
      sha256sum "$BINARY_PATH" 2>/dev/null || true
    else
      printf 'missing %s\n' "$BINARY_PATH"
    fi
    printf '\n## snell_config\n'
    if [ -r "$CONFIG_FILE" ]; then
      sed -n '1,80p' "$CONFIG_FILE"
    else
      printf 'missing/unreadable %s\n' "$CONFIG_FILE"
    fi
    printf '\n## service_state\n'
    systemctl show "$SERVICE_NAME" -p ActiveState -p SubState -p Result -p NRestarts -p LimitNOFILE 2>/dev/null || true
    systemctl is-enabled "$SERVICE_NAME" 2>/dev/null || true
    printf '\n## service_files\n'
    systemctl cat "$SERVICE_NAME" 2>/dev/null || true
    printf '\n## listeners\n'
    ss -lntup 2>/dev/null | awk -v port=":${SNELL_PORT}" '$0 ~ port { print }' || true
    printf '\n## journal_recent\n'
    journalctl -u "$SERVICE_NAME" --since "$SNELL_JOURNAL_SINCE" --no-pager 2>/dev/null |
      awk '/WARN|ERROR|assert|Failed|failed|exited|signal 6|Decryption failed|DNS error|connect error/ { print }' |
      tail -120 || true
    printf '\n## summary_kv\n'
    audit_summary_kv
  } >"$raw_file"
}

audit_summary_kv() {
  local active
  local apt_duplicate_sources
  local decryption_total
  local hardening_mentions
  local nofile
  local restarts
  local sub
  local tcp_listen
  local top_decryption
  local udp_crash_markers
  local udp_listen
  local version
  version="$("$BINARY_PATH" -v 2>&1 | sed -n 's/^.*snell-server /snell-server /p' | head -1 || true)"
  active="$(systemctl show "$SERVICE_NAME" -p ActiveState --value 2>/dev/null || true)"
  sub="$(systemctl show "$SERVICE_NAME" -p SubState --value 2>/dev/null || true)"
  restarts="$(systemctl show "$SERVICE_NAME" -p NRestarts --value 2>/dev/null || true)"
  nofile="$(systemctl show "$SERVICE_NAME" -p LimitNOFILE --value 2>/dev/null || true)"
  if command -v ss >/dev/null 2>&1; then
    tcp_listen="$(ss -lntup 2>/dev/null | awk -v port=":${SNELL_PORT}" '$0 ~ port && $1 == "tcp" { found=1 } END { print found ? "yes" : "no" }')"
    udp_listen="$(ss -lntup 2>/dev/null | awk -v port=":${SNELL_PORT}" '$0 ~ port && $1 == "udp" { found=1 } END { print found ? "yes" : "no" }')"
  else
    tcp_listen="no"
    udp_listen="no"
  fi
  hardening_mentions="$({ systemctl cat "$SERVICE_NAME" 2>/dev/null || true; } | awk '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*(PrivateDevices|ProtectSystem|RestrictAddressFamilies|CapabilityBoundingSet)[[:space:]=]/ { count++ }
    END { print count + 0 }
  ')"
  apt_duplicate_sources=0
  if [ -f /etc/apt/sources.list.d/debian-security-autofix.list ] &&
    [ -f /etc/apt/sources.list ] &&
    grep -q 'security.debian.org/debian-security' /etc/apt/sources.list.d/debian-security-autofix.list &&
    grep -q 'security.debian.org/debian-security' /etc/apt/sources.list; then
    apt_duplicate_sources=1
  fi
  decryption_total="$({ journalctl -u "$SERVICE_NAME" --since "$SNELL_JOURNAL_SINCE" --no-pager 2>/dev/null || true; } | awk '/Decryption failed/ { count++ } END { print count + 0 }')"
  udp_crash_markers="$({ journalctl -u "$SERVICE_NAME" --since "$SNELL_JOURNAL_SINCE" --no-pager 2>/dev/null || true; } | awk '/UDP socket send error|uv_close|signal 6|Main process exited|Failed with result/ { count++ } END { print count + 0 }')"
  top_decryption="$({ journalctl -u "$SERVICE_NAME" --since "$SNELL_JOURNAL_SINCE" --no-pager 2>/dev/null || true; } | awk '/Decryption failed/ { count[$NF]++ } END { topc=0; topip="-"; for (ip in count) if (count[ip] > topc) { topc=count[ip]; topip=ip } print topc ":" topip }')"
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
}

audit_result_json() {
  local active
  local apt_dupes
  local crashes
  local decryption
  local failed_checks=""
  local hardening
  local nofile
  local raw_file=$1
  local restarts
  local status
  local sub
  local tcp_listen
  local top_decryption
  local udp_listen
  local version
  local warning_checks=""

  active="$(summary_value active "$raw_file")"
  sub="$(summary_value sub "$raw_file")"
  restarts="$(summary_value restarts "$raw_file")"
  nofile="$(summary_value nofile "$raw_file")"
  version="$(summary_value version "$raw_file")"
  tcp_listen="$(summary_value tcp_listen "$raw_file")"
  udp_listen="$(summary_value udp_listen "$raw_file")"
  hardening="$(summary_value hardening_mentions "$raw_file")"
  apt_dupes="$(summary_value apt_duplicate_sources "$raw_file")"
  decryption="$(summary_value decryption_total "$raw_file")"
  top_decryption="$(summary_value top_decryption "$raw_file")"
  crashes="$(summary_value udp_crash_markers "$raw_file")"

  [ "$active" = "active" ] || failed_checks="$(append_json_item "$failed_checks" "service_inactive")"
  [ "$sub" = "running" ] || failed_checks="$(append_json_item "$failed_checks" "service_not_running")"
  [ "$tcp_listen" = "yes" ] || failed_checks="$(append_json_item "$failed_checks" "tcp_not_listening")"
  [ "$udp_listen" = "yes" ] || failed_checks="$(append_json_item "$failed_checks" "udp_not_listening")"
  nonzero "$hardening" && failed_checks="$(append_json_item "$failed_checks" "systemd_hardening_present")"
  nonzero "$apt_dupes" && failed_checks="$(append_json_item "$failed_checks" "apt_duplicate_security_sources")"
  nonzero "$crashes" && failed_checks="$(append_json_item "$failed_checks" "udp_crash_markers_present")"
  nonzero "$decryption" && warning_checks="$(append_json_item "$warning_checks" "decryption_failed_seen")"

  status="ok"
  if [ -n "$failed_checks" ]; then
    status="issue"
  elif [ -n "$warning_checks" ]; then
    status="warn"
  fi

  printf '{'
  printf '"status":"%s","operation":"audit-snell","port":"%s","failed_checks":[%s],"warning_checks":[%s],"raw_log":"%s","values":{' \
    "$status" "$(json_escape "$SNELL_PORT")" "$failed_checks" "$warning_checks" "$(json_escape "$raw_file")"
  printf '"version":"%s","active":"%s","sub":"%s","restarts":"%s","nofile":"%s"' \
    "$(json_escape "$version")" "$(json_escape "$active")" "$(json_escape "$sub")" "$(json_escape "$restarts")" "$(json_escape "$nofile")"
  printf ',"tcp_listen":"%s","udp_listen":"%s","hardening_mentions":"%s","apt_duplicate_sources":"%s"' \
    "$(json_escape "$tcp_listen")" "$(json_escape "$udp_listen")" "$(json_escape "$hardening")" "$(json_escape "$apt_dupes")"
  printf ',"decryption_total":"%s","top_decryption":"%s","udp_crash_markers":"%s"}}' \
    "$(json_escape "$decryption")" "$(json_escape "$top_decryption")" "$(json_escape "$crashes")"
}

run_audit() {
  local payload
  local raw_file="${LOG_DIR}/audit_raw.log"
  validate_common
  write_audit_raw "$raw_file"
  payload="$(audit_result_json "$raw_file")"
  write_result "$payload"
  case "$payload" in
  *'"status":"issue"'*)
    exit 1
    ;;
  esac
}

run_install() {
  local audit_payload
  local ip
  local payload
  local proxy_line
  local raw_file="${LOG_DIR}/post_install_audit_raw.log"
  validate_common
  validate_snell_version_required
  validate_psk
  require_root_debian_systemd
  validate_architecture
  [ -n "$SNELL_NAME" ] || SNELL_NAME="$(hostname -s 2>/dev/null || hostname 2>/dev/null || printf 'snell-vps')"
  choose_psk
  configure_swap
  install_dependencies
  download_snell
  write_config
  write_service
  configure_ufw
  start_service
  verify_installation
  write_audit_raw "$raw_file"
  audit_payload="$(audit_result_json "$raw_file")"
  ip="$(public_ip)"
  proxy_line="${SNELL_NAME} = snell, ${ip}, ${SNELL_PORT}, psk=${SNELL_PSK}, version=$(major_version)"
  payload=$(printf '{')
  payload="${payload}\"status\":\"installed\""
  payload="${payload},\"operation\":\"install-snell\""
  payload="${payload},\"persistent_effects\":[\"install_or_replace_/usr/local/bin/snell-server\",\"backup_and_replace_/etc/snell/snell-server.conf\",\"backup_and_replace_/etc/systemd/system/snell-server.service\",\"remove_incompatible_snell_systemd_hardening_dropins\",\"enable_and_restart_snell-server\""
  if [ "$SNELL_OPEN_UFW" = true ]; then
    payload="${payload},\"allow_snell_tcp_udp_in_ufw\""
  fi
  if [ "$SNELL_ENSURE_SWAP" = true ]; then
    payload="${payload},\"ensure_swapfile_and_fstab_entry\""
  fi
  payload="${payload}]"
  payload="${payload},\"name\":\"$(json_escape "$SNELL_NAME")\""
  payload="${payload},\"public_ip\":\"$(json_escape "$ip")\""
  payload="${payload},\"port\":\"$(json_escape "$SNELL_PORT")\""
  payload="${payload},\"psk\":\"$(json_escape "$SNELL_PSK")\""
  payload="${payload},\"version\":\"$(json_escape "$(major_version)")\""
  payload="${payload},\"snell_version\":\"$(json_escape "$SNELL_VERSION")\""
  payload="${payload},\"config_file\":\"$(json_escape "$CONFIG_FILE")\""
  payload="${payload},\"service_file\":\"$(json_escape "$SERVICE_FILE")\""
  payload="${payload},\"surge_proxy_line\":\"$(json_escape "$proxy_line")\""
  payload="${payload},\"post_install_audit\":${audit_payload}}"
  write_result "$payload"
}

case "$SURGE_PATCH_OPERATION" in
install-snell)
  run_install
  ;;
audit-snell)
  run_audit
  ;;
*)
  die "unsupported SURGE_PATCH_OPERATION: ${SURGE_PATCH_OPERATION}"
  ;;
esac
