---
name: brrr-now
description: "Send, test, or integrate brrr.now push notifications for explicit user pings, reminders, task-complete alerts, blockers, unattended-work notifications, and code paths that must deliver out-of-band notifications."
metadata:
  version: "1"
---

# brrr Push Notifications

Use brrr.now when chat is not enough: the user asks for a push, ping, reminder, or task-complete alert; project or harness instructions require a blocker or unattended job to notify outside chat; or the task builds, tests, or repairs a brrr notification path.

Keep ordinary progress updates, clarification questions, and unrequested failure reports in chat.

Check <https://brrr.now/docs/> or <https://brrr.now/learn/critical-alerts/> before changing API fields, auth behavior, or critical-alert semantics.

## Vocabulary

- Sender script: [`scripts/brrr-send.sh`](scripts/brrr-send.sh). It builds the JSON payload and sends it through the exe.dev proxy or public API.
- Wrapper: a project, host, or service script that adds local context and calls the sender script.
- Hook: the command, trap, systemd unit, worker callback, or monitor that observes the real completion, failure, or liveness event.
- Delivery configuration: endpoint plus credential source. `--dry-run` prints `auth_mode` to show which credential path the sender script would use.

## Rules

- Do not ask the user to paste a brrr secret into chat.
- Do not invent a secret or send an unauthenticated request to the public API.
- Keep secrets out of repos, scripts, unit files, shell history, and exe.dev VMs.
- Use the exe.dev proxy without an `Authorization` header on exe.dev.
- Use `BRRR_SECRET` as the public API bearer token outside exe.dev.
- Omit `interruption_level` for ordinary pings, reminders, and completion notices.
- Ask before the first proactive notification when the user did not request one.
- Ask before `time-sensitive` or `critical` unless the user clearly asked for urgent delivery.
- Test required delivery before relying on it for unattended work. Optional delivery may fail closed with a chat report.

## Workflow

1. Detect the runtime: exe.dev, macOS, or ordinary Linux.
2. Choose the delivery path and credential source.
3. Choose the hook: one-off command, repo script, systemd service, queue worker, or heartbeat.
4. Put the hook where the real event is visible. A launcher process does not prove that detached work succeeded.
5. Dry-run the sender command before delayed sends or unattended work.
6. Fix endpoint, credential, or payload failures before promising delivery.
7. Send concise notifications with `title`, `message`, stable `thread_id`, optional `open_url`, and the weakest interruption level that fits.

## Runtime

Detect the runtime:

```bash
[ -f /exe.dev/shelley.json ] && echo exe.dev || ([ "$(uname)" = Darwin ] && echo macOS || echo Linux)
```

Choose one delivery path:

- `exe.dev`: use `https://brrr.int.exe.xyz/v1/send`. Store no brrr secret on the VM and send no `Authorization` header. Required delivery needs the brrr HTTP Proxy integration attached to this VM, a covering tag, or all VMs.
- `macOS`: use the public API with a local `BRRR_SECRET` credential source.
- `Linux`: use the public API with a local `BRRR_SECRET` credential source unless the host is exe.dev. Remote or shared hosts should use a root or service env file with mode `600`.

The sender script reads `BRRR_SECRET` directly, or loads it from `BRRR_ENV_FILE`, `~/.config/brrr/env`, or `~/.config/notify/brrr.env` when readable.

## Sender Script

Call `scripts/brrr-send.sh` with flags. Do not pass positional JSON to the sender script.

Copy the sender script to the scope that owns the notification path, then call that copy through `/bin/bash` by absolute path:

```bash
tmpdir="$(mktemp -d)"
cp "<brrr-now skill dir>/scripts/brrr-send.sh" "$tmpdir/brrr-send.sh"
BRRR_SENDER="$tmpdir/brrr-send.sh"

/bin/bash "$BRRR_SENDER" \
  --title "提醒" \
  --message "一分钟到了。" \
  --thread-id "brrr-one-minute-reminder"
```

For delayed sends, dry-run the exact command before sleeping:

```bash
/bin/bash "$BRRR_SENDER" --dry-run \
  --title "提醒" \
  --message "一分钟到了。" \
  --thread-id "brrr-one-minute-reminder"

sleep 60
/bin/bash "$BRRR_SENDER" \
  --title "提醒" \
  --message "一分钟到了。" \
  --thread-id "brrr-one-minute-reminder"
```

`--dry-run` validates payload shape without sending. If it prints `auth_mode=unconfigured`, delivery configuration is missing.

Do not assume the skill directory exists on the target host:

- One-off work: copy the sender script to `$(mktemp -d)/brrr-send.sh` and run it through `/bin/bash`.
- Project behavior: copy or adapt the sender script into the repo, such as `scripts/brrr-send.sh` or `ops/notify/brrr-send.sh`.
- Host or systemd behavior: install a reviewed sender script at a stable absolute path such as `/usr/local/libexec/brrr-send` or `/opt/<app>/bin/brrr-send`.

## Integration patterns

Pick the smallest durable hook that observes the real event:

- One-off command: wrap the command and notify success or failure.
- Bash script: call the sender script or a wrapper, and use an `ERR` trap only when shell semantics are understood.
- systemd service: use `OnFailure=notify-brrr@%p.service` and include recent journal context.
- Long-running host: add a heartbeat timer so silence can be detected.
- Queue or background worker: hook the queue task result, not only the outer launcher process.

Read [`references/integration-patterns.md`](references/integration-patterns.md) for command, shell, secret-location, and heartbeat examples. Read [`references/systemd-pattern.md`](references/systemd-pattern.md) for Linux service units.

## Payloads

Use flags for the sender script. Use JSON only for raw public API calls.

Core fields:

- `title`: first line of the notification.
- `message`: main body text.
- `thread_id`: groups related notifications.
- `open_url`: opens when the user taps the notification.
- `sound`: optional alert sound. Use attention-grabbing sounds only for real alerts.
- `interruption_level`: `passive`, `active`, `time-sensitive`, or `critical`.
- `volume`: critical-alert volume from `0` to `1`.

Real sends include `title`, `message`, and a stable `thread_id` unless the target API cannot accept one of those fields.

## Interruption levels

Choose the weakest level that fits:

- Omit `interruption_level` for ordinary completion pings, reminders, and tests.
- Use `passive` for low-priority FYI updates.
- Use `active` when the user should notice soon.
- Use `time-sensitive` when the update should break through Focus and Notification Summary.
- Use `critical` only for urgent, alarm-style alerts where waking the user is intended.

Critical alerts are not enabled by default. The user must first enable critical alerts in the brrr app and allow the iOS permission prompt. After that, send `"interruption_level": "critical"` and optional `"volume": 0..1`.

Do not use `critical` for ordinary completion pings, routine status updates, or tests unless the user explicitly asks to test critical delivery.
