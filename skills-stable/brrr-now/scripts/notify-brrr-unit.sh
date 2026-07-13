#!/bin/bash
set -euo pipefail

sender="${BRRR_SENDER:-/usr/local/libexec/brrr-send}"
unit="${MONITOR_UNIT:-}"
if [ -z "$unit" ]; then
    unit="${1:-}"
    case "$unit" in
        *.service|*.socket|*.device|*.mount|*.automount|*.swap|*.target|*.path|*.timer|*.slice|*.scope) ;;
        *)
            echo "expected a complete systemd unit name when MONITOR_UNIT is unavailable" >&2
            exit 2
            ;;
    esac
fi
host="$(hostname -f 2>/dev/null || hostname)"
active_state="$(systemctl show "$unit" --property=ActiveState --value 2>/dev/null || printf unknown)"
sub_state="$(systemctl show "$unit" --property=SubState --value 2>/dev/null || printf unknown)"

message="The unit entered ${active_state:-unknown}/${sub_state:-unknown}."
if [ -n "${MONITOR_SERVICE_RESULT:-}" ]; then
    message+=" Service result is ${MONITOR_SERVICE_RESULT}."
fi
if [ -n "${MONITOR_EXIT_CODE:-}" ] || [ -n "${MONITOR_EXIT_STATUS:-}" ]; then
    message+=" Process exit is ${MONITOR_EXIT_CODE:-unknown}/${MONITOR_EXIT_STATUS:-unknown}."
fi
message+=" Inspect the unit status and journal to diagnose the failure."

"$sender" \
    --title "${host}: ${unit} failed" \
    --subtitle "systemd unit" \
    --message "$message" \
    --thread-id "systemd-${host}-${unit}"
