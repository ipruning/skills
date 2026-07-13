#!/bin/bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  brrr-send.sh --title TEXT --message TEXT [options]

Options:
  --thread-id TEXT
  --open-url URL
  --sound NAME
  --interruption-level passive|active|time-sensitive|critical (omit for a normal ping)
  --volume 0..1          critical only
  --dry-run              print auth_mode and payload without sending; exit 3 if unconfigured

Environment:
  BRRR_SECRET: public API bearer token; takes precedence over runtime detection
  exe.dev: when no BRRR_SECRET is loaded, sends through the attached HTTP Proxy
  BRRR_ENV_FILE: optional shell env file to source before sending
  BRRR_TIMEOUT: curl timeout in seconds, default 10

Exit codes:
  2  usage or payload validation error
  3  no delivery configuration (secret or proxy)
  4  python3 not found
EOF
}

load_brrr_env() {
    if [ -n "${BRRR_SECRET:-}" ]; then
        return
    fi

    local candidates=()
    if [ -n "${BRRR_ENV_FILE:-}" ]; then
        candidates+=("$BRRR_ENV_FILE")
    fi
    if [ -n "${HOME:-}" ]; then
        candidates+=("$HOME/.config/brrr/env" "$HOME/.config/notify/brrr.env")
    fi

    local env_file
    for env_file in "${candidates[@]}"; do
        if [ -r "$env_file" ]; then
            # shellcheck disable=SC1090
            source "$env_file"
            return
        fi
    done
}

config_error() {
    cat >&2 <<'EOF'
brrr is not configured.

Configure one of:
  - exe.dev brrr HTTP Proxy integration, if running on exe.dev
  - BRRR_SECRET, the public API bearer token
  - BRRR_ENV_FILE, ~/.config/brrr/env, or ~/.config/notify/brrr.env with BRRR_SECRET='<secret>'

Do not paste secrets into chat or commit them to a repo.
EOF
}

find_python() {
    if [ -x /usr/bin/python3 ]; then
        printf '%s\n' /usr/bin/python3
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return
    fi

    echo "python3 is required for JSON payload construction" >&2
    exit 4
}

message=
title=
thread_id=
open_url=
sound=
interruption_level=
volume=
dry_run=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --message)
            message="${2:?missing value for --message}"
            shift 2
            ;;
        --title)
            title="${2:?missing value for --title}"
            shift 2
            ;;
        --thread-id)
            thread_id="${2:?missing value for --thread-id}"
            shift 2
            ;;
        --open-url)
            open_url="${2:?missing value for --open-url}"
            shift 2
            ;;
        --sound)
            sound="${2:?missing value for --sound}"
            shift 2
            ;;
        --interruption-level)
            interruption_level="${2:?missing value for --interruption-level}"
            shift 2
            ;;
        --volume)
            volume="${2:?missing value for --volume}"
            shift 2
            ;;
        --dry-run)
            dry_run=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ -z "$message" ] || [ -z "$title" ]; then
    echo "missing required --title or --message" >&2
    usage >&2
    exit 2
fi

load_brrr_env

timeout="${BRRR_TIMEOUT:-10}"
endpoint=
auth_mode=

# An explicit credential belongs to the invoking service and must win over a
# machine-level proxy attachment. The exe.dev marker is only a fallback.
if [ -n "${BRRR_SECRET:-}" ]; then
    endpoint="https://api.brrr.now/v1/send"
    auth_mode="bearer"
elif [ -f /exe.dev/shelley.json ]; then
    endpoint="https://brrr.int.exe.xyz/v1/send"
    auth_mode="exe.dev-proxy"
elif [ "$dry_run" -eq 1 ]; then
    auth_mode="unconfigured"
else
    config_error
    exit 3
fi

python_bin="$(find_python)"

payload="$(
    "$python_bin" - "$message" "$title" "$thread_id" "$open_url" "$sound" "$interruption_level" "$volume" <<'PY'
import json
import sys

names = [
    "message",
    "title",
    "thread_id",
    "open_url",
    "sound",
    "interruption_level",
    "volume",
]
if len(sys.argv) != len(names) + 1:
    print("internal argument mismatch", file=sys.stderr)
    sys.exit(2)
values = dict(zip(names, sys.argv[1:]))

fields = {
    "message": values["message"],
    "title": values["title"],
    "thread_id": values["thread_id"],
    "open_url": values["open_url"],
    "sound": values["sound"],
    "interruption_level": values["interruption_level"],
}

payload = {key: value for key, value in fields.items() if value}
interruption_level = values["interruption_level"]
if interruption_level and interruption_level not in {
    "passive",
    "active",
    "time-sensitive",
    "critical",
}:
    print("interruption_level must be passive, active, time-sensitive, or critical", file=sys.stderr)
    sys.exit(2)

volume = values["volume"]
if volume and interruption_level != "critical":
    print("volume only applies to --interruption-level critical", file=sys.stderr)
    sys.exit(2)
if volume:
    try:
        payload["volume"] = float(volume)
    except ValueError:
        print("volume must be numeric", file=sys.stderr)
        sys.exit(2)
    if payload["volume"] < 0 or payload["volume"] > 1:
        print("volume must be between 0 and 1", file=sys.stderr)
        sys.exit(2)

print(json.dumps(payload, separators=(",", ":")))
PY
)"

if [ "$dry_run" -eq 1 ]; then
    echo "auth_mode=$auth_mode"
    printf '%s\n' "$payload"
    if [ "$auth_mode" = "unconfigured" ]; then
        config_error
        exit 3
    fi
    exit 0
fi

# duplicate delivery beats missed delivery for notifications
curl_args=(-fsS --max-time "$timeout" --retry 2 -X POST)
if [ "$auth_mode" = "bearer" ]; then
    curl_args+=(-H "Authorization: Bearer $BRRR_SECRET")
fi

http_status="$(curl "${curl_args[@]}" \
    -H 'Content-Type: application/json' \
    --data-binary "$payload" \
    --output /dev/null \
    --write-out '%{http_code}' \
    "$endpoint")"

case "$http_status" in
    2??) ;;
    *)
        echo "brrr returned unexpected HTTP status: $http_status" >&2
        exit 1
        ;;
esac

printf 'auth_mode=%s\n' "$auth_mode"
printf 'http_status=%s\n' "$http_status"
