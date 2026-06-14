---
name: brrr-now
description: "Send brrr.now push notifications when the user requests a ping, a workflow requires out-of-band delivery, or you are building notification hooks."
metadata:
  version: "1"
---

# brrr Push Notifications

brrr.now handles out-of-band push notifications for three situations: the user explicitly asks for a brrr.now push, ping, notification, reminder, or task-complete alert; project or harness instructions require a blocker or unattended job to notify outside chat; or the task implements, tests, or repairs a brrr notification integration.

Ordinary chat updates, routine progress reports, normal clarification questions, and unrequested failure reports stay in chat. A notification hook must observe the real event and must make delivery testable.

The agent checks <https://brrr.now/docs/> or <https://brrr.now/learn/critical-alerts/> before changing API fields, auth behavior, or critical-alert semantics.

## Ground rules

- The agent does not ask the user to paste a brrr secret into chat.
- The agent does not invent a secret or send unauthenticated requests to the public API.
- A user-requested brrr push, ping, or "notify me" allows an ordinary/default-level test or task notification. Normal pings do not need repeated confirmation.
- A proactive notification needs user approval before the first send when the user did not explicitly request notifications. Noisy repeated notifications, `time-sensitive`, and `critical` also need approval.
- The public API uses `BRRR_SECRET` with `Authorization: Bearer ...`. Secret-bearing URLs stay out of commands and docs.
- Secrets stay out of repos, scripts, unit files, shell history, and exe.dev VMs.
- Helper paths stay explicit. One-off work uses a temp path, project behavior uses a repo-local helper, and systemd uses a stable absolute host path.
- Notification delivery uses the weakest interruption level that fits. `critical` belongs to alarm-style events where waking the user is intended.
- Missing delivery configuration does not block optional notifications. Required delivery must be configured before the work relies on it.

## Workflow

1. The agent detects the runtime: exe.dev, macOS, or ordinary Linux.
2. The agent chooses auth: exe.dev proxy or public API with `BRRR_SECRET`.
3. The agent chooses the integration pattern: one-off command, repo script, systemd/daemon, queue watcher, or heartbeat.
4. If delivery configuration is missing, the agent resolves delivery configuration only when delivery is required for the task.
5. For user-requested ordinary notifications, the agent sends a small default-level test or the first task notification. For proactive notifications, the agent asks before the first test.
6. The agent fixes endpoint/auth/payload issues before relying on notifications for unattended work.
7. The agent places the real hook at the failure or completion point that actually observes the event.
8. The agent sends concise notifications with `title`, `message`, `thread_id`, optional `open_url`, and the appropriate `interruption_level`.

For planned unattended work where notification is part of the promise, the agent tests the path before the work begins.

## Runtime

The agent detects the current runtime:

```bash
[ -f /exe.dev/shelley.json ] && echo exe.dev || ([ "$(uname)" = Darwin ] && echo macOS || echo Linux)
```

The agent chooses the delivery path:

- `exe.dev`: use `https://brrr.int.exe.xyz/v1/send`. The VM stores no brrr secret and sends no `Authorization` header. Required delivery needs the brrr HTTP Proxy integration attached to this VM, a covering tag, or all VMs. Optional delivery can fail closed with a chat report.
- `macOS`: use the public API with a local secret. The user gets a secret from the brrr app and stores it outside chat, usually as a temporary `BRRR_SECRET`, a local secret manager value, or an untracked local env file.
- `Linux`: use the public API with a local secret unless the host is exe.dev. Remote or shared hosts use a root/service env file with mode `600` instead of shell profiles or shell history.

## Helper

[`scripts/brrr-send.sh`](scripts/brrr-send.sh) is the reference sender. It auto-selects the exe.dev proxy when available, otherwise it uses `BRRR_SECRET` with the public `/v1/send` endpoint.

The helper accepts flags, not positional JSON. The agent does not pass a JSON object as an argument.

The agent copies or adapts the helper to the target scope, then calls that copy by absolute path:

```bash
tmpdir="$(mktemp -d)"
cp "<brrr-now skill dir>/scripts/brrr-send.sh" "$tmpdir/brrr-send.sh"
chmod +x "$tmpdir/brrr-send.sh"
BRRR_HELPER="$tmpdir/brrr-send.sh"

"$BRRR_HELPER" \
  --title "提醒" \
  --message "一分钟到了。" \
  --thread-id "brrr-one-minute-reminder"
```

For delayed sends, the agent dry-runs the exact helper command before sleeping so common argument and payload mistakes fail immediately:

```bash
"$BRRR_HELPER" --dry-run \
  --title "提醒" \
  --message "一分钟到了。" \
  --thread-id "brrr-one-minute-reminder"

sleep 60
"$BRRR_HELPER" \
  --title "提醒" \
  --message "一分钟到了。" \
  --thread-id "brrr-one-minute-reminder"
```

`--dry-run` validates the payload shape even when auth is not configured. If `--dry-run` prints `auth_mode=unconfigured`, the agent fixes delivery configuration before relying on a real notification.

The agent does not assume the skill directory exists on the target host. The agent copies the helper to the right scope:

- One-off agent work: copy to `$(mktemp -d)/brrr-send.sh` and call it by absolute path.
- Project behavior: copy or adapt it into the repo, such as `scripts/brrr-send.sh` or `ops/notify/brrr-send.sh`.
- Host/systemd behavior: install a reviewed helper at a stable absolute path such as `/usr/local/libexec/brrr-send` or `/opt/<app>/bin/brrr-send`.

## Integration patterns

The agent picks the smallest durable hook that observes the real event:

- One-off command: wrap the command and notify success or failure.
- Bash script: source or call a helper, and use an `ERR` trap only when shell semantics are understood.
- systemd service: use `OnFailure=notify-brrr@%p.service` and include recent journal context.
- Long-running host: add a heartbeat timer so silence can be detected.
- Queue or background worker: hook the queue task result, not only the outer launcher process.

Concrete snippets and secret-location guidance live in [`references/integration-patterns.md`](references/integration-patterns.md). The systemd template lives in [`references/systemd-pattern.md`](references/systemd-pattern.md).

## Payloads

For the helper, the agent uses flags. For raw public API calls, the agent uses JSON.

Core fields:

- `title`: first line of the notification.
- `message`: main body text. Real notifications include this field.
- `thread_id`: groups related notifications in Notification Center.
- `open_url`: opens when the user taps the notification.
- `sound`: optional alert sound. The agent uses attention-grabbing sounds only for real alerts.
- `interruption_level`: `passive`, `active`, `time-sensitive`, or `critical`.
- `volume`: critical-alert volume from `0` to `1`.

Real notifications should usually include at least `title`, `message`, and a stable `thread_id`.

## Interruption levels

The agent chooses the weakest level that fits:

- The agent omits `interruption_level` for ordinary completion pings.
- The agent uses `passive` for low-priority FYI updates.
- The agent uses `active` when the user should notice soon.
- The agent uses `time-sensitive` when the update should break through Focus and Notification Summary.
- The agent uses `critical` only for urgent, alarm-style alerts.

Critical alerts are not enabled by default. The user must first enable critical alerts in the brrr app and allow the iOS permission prompt. After that, the agent sends JSON with `"interruption_level": "critical"` and optional `"volume": 0..1`.

The agent asks before using `time-sensitive` or `critical` unless the user's request clearly asks for urgent delivery. The agent does not use critical alerts for ordinary completion pings, routine status updates, or tests unless the user explicitly asks to test critical delivery.
