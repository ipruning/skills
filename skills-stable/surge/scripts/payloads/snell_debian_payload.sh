#!/usr/bin/env bash
set -Eeuo pipefail

RUN_DIR="${RUN_DIR:-$(pwd)}"
INPUT_ENV="${RUN_DIR}/input.env"
LOG_DIR="${RUN_DIR}/logs"
RESULT_FILE="${RUN_DIR}/result.json"
STDOUT_JSON_EMITTED=false

SERVICE_NAME="snell-server"
DEFAULT_BINARY_PATH="/usr/local/bin/snell-server"
DEFAULT_CONFIG_FILE="/etc/snell/snell-server.conf"

SNELL_AUDIT_OPERATION=""
SNELL_PORT="14180"
SNELL_JOURNAL_SINCE="10 min ago"

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
    "$(json_escape "$SNELL_AUDIT_OPERATION")" \
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

validate_common() {
  [ -r "$INPUT_ENV" ] || die "missing input.env"
  validate_port
}

trim() {
  awk '{$1=$1; print}'
}

kv() {
  local key=$1
  local value=${2:-}
  printf '%s=%s\n' "$key" "$value"
}

service_cat() {
  systemctl cat "$SERVICE_NAME" 2>/dev/null || true
}

service_show() {
  local prop=$1
  systemctl show "$SERVICE_NAME" -p "$prop" --value 2>/dev/null || true
}

detect_exec_start_line() {
  service_cat | awk -F= '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*ExecStart=/ {
      line=$0
      sub(/^[^=]*=/, "", line)
      print line
    }
  ' | tail -1
}

detect_binary_path() {
  local exec_line=$1
  if [ -n "$exec_line" ]; then
    # shellcheck disable=SC2086 # ExecStart is intentionally tokenized like systemd does.
    set -- $exec_line
    if [ -n "${1:-}" ]; then
      printf '%s' "$1"
      return
    fi
  fi
  printf '%s' "$DEFAULT_BINARY_PATH"
}

detect_config_file() {
  local exec_line=$1
  local previous=""
  if [ -n "$exec_line" ]; then
    # shellcheck disable=SC2086 # ExecStart is intentionally tokenized like systemd does.
    set -- $exec_line
    for token in "$@"; do
      if [ "$previous" = "-c" ]; then
        printf '%s' "$token"
        return
      fi
      previous="$token"
    done
  fi
  printf '%s' "$DEFAULT_CONFIG_FILE"
}

redact_config() {
  local config_file=$1
  if [ ! -r "$config_file" ]; then
    printf 'missing/unreadable %s\n' "$config_file"
    return
  fi
  awk -F= '
    {
      key=$1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
      lower=tolower(key)
      if (lower == "psk") {
        printf "%s = <redacted>\n", key
      } else {
        print
      }
    }
  ' "$config_file" | sed -n '1,120p'
}

config_value() {
  local config_file=$1
  local key=$2
  [ -r "$config_file" ] || return 0
  awk -F= -v wanted="$key" '
    {
      key=$1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
      if (tolower(key) == wanted) {
        value=$2
        sub(/^[[:space:]]*/, "", value)
        sub(/[[:space:]]*$/, "", value)
        print value
        exit
      }
    }
  ' "$config_file"
}

config_key_present() {
  local config_file=$1
  local key=$2
  [ -r "$config_file" ] || return 1
  awk -F= -v wanted="$key" '
    {
      key=$1
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
      if (tolower(key) == wanted) {
        found=1
      }
    }
    END { exit found ? 0 : 1 }
  ' "$config_file"
}

config_legacy_keys() {
  local config_file=$1
  local keys=""
  local key
  for key in ipv6 obfs reuse version; do
    if config_key_present "$config_file" "$key"; then
      if [ -n "$keys" ]; then
        keys="${keys},${key}"
      else
        keys="$key"
      fi
    fi
  done
  printf '%s' "$keys"
}

sshd_effective() {
  if command -v sshd >/dev/null 2>&1; then
    sshd -T 2>/dev/null || true
  elif [ -x /usr/sbin/sshd ]; then
    /usr/sbin/sshd -T 2>/dev/null || true
  fi
}

sshd_value() {
  local key=$1
  awk -v wanted="$key" '$1 == wanted { print $2; exit }' "${LOG_DIR}/sshd_effective.log" 2>/dev/null || true
}

root_authorized_keys_count() {
  local file="/root/.ssh/authorized_keys"
  if [ ! -r "$file" ]; then
    printf '0'
    return
  fi
  awk 'NF && $1 !~ /^#/ { count++ } END { print count + 0 }' "$file"
}

sysctl_value() {
  local key=$1
  sysctl -n "$key" 2>/dev/null || true
}

listener_present() {
  local proto=$1
  awk -v proto="$proto" -v port=":${SNELL_PORT}" '
    $0 ~ port && $1 ~ "^" proto { found=1 }
    END { print found ? "yes" : "no" }
  ' "${LOG_DIR}/listeners.log" 2>/dev/null || printf 'no'
}

ufw_status_value() {
  awk '/^Status:/ { print $2; exit }' "${LOG_DIR}/ufw_status.log" 2>/dev/null || true
}

ufw_port_proto_present() {
  local proto=$1
  awk -v port="${SNELL_PORT}/${proto}" '
    index($0, port) > 0 { found=1 }
    END { print found ? "yes" : "no" }
  ' "${LOG_DIR}/ufw_status.log" 2>/dev/null || printf 'no'
}

line_count_file() {
  local file=$1
  if [ -r "$file" ]; then
    wc -l <"$file" | tr -d ' '
  else
    printf '0'
  fi
}

collect_raw_logs() {
  local binary_path=$1
  local config_file=$2
  {
    printf '## identity\n'
    hostname -f 2>/dev/null || hostname 2>/dev/null || true
    date -u '+%Y-%m-%dT%H:%M:%SZ' || true
    uname -a || true

    printf '\n## snell_binary\n'
    if [ -x "$binary_path" ]; then
      "$binary_path" -v 2>&1 || true
      sha256sum "$binary_path" 2>/dev/null || true
    else
      printf 'missing %s\n' "$binary_path"
    fi

    printf '\n## snell_config_redacted\n'
    redact_config "$config_file"

    printf '\n## service_state\n'
    systemctl show "$SERVICE_NAME" \
      -p ActiveState -p SubState -p Result -p NRestarts -p LimitNOFILE \
      -p User -p Group -p Restart -p MainPID 2>/dev/null || true
    systemctl is-enabled "$SERVICE_NAME" 2>/dev/null || true

    printf '\n## listeners\n'
    cat "${LOG_DIR}/listeners.log" 2>/dev/null || true

    printf '\n## sshd_effective\n'
    cat "${LOG_DIR}/sshd_effective.log" 2>/dev/null || true

    printf '\n## ufw_status\n'
    cat "${LOG_DIR}/ufw_status.log" 2>/dev/null || true

    printf '\n## sysctl\n'
    cat "${LOG_DIR}/sysctl.log" 2>/dev/null || true

    printf '\n## journal_recent_filtered\n'
    cat "${LOG_DIR}/journal_recent.log" 2>/dev/null || true
  } >"${LOG_DIR}/audit_raw.log"
}

collect_supporting_files() {
  service_cat >"${LOG_DIR}/service_cat.log"
  ss -lntup >"${LOG_DIR}/listeners.log" 2>/dev/null || true
  sshd_effective >"${LOG_DIR}/sshd_effective.log"
  if command -v ufw >/dev/null 2>&1; then
    ufw status verbose >"${LOG_DIR}/ufw_status.log" 2>/dev/null || true
  else
    printf 'ufw unavailable\n' >"${LOG_DIR}/ufw_status.log"
  fi
  if command -v nft >/dev/null 2>&1; then
    nft list ruleset >"${LOG_DIR}/nft_ruleset.log" 2>/dev/null || true
  else
    printf 'nft unavailable\n' >"${LOG_DIR}/nft_ruleset.log"
  fi
  iptables -S >"${LOG_DIR}/iptables_rules.log" 2>/dev/null || true
  ip6tables -S >"${LOG_DIR}/ip6tables_rules.log" 2>/dev/null || true
  if command -v docker >/dev/null 2>&1; then
    docker ps --format '{{.ID}} {{.Names}} {{.Ports}}' >"${LOG_DIR}/docker_ports.log" 2>/dev/null || true
  else
    printf 'docker unavailable\n' >"${LOG_DIR}/docker_ports.log"
  fi
  {
    for key in \
      net.core.default_qdisc \
      net.ipv4.tcp_congestion_control \
      net.core.somaxconn \
      net.ipv4.tcp_max_syn_backlog \
      net.ipv4.tcp_syncookies \
      net.ipv4.ip_local_port_range \
      net.ipv4.ip_local_reserved_ports \
      net.ipv4.tcp_mtu_probing \
      net.netfilter.nf_conntrack_count \
      net.netfilter.nf_conntrack_max; do
      printf '%s=%s\n' "$key" "$(sysctl_value "$key")"
    done
  } >"${LOG_DIR}/sysctl.log"
  swapon --show --bytes >"${LOG_DIR}/swaps.log" 2>/dev/null || true
  df -Pk / /var /boot >"${LOG_DIR}/df.log" 2>/dev/null || df -Pk >"${LOG_DIR}/df.log" 2>/dev/null || true
  journalctl -u "$SERVICE_NAME" --since "$SNELL_JOURNAL_SINCE" -o short-iso --no-pager 2>/dev/null |
    awk '/WARN|ERROR|assert|Failed|failed|exited|signal 6|Decryption failed|DNS error|connect error|UDP socket send error|uv_close/ { print }' |
    tail -500 >"${LOG_DIR}/journal_recent.log" || true
}

hardening_directives() {
  awk '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*(PrivateDevices|ProtectSystem|RestrictAddressFamilies|CapabilityBoundingSet|NoNewPrivileges|PrivateTmp)[[:space:]=]/ {
      key=$1
      sub(/[=:].*/, "", key)
      seen[key]=1
    }
    END {
      first=1
      for (key in seen) {
        if (!first) {
          printf ","
        }
        printf "%s", key
        first=0
      }
    }
  ' "${LOG_DIR}/service_cat.log" 2>/dev/null || true
}

write_summary_kv() {
  local binary_path=$1
  local config_file=$2
  local directives
  local mem_total
  local swap_free
  local swap_total
  local root_available
  directives="$(hardening_directives)"
  mem_total="$(awk '/^MemTotal:/ { print $2; exit }' /proc/meminfo 2>/dev/null || true)"
  swap_total="$(awk '/^SwapTotal:/ { print $2; exit }' /proc/meminfo 2>/dev/null || true)"
  swap_free="$(awk '/^SwapFree:/ { print $2; exit }' /proc/meminfo 2>/dev/null || true)"
  root_available="$(df -Pk / 2>/dev/null | awk 'NR == 2 { print $4; exit }')"

  {
    kv schema_version "surge-snell.audit.remote.v1"
    kv collected_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ' || true)"
    kv hostname "$(hostname -f 2>/dev/null || hostname 2>/dev/null || true)"
    kv kernel "$(uname -r 2>/dev/null || true)"
    kv os_pretty_name "$(awk -F= '$1 == "PRETTY_NAME" { gsub(/"/, "", $2); print $2; exit }' /etc/os-release 2>/dev/null || true)"

    kv snell_port "$SNELL_PORT"
    kv snell_binary_path "$binary_path"
    if [ -x "$binary_path" ]; then
      kv snell_version_text "$("$binary_path" -v 2>&1 | head -1 || true)"
      kv snell_binary_sha256 "$(sha256sum "$binary_path" 2>/dev/null | awk '{ print $1 }')"
    else
      kv snell_version_text ""
      kv snell_binary_sha256 ""
    fi
    kv snell_config_path "$config_file"
    if [ -r "$config_file" ]; then
      kv config_present "yes"
      if config_key_present "$config_file" psk; then kv config_psk_present "yes"; else kv config_psk_present "no"; fi
      kv config_listen "$(config_value "$config_file" listen)"
      kv config_legacy_keys "$(config_legacy_keys "$config_file")"
      if config_key_present "$config_file" dns-ip-preference; then
        kv config_dns_ip_preference_present "yes"
      else
        kv config_dns_ip_preference_present "no"
      fi
    else
      kv config_present "no"
      kv config_psk_present "no"
      kv config_listen ""
      kv config_legacy_keys ""
      kv config_dns_ip_preference_present "no"
    fi

    kv systemd_active "$(service_show ActiveState)"
    kv systemd_sub "$(service_show SubState)"
    kv systemd_result "$(service_show Result)"
    kv systemd_nrestarts "$(service_show NRestarts)"
    kv systemd_limit_nofile "$(service_show LimitNOFILE)"
    kv systemd_user "$(service_show User)"
    kv systemd_group "$(service_show Group)"
    kv systemd_restart "$(service_show Restart)"
    kv systemd_main_pid "$(service_show MainPID)"
    if [ -n "$directives" ]; then
      kv systemd_hardening_mentions "$(printf '%s' "$directives" | awk -F, '{ print NF }')"
    else
      kv systemd_hardening_mentions "0"
    fi
    kv systemd_hardening_directives "$directives"

    kv tcp_listen "$(listener_present tcp)"
    kv udp_listen "$(listener_present udp)"

    kv ssh_permitrootlogin "$(sshd_value permitrootlogin)"
    kv ssh_passwordauthentication "$(sshd_value passwordauthentication)"
    kv ssh_kbdinteractiveauthentication "$(sshd_value kbdinteractiveauthentication)"
    kv ssh_pubkeyauthentication "$(sshd_value pubkeyauthentication)"
    kv ssh_maxauthtries "$(sshd_value maxauthtries)"
    kv ssh_authenticationmethods "$(sshd_value authenticationmethods)"
    kv ssh_root_authorized_keys_count "$(root_authorized_keys_count)"

    kv ufw_status "$(ufw_status_value)"
    kv ufw_snell_tcp "$(ufw_port_proto_present tcp)"
    kv ufw_snell_udp "$(ufw_port_proto_present udp)"
    kv nft_ruleset_lines "$(line_count_file "${LOG_DIR}/nft_ruleset.log")"
    kv iptables_rules_lines "$(line_count_file "${LOG_DIR}/iptables_rules.log")"
    kv ip6tables_rules_lines "$(line_count_file "${LOG_DIR}/ip6tables_rules.log")"
    if command -v docker >/dev/null 2>&1; then kv docker_present "yes"; else kv docker_present "no"; fi
    kv docker_published_ports_lines "$(awk 'index($0, "->") > 0 { count++ } END { print count + 0 }' "${LOG_DIR}/docker_ports.log" 2>/dev/null || true)"

    kv sysctl_net_core_default_qdisc "$(sysctl_value net.core.default_qdisc)"
    kv sysctl_net_ipv4_tcp_congestion_control "$(sysctl_value net.ipv4.tcp_congestion_control)"
    kv sysctl_net_core_somaxconn "$(sysctl_value net.core.somaxconn)"
    kv sysctl_net_ipv4_tcp_max_syn_backlog "$(sysctl_value net.ipv4.tcp_max_syn_backlog)"
    kv sysctl_net_ipv4_tcp_syncookies "$(sysctl_value net.ipv4.tcp_syncookies)"
    kv sysctl_net_ipv4_ip_local_port_range "$(sysctl_value net.ipv4.ip_local_port_range)"
    kv sysctl_net_ipv4_ip_local_reserved_ports "$(sysctl_value net.ipv4.ip_local_reserved_ports)"
    kv sysctl_net_ipv4_tcp_mtu_probing "$(sysctl_value net.ipv4.tcp_mtu_probing)"
    kv sysctl_net_netfilter_nf_conntrack_count "$(sysctl_value net.netfilter.nf_conntrack_count)"
    kv sysctl_net_netfilter_nf_conntrack_max "$(sysctl_value net.netfilter.nf_conntrack_max)"

    kv mem_total_kib "$mem_total"
    kv swap_total_kib "$swap_total"
    kv swap_free_kib "$swap_free"
    kv fstab_swap_entries "$(awk '$3 == "swap" { count++ } END { print count + 0 }' /etc/fstab 2>/dev/null || true)"
    kv root_available_kib "$root_available"
    kv journald_disk_usage "$(journalctl --disk-usage 2>&1 | tr '\n' ' ' | trim)"
  } >"${LOG_DIR}/audit_summary.kv"
}

run_audit() {
  local exec_line
  local binary_path
  local config_file
  validate_common
  exec_line="$(detect_exec_start_line)"
  binary_path="$(detect_binary_path "$exec_line")"
  config_file="$(detect_config_file "$exec_line")"
  collect_supporting_files
  collect_raw_logs "$binary_path" "$config_file"
  write_summary_kv "$binary_path" "$config_file"
  write_result '{"status":"audited","operation":"audit-snell","persistent_effects":[],"summary_kv":"logs/audit_summary.kv","raw_log":"logs/audit_raw.log"}'
}

case "$SNELL_AUDIT_OPERATION" in
audit-snell)
  run_audit
  ;;
*)
  die "unsupported read-only operation: ${SNELL_AUDIT_OPERATION}"
  ;;
esac
