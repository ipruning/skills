#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  brrr-send.sh --message TEXT [options]

Options:
  --title TEXT
  --subtitle TEXT
  --thread-id TEXT
  --open-url URL
  --image-url URL
  --sound NAME
  --expiration-date ISO8601
  --filter-criteria TEXT
  --interruption-level passive|active|time-sensitive|critical
  --volume 0..1
  --plain
  --dry-run

Environment:
  exe.dev: detected automatically; sends to https://brrr.int.exe.xyz/v1/send
  BRRR_SECRET: preferred public API auth secret for Authorization header
  BRRR_TIMEOUT: curl timeout in seconds, default 10
EOF
}

message=
title=
subtitle=
thread_id=
open_url=
image_url=
sound=
expiration_date=
filter_criteria=
interruption_level=
volume=
plain=0
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
        --subtitle)
            subtitle="${2:?missing value for --subtitle}"
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
        --image-url)
            image_url="${2:?missing value for --image-url}"
            shift 2
            ;;
        --sound)
            sound="${2:?missing value for --sound}"
            shift 2
            ;;
        --expiration-date)
            expiration_date="${2:?missing value for --expiration-date}"
            shift 2
            ;;
        --filter-criteria)
            filter_criteria="${2:?missing value for --filter-criteria}"
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
        --plain)
            plain=1
            shift
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

if [ -z "$message" ]; then
    echo "missing required --message" >&2
    usage >&2
    exit 2
fi

timeout="${BRRR_TIMEOUT:-10}"
endpoint=
auth_mode=

if [ -f /exe.dev/shelley.json ]; then
    endpoint="https://brrr.int.exe.xyz/v1/send"
    auth_mode="exe.dev-proxy"
elif [ -n "${BRRR_SECRET:-}" ]; then
    endpoint="https://api.brrr.now/v1/send"
    auth_mode="bearer"
else
    cat >&2 <<'EOF'
brrr is not configured.

Configure one of:
  - exe.dev brrr HTTP Proxy integration, if running on exe.dev
  - BRRR_SECRET, preferred for public API Authorization header

Do not paste secrets into chat or commit them to a repo.
EOF
    exit 3
fi

has_json_fields=0
for value in "$title" "$subtitle" "$thread_id" "$open_url" "$image_url" "$sound" \
        "$expiration_date" "$filter_criteria" "$interruption_level" "$volume"; do
    if [ -n "$value" ]; then
        has_json_fields=1
        break
    fi
done

curl_args=(-fsS --max-time "$timeout" -X POST)
if [ "$auth_mode" = "bearer" ]; then
    curl_args+=(-H "Authorization: Bearer $BRRR_SECRET")
fi

if [ "$plain" -eq 1 ] && [ "$has_json_fields" -eq 0 ]; then
    if [ "$dry_run" -eq 1 ]; then
        echo "auth_mode=$auth_mode"
        echo "payload=plain"
        exit 0
    fi
    curl "${curl_args[@]}" --data-binary "$message" "$endpoint" >/dev/null
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required for JSON payload construction; use --plain for a plain text test" >&2
    exit 4
fi

payload="$(
    python3 - "$message" "$title" "$subtitle" "$thread_id" "$open_url" "$image_url" "$sound" \
        "$expiration_date" "$filter_criteria" "$interruption_level" "$volume" <<'PY'
import json
import sys

names = [
    "message",
    "title",
    "subtitle",
    "thread_id",
    "open_url",
    "image_url",
    "sound",
    "expiration_date",
    "filter_criteria",
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
    "subtitle": values["subtitle"],
    "thread_id": values["thread_id"],
    "open_url": values["open_url"],
    "image_url": values["image_url"],
    "sound": values["sound"],
    "expiration_date": values["expiration_date"],
    "filter_criteria": values["filter_criteria"],
    "interruption_level": values["interruption_level"],
}

payload = {key: value for key, value in fields.items() if value}
volume = values["volume"]
if volume:
    try:
        payload["volume"] = float(volume)
    except ValueError:
        print("volume must be numeric", file=sys.stderr)
        sys.exit(2)

print(json.dumps(payload, separators=(",", ":")))
PY
)"

if [ "$dry_run" -eq 1 ]; then
    echo "auth_mode=$auth_mode"
    echo "payload=json"
    printf '%s\n' "$payload"
    exit 0
fi

curl "${curl_args[@]}" \
    -H 'Content-Type: application/json' \
    --data-binary "$payload" \
    "$endpoint" >/dev/null
