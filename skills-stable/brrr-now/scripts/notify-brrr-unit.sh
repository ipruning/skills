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
host="$(hostname)"
when="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
state="$(systemctl show "$unit" --property=LoadState,ActiveState,SubState,UnitFileState --no-pager 2>/dev/null || true)"

message="[${host}] systemd FAILED
unit: ${unit}
time: ${when}
service_result: ${MONITOR_SERVICE_RESULT:-n/a}
exit_code: ${MONITOR_EXIT_CODE:-n/a}
exit_status: ${MONITOR_EXIT_STATUS:-n/a}
${state}"

"$sender" \
    --title "systemd failed: ${unit}" \
    --message "$message" \
    --thread-id "systemd-${unit}"
