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
service_result="${MONITOR_SERVICE_RESULT:-unknown}"
exit_code="${MONITOR_EXIT_CODE:-unknown}"
exit_status="${MONITOR_EXIT_STATUS:-unknown}"

message="The unit entered ${active_state:-unknown}/${sub_state:-unknown}; result=${service_result}, exit=${exit_code}/${exit_status}. Inspect its journal before restarting."

"$sender" \
    --title "${host}: ${unit} failed" \
    --subtitle "systemd unit" \
    --message "$message" \
    --thread-id "systemd-${host}-${unit}"
