#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="${0##*/}"

DEFAULT_PORT="14180"
DEFAULT_SWAP_SIZE_GIB="4"

SNELL_VERSION=""
SNELL_SHA256=""
SWAP_SIZE_GIB="$DEFAULT_SWAP_SIZE_GIB"
SNELL_USER="snell"
SNELL_GROUP="snell"

BINARY_PATH="/usr/local/bin/snell-server"
CONFIG_DIR="/etc/snell"
CONFIG_FILE="${CONFIG_DIR}/snell-server.conf"
SERVICE_FILE="/etc/systemd/system/snell-server.service"
SWAP_FILE="/swapfile"

PORT="$DEFAULT_PORT"
PSK=""
VPS_NAME=""

DRY_RUN=false
VERBOSE=false
REPLACE_PSK=false
OPEN_UFW=false
ENSURE_SWAP=false

TMP_DIR=""
WARNINGS=""

RED='\033[0;31m'
YELLOW='\033[1;33m'
GRAY='\033[0;90m'
NC='\033[0m'

if [ ! -t 2 ]; then
  RED=''
  YELLOW=''
  GRAY=''
  NC=''
fi

log() {
  local message=$1
  local color=$GRAY
  local prefix="[INFO]"

  if [ "${2:-}" = "error" ]; then
    color=$RED
    prefix="[ERROR]"
  elif [ "$DRY_RUN" = true ]; then
    color=$YELLOW
    prefix="[DRY-RUN]"
  fi

  printf '%b%s%b %s\n' "$color" "$prefix" "$NC" "$message" >&2
}

debug() {
  if [ "$VERBOSE" = true ]; then
    log "$1"
  fi
}

die() {
  log "$1" error
  exit 1
}

usage() {
  local exit_code=${1:-0}

  cat <<EOF
Usage: ${SCRIPT_NAME} [options]

Install or upgrade Snell proxy server on a Debian-based VPS.

Persistent effects:
  - Back up and replace ${CONFIG_FILE}
  - Back up and replace ${SERVICE_FILE}
  - Install ${BINARY_PATH}
  - Enable and restart snell-server
  - Remove incompatible systemd hardening drop-ins when detected

Options:
  --snell-version <version>  Snell version to install; check official release notes first
  --name <name>              Name used in the final Surge line (default: hostname)
  --port <port>              Port for Snell to listen on (default: ${DEFAULT_PORT})
  --psk <PSK>                Pre-shared key; generated on first install
  --replace-psk              Generate a new PSK instead of reusing the existing config PSK
  --sha256 <sha256>          Optional sha256 checksum for the Snell zip archive
  --open-ufw                 Persistently allow Snell TCP/UDP with ufw; if ufw is inactive,
                             allow detected SSH ports, then enable ufw
  --ensure-swap              Ensure a persistent ${DEFAULT_SWAP_SIZE_GIB} GiB /swapfile and /etc/fstab entry
  --swap-size-gib <number>   Swap file size; also enables --ensure-swap (default: ${DEFAULT_SWAP_SIZE_GIB})
  --dry-run                  Show what would be done without making changes
  --verbose                  Show extra progress information
  --help                     Show this help message

Output:
  --dry-run prints one JSON object to stdout and writes diagnostics to stderr.
  A successful install prints one JSON object to stdout and writes progress to stderr.

Examples:
  ${SCRIPT_NAME} --snell-version <version>
  ${SCRIPT_NAME} --snell-version <version> --name my-snell-vps --port 14180 --open-ufw --ensure-swap
  ${SCRIPT_NAME} --snell-version <version> --dry-run
EOF

  exit "$exit_code"
}

cleanup() {
  if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
    rm -rf "$TMP_DIR"
  fi
}

trap cleanup EXIT

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

append_warning() {
  if [ -n "$WARNINGS" ]; then
    WARNINGS="${WARNINGS},"
  fi
  WARNINGS="${WARNINGS}\"$1\""
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
    --name)
      [ "$#" -ge 2 ] || die "--name requires a value"
      VPS_NAME=$2
      shift 2
      ;;
    --port)
      [ "$#" -ge 2 ] || die "--port requires a value"
      PORT=$2
      shift 2
      ;;
    --psk)
      [ "$#" -ge 2 ] || die "--psk requires a value"
      PSK=$2
      shift 2
      ;;
    --snell-version)
      [ "$#" -ge 2 ] || die "--snell-version requires a value"
      SNELL_VERSION=$2
      shift 2
      ;;
    --sha256)
      [ "$#" -ge 2 ] || die "--sha256 requires a value"
      SNELL_SHA256=$2
      shift 2
      ;;
    --replace-psk)
      REPLACE_PSK=true
      shift
      ;;
    --open-ufw)
      OPEN_UFW=true
      shift
      ;;
    --ensure-swap)
      ENSURE_SWAP=true
      shift
      ;;
    --swap-size-gib)
      [ "$#" -ge 2 ] || die "--swap-size-gib requires a value"
      SWAP_SIZE_GIB=$2
      ENSURE_SWAP=true
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --verbose)
      VERBOSE=true
      shift
      ;;
    --help)
      usage 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "Invalid option: $1"
      ;;
    *)
      die "Unexpected argument: $1"
      ;;
    esac
  done
}

require_supported_system() {
  command -v apt-get >/dev/null 2>&1 || die "This script only supports Debian-based systems"
  command -v systemctl >/dev/null 2>&1 || die "systemd is required"

  if [ "$DRY_RUN" != true ] && [ "$(id -u)" -ne 0 ]; then
    die "Run as root, or use --dry-run to preview"
  fi
}

detect_defaults() {
  if [ -z "$VPS_NAME" ]; then
    VPS_NAME="$(hostname -s 2>/dev/null || hostname 2>/dev/null || printf 'vps')"
  fi
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

validate_psk() {
  if [ -z "$PSK" ]; then
    return
  fi

  case "$PSK" in
  *','* | *' '* | *'	'*)
    die "PSK must not contain commas or whitespace"
    ;;
  esac
}

validate_swap_size() {
  if [ "$ENSURE_SWAP" != true ]; then
    return
  fi

  case "$SWAP_SIZE_GIB" in
  '' | *[!0-9]*)
    die "--swap-size-gib must be a positive integer: $SWAP_SIZE_GIB"
    ;;
  esac

  if [ "$SWAP_SIZE_GIB" -lt 1 ]; then
    die "--swap-size-gib must be at least 1: $SWAP_SIZE_GIB"
  fi
}

validate_snell_version() {
  if [ -z "$SNELL_VERSION" ]; then
    die "--snell-version is required. Check official Snell release notes, then pass the chosen version."
  fi

  case "$SNELL_VERSION" in
  *[!A-Za-z0-9._-]*)
    die "--snell-version contains unsupported characters: $SNELL_VERSION"
    ;;
  esac
}

validate_architecture() {
  local arch
  arch="$(uname -m)"

  case "$arch" in
  x86_64 | amd64)
    ;;
  *)
    die "Only x86_64/amd64 architecture is supported, got: $arch"
    ;;
  esac
}

snell_binary_name() {
  printf 'snell-server-v%s-linux-amd64.zip' "$SNELL_VERSION"
}

snell_download_url() {
  printf 'https://dl.nssurge.com/snell/%s' "$(snell_binary_name)"
}

major_version() {
  printf '%s' "${SNELL_VERSION%%.*}"
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

  if [ -n "$PSK" ]; then
    debug "Using PSK provided by --psk"
    return
  fi

  if [ "$REPLACE_PSK" != true ]; then
    existing_psk="$(existing_config_value psk || true)"
    if [ -n "$existing_psk" ]; then
      PSK="$existing_psk"
      debug "Reusing PSK from existing config"
      return
    fi
  fi

  PSK="$(generate_psk)"
}

print_dry_run() {
  local psk_source
  local sha256_provided

  if [ -n "$PSK" ]; then
    psk_source="provided"
  elif [ "$REPLACE_PSK" = true ]; then
    psk_source="generated_new"
  else
    psk_source="reuse_existing_or_generate"
  fi

  sha256_provided=false
  if [ -n "$SNELL_SHA256" ]; then
    sha256_provided=true
  fi

  printf '{'
  printf '"action":"install_snell_server"'
  printf ',"dry_run":true'
  printf ',"name":"%s"' "$(json_escape "$VPS_NAME")"
  printf ',"snell_version":"%s"' "$(json_escape "$SNELL_VERSION")"
  printf ',"major_version":"%s"' "$(json_escape "$(major_version)")"
  printf ',"binary":"%s"' "$(json_escape "$(snell_binary_name)")"
  printf ',"download_url":"%s"' "$(json_escape "$(snell_download_url)")"
  printf ',"port":"%s"' "$(json_escape "$PORT")"
  printf ',"psk_source":"%s"' "$psk_source"
  printf ',"user":"%s"' "$(json_escape "$SNELL_USER")"
  printf ',"config_file":"%s"' "$(json_escape "$CONFIG_FILE")"
  printf ',"service_file":"%s"' "$(json_escape "$SERVICE_FILE")"
  printf ',"replace_psk":%s' "$(json_bool "$REPLACE_PSK")"
  printf ',"open_ufw":%s' "$(json_bool "$OPEN_UFW")"
  printf ',"ensure_swap":%s' "$(json_bool "$ENSURE_SWAP")"
  printf ',"swap_size_gib":"%s"' "$(json_escape "$SWAP_SIZE_GIB")"
  printf ',"sha256_provided":%s' "$(json_bool "$sha256_provided")"
  printf ',"warnings":[]'
  printf ',"persistent_effects":["install_binary","backup_and_replace_config","backup_and_replace_systemd_service","remove_incompatible_hardening_dropin_when_detected","enable_and_restart_service"'
  if [ "$OPEN_UFW" = true ]; then
    printf ',"allow_snell_tcp_udp_and_maybe_enable_ufw"'
  fi
  if [ "$ENSURE_SWAP" = true ]; then
    printf ',"ensure_swapfile_and_fstab_entry"'
  fi
  printf ']'
  printf '}\n'
}

backup_file() {
  local path=$1

  if [ -f "$path" ]; then
    cp -a "$path" "${path}.bak.$(date +%Y%m%d%H%M%S)"
  fi
}

install_dependencies() {
  log "Installing dependencies..."
  DEBIAN_FRONTEND=noninteractive apt-get update -qq >&2
  DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl unzip >&2
}

download_snell() {
  local archive
  local unpack_dir

  TMP_DIR="$(mktemp -d)"
  archive="${TMP_DIR}/$(snell_binary_name)"
  unpack_dir="${TMP_DIR}/unpack"

  mkdir -p "$unpack_dir"

  log "Downloading Snell $(snell_binary_name)..."
  curl --fail --location --show-error --silent --connect-timeout 10 --retry 3 \
    --output "$archive" "$(snell_download_url)"

  if [ -n "$SNELL_SHA256" ]; then
    printf '%s  %s\n' "$SNELL_SHA256" "$archive" | sha256sum -c - >&2
  fi

  unzip -q -o "$archive" -d "$unpack_dir"

  if [ ! -f "${unpack_dir}/snell-server" ]; then
    die "Archive did not contain snell-server"
  fi

  install -m 755 "${unpack_dir}/snell-server" "$BINARY_PATH"
}

ensure_snell_user() {
  if ! getent group "$SNELL_GROUP" >/dev/null 2>&1; then
    groupadd --system "$SNELL_GROUP"
  fi

  if ! id "$SNELL_USER" >/dev/null 2>&1; then
    useradd --system --gid "$SNELL_GROUP" --home-dir /nonexistent --shell /usr/sbin/nologin "$SNELL_USER"
  fi
}

write_config() {
  local temp_config

  log "Writing Snell config..."
  ensure_snell_user

  install -d -m 750 -o root -g "$SNELL_GROUP" "$CONFIG_DIR"
  backup_file "$CONFIG_FILE"

  temp_config="${TMP_DIR:-/tmp}/snell-server.conf.$$"
  cat >"$temp_config" <<CONF
[snell-server]
listen = 0.0.0.0:${PORT}
psk = ${PSK}
ipv6 = false
CONF

  install -m 640 -o root -g "$SNELL_GROUP" "$temp_config" "$CONFIG_FILE"
  rm -f "$temp_config"
}

remove_incompatible_service_dropins() {
  local backup_path
  local dropin_dir
  local hardening_dropin

  dropin_dir="${SERVICE_FILE}.d"
  hardening_dropin="${dropin_dir}/hardening.conf"

  if [ ! -f "$hardening_dropin" ]; then
    return
  fi

  if grep -Eq 'PrivateDevices|ProtectSystem|RestrictAddressFamilies|CapabilityBoundingSet' "$hardening_dropin"; then
    log "Removing incompatible systemd hardening drop-in..."
    backup_path="${SERVICE_FILE}.hardening.conf.bak.$(date +%Y%m%d%H%M%S)"
    cp -a "$hardening_dropin" "$backup_path"
    rm -f "$hardening_dropin"
    rmdir "$dropin_dir" 2>/dev/null || true
  fi
}

write_service() {
  local temp_service

  log "Writing systemd service..."
  backup_file "$SERVICE_FILE"
  remove_incompatible_service_dropins

  temp_service="${TMP_DIR:-/tmp}/snell-server.service.$$"
  cat >"$temp_service" <<SERVICE
[Unit]
Description=Snell Proxy Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SNELL_USER}
Group=${SNELL_GROUP}
ExecStart=${BINARY_PATH} -c ${CONFIG_FILE}
Restart=always
RestartSec=2
LimitNOFILE=1048576
UMask=0077
# Keep this service intentionally minimal. systemd sandboxing such as
# PrivateDevices, ProtectSystem, or RestrictAddressFamilies has broken Snell v5 UDP/QUIC.

[Install]
WantedBy=multi-user.target
SERVICE

  install -m 644 -o root -g root "$temp_service" "$SERVICE_FILE"
  rm -f "$temp_service"
}

configure_ufw() {
  local ssh_ports
  local ssh_port
  local ufw_status

  if [ "$OPEN_UFW" != true ]; then
    return
  fi

  if ! command -v ufw >/dev/null 2>&1; then
    log "ufw is not installed; skipping firewall rule"
    append_warning "ufw_not_installed"
    return
  fi

  log "Allowing Snell port with ufw..."

  if [ -x /usr/sbin/sshd ]; then
    ssh_ports="$({ /usr/sbin/sshd -T 2>/dev/null || true; } | awk '$1 == "port" { print $2 }')"
  else
    ssh_ports=""
  fi

  if [ -z "$ssh_ports" ]; then
    ssh_ports="22"
  fi

  for ssh_port in $ssh_ports; do
    ufw allow "${ssh_port}/tcp" comment ssh >&2
  done

  ufw allow "${PORT}/tcp" comment snell >&2
  ufw allow "${PORT}/udp" comment snell >&2

  ufw_status="$(ufw status | awk '/^Status:/ { print $2; exit }')"
  if [ "$ufw_status" != "active" ]; then
    ufw --force enable >&2
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

  if ! fallocate -l "${SWAP_SIZE_GIB}G" "$path" 2>/dev/null; then
    dd if=/dev/zero of="$path" bs=1M count=$((SWAP_SIZE_GIB * 1024)) status=none
  fi

  chmod 600 "$path"
  mkswap -f "$path" >/dev/null
}

ensure_fstab_swap() {
  local temp_fstab

  backup_file /etc/fstab

  temp_fstab="${TMP_DIR:-/tmp}/fstab.$$"
  awk -v path="$SWAP_FILE" '($1 == path && $3 == "swap") { next } { print }' /etc/fstab >"$temp_fstab"
  printf '%s none swap sw 0 0\n' "$SWAP_FILE" >>"$temp_fstab"
  install -m 644 -o root -g root "$temp_fstab" /etc/fstab
  rm -f "$temp_fstab"
}

configure_swap() {
  local current_size
  local required_size
  local temp_swap

  if [ "$ENSURE_SWAP" != true ]; then
    return
  fi

  log "Ensuring ${SWAP_SIZE_GIB} GiB swap file..."

  command -v mkswap >/dev/null 2>&1 || die "mkswap is required to configure swap"
  command -v swapon >/dev/null 2>&1 || die "swapon is required to configure swap"
  command -v swapoff >/dev/null 2>&1 || die "swapoff is required to configure swap"

  required_size=$((SWAP_SIZE_GIB * 1024 * 1024 * 1024))
  current_size="$(file_size_bytes "$SWAP_FILE")"

  if [ "$current_size" -lt "$required_size" ]; then
    temp_swap="${SWAP_FILE}.snell-new"
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

  rm -f "${SWAP_FILE}.snell-new"
  ensure_fstab_swap
}

start_service() {
  log "Starting Snell service..."
  systemctl daemon-reload
  systemctl enable snell-server >/dev/null
  systemctl restart snell-server
}

verify_installation() {
  local attempt=0

  systemctl is-active --quiet snell-server || die "snell-server is not active"

  if ! command -v ss >/dev/null 2>&1; then
    append_warning "ss_not_installed_skip_listener_verification"
    return
  fi

  while [ "$attempt" -lt 10 ]; do
    if ss -tuln | awk -v port=":${PORT}" '$0 ~ port { found=1 } END { exit found ? 0 : 1 }'; then
      return
    fi

    attempt=$((attempt + 1))
    sleep 1
  done

  die "snell-server is active but port ${PORT} was not found in ss output"
}

public_ip() {
  curl -4fsS --max-time 5 https://icanhazip.com 2>/dev/null ||
    hostname -I 2>/dev/null | awk '{print $1}' ||
    printf 'UNKNOWN_IP'
}

print_result() {
  local ip
  local surge_proxy_line
  ip="$(public_ip)"
  surge_proxy_line="${VPS_NAME} = snell, ${ip}, ${PORT}, psk=${PSK}, version=$(major_version)"

  printf '{'
  printf '"status":"installed"'
  printf ',"name":"%s"' "$(json_escape "$VPS_NAME")"
  printf ',"public_ip":"%s"' "$(json_escape "$ip")"
  printf ',"port":"%s"' "$(json_escape "$PORT")"
  printf ',"psk":"%s"' "$(json_escape "$PSK")"
  printf ',"version":"%s"' "$(json_escape "$(major_version)")"
  printf ',"snell_version":"%s"' "$(json_escape "$SNELL_VERSION")"
  printf ',"config_file":"%s"' "$(json_escape "$CONFIG_FILE")"
  printf ',"service_file":"%s"' "$(json_escape "$SERVICE_FILE")"
  printf ',"warnings":[%s]' "$WARNINGS"
  printf ',"surge_proxy_line":"%s"' "$(json_escape "$surge_proxy_line")"
  printf '}\n'
}

main() {
  parse_args "$@"
  detect_defaults
  validate_port
  validate_psk
  validate_swap_size
  validate_snell_version

  if [ "$DRY_RUN" = true ]; then
    print_dry_run
    exit 0
  fi

  validate_architecture
  require_supported_system

  choose_psk
  configure_swap
  install_dependencies
  download_snell
  write_config
  write_service
  configure_ufw
  start_service
  verify_installation
  print_result
}

main "$@"
