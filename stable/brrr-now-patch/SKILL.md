---
name: brrr-now-patch
description: "Send push notifications via brrr on exe.dev VMs (proxy auth, no bearer token)."
allowed-tools: Bash(curl:*)
metadata:
  version: "1"
---

# brrr Push Notification on exe.dev

The exe.dev HTTP Proxy exposes brrr at `brrr.int.exe.xyz` and injects authentication automatically — no bearer token required.

## Environment Check

```bash
[ -f /exe.dev/shelley.json ] && echo exe.dev || ([ "$(uname)" = Darwin ] && echo macOS || echo Linux)
```

Only proceed with this skill if the output is `exe.dev`.

## Plain text

```bash
curl -X POST https://brrr.int.exe.xyz/v1/send \
  -d 'Hello from exe.dev! 🚀'
```

## JSON

```bash
curl -X POST https://brrr.int.exe.xyz/v1/send \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "exe.dev",
    "message": "Hello from exe.dev! 🚀"
  }'
```

No `Authorization` header needed — the proxy handles it.

## Linking back to the conversation

On exe.dev you can resolve the current Shelley conversation URL and pass it as `open_url`, so the user taps the notification and lands straight back in the conversation:

```bash
CONVERSATION_URL=$(shelley client list 2>/dev/null | jq -r --arg id "$SHELLEY_CONVERSATION_ID" 'select(.conversation_id==$id) | "https://'"$(hostname)"'.shelley.exe.xyz/c/\(.slug)"')

curl -X POST https://brrr.int.exe.xyz/v1/send \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg url "$CONVERSATION_URL" '{
    "title": "Task Complete",
    "message": "Your task has finished.",
    "open_url": $url
  }')"
```

If `SHELLEY_CONVERSATION_ID` is unset or the command fails, omit `open_url` and send the notification without it.

## When to notify

Send a notification when a long-running task completes, fails, or needs user input. Always include a meaningful `message` describing what happened.

See the `brrr-now` skill for full field reference and usage details.
