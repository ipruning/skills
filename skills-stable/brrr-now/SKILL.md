---
name: brrr-now
description: "Send brrr.now push notifications for pings, alerts, task-complete notices, and user-facing updates."
metadata:
  version: "1"
---

# brrr Push Notifications

Sources: <https://brrr.now/docs/> and <https://brrr.now/learn/critical-alerts/>

Use this skill when the user wants, implies, or would benefit from a push notification: task-complete pings, long-running job updates, failures, alerts, or requests for user input. The goal is not merely to send one `curl`; the goal is to pick the right notification hook and make delivery testable.

## Ground rules

- Do not ask the user to paste a brrr secret into chat.
- Do not invent a secret or send unauthenticated requests to the public API.
- If the user explicitly asks for brrr, a push, a ping, or "notify me", ordinary/default-level test and task notifications are allowed. Do not ask again for every normal ping.
- Ask before the first proactive notification only when the user did not explicitly request notifications. Also ask before noisy repeated notifications, `time-sensitive`, or `critical`.
- Use `BRRR_SECRET` with `Authorization: Bearer ...` for the public API. Avoid secret-bearing URLs.
- Do not put secrets in repos, scripts, unit files, shell history, or exe.dev VMs.
- Do not rely on `PATH` for helpers. Use a temp path for one-off work, a repo-local helper for project behavior, or an absolute host path for systemd.
- Use the weakest interruption level that fits. Reserve `critical` for alarm-style events where waking the user is intended.
- If setup is missing and notification is optional, say notifications are not configured and continue the main task. If notification is the deliverable or required for unattended work, guide setup before relying on it.

## Workflow

1. Detect the runtime: exe.dev, macOS, or ordinary Linux.
2. Choose auth: exe.dev proxy or public API with `BRRR_SECRET`.
3. Choose the integration pattern: one-off command, repo script, systemd/daemon, queue watcher, or heartbeat.
4. If notification setup is missing, decide whether notification is optional or required. Optional means report the missing setup and keep moving; required means guide the user through setup for the current environment.
5. For user-requested ordinary notifications, send a small default-level test or the first task notification. For proactive notifications, ask before the first test.
6. Fix endpoint/auth/payload issues before relying on notifications for unattended work.
7. Place the real hook at the failure or completion point that actually observes the event.
8. Send concise notifications with `title`, `message`, `thread_id`, optional `open_url`, and the appropriate `interruption_level`.

For planned unattended work where notification is part of the promise, test the path before the work begins. If notification is only a helpful extra and setup is missing, do not block the main task.

## Runtime

Detect the current runtime:

```bash
[ -f /exe.dev/shelley.json ] && echo exe.dev || ([ "$(uname)" = Darwin ] && echo macOS || echo Linux)
```

Choose the setup path:

- `exe.dev`: use `https://brrr.int.exe.xyz/v1/send`. Do not store a brrr secret in the VM and do not add an `Authorization` header. If the proxy is unavailable and notifications are required, ask the user to attach or enable the brrr HTTP Proxy integration for this VM, a covering tag, or all VMs. If notification is optional, report that the proxy is unavailable and continue.
- `macOS`: use the public API with a local secret. Have the user get a secret from the brrr app and store it outside chat, usually as a temporary `BRRR_SECRET`, a local secret manager value, or an untracked local env file.
- `Linux`: use the public API with a local secret unless this is exe.dev. For remote or shared hosts, prefer a root/service env file with mode `600` over shell profiles or shell history.

## Helper

Use [`scripts/brrr-send.sh`](scripts/brrr-send.sh) as the reference sender. It auto-selects the exe.dev proxy when available, otherwise uses `BRRR_SECRET` with the public `/v1/send` endpoint.

The helper accepts flags, not positional JSON. Do not pass a JSON object as an argument.

```bash
scripts/brrr-send.sh \
  --title "提醒" \
  --message "一分钟到了。" \
  --thread-id "codex-one-minute-reminder"
```

For delayed sends, dry-run the exact helper command before sleeping so argument mistakes fail immediately:

```bash
scripts/brrr-send.sh --dry-run \
  --title "提醒" \
  --message "一分钟到了。" \
  --thread-id "codex-one-minute-reminder"

sleep 60
scripts/brrr-send.sh \
  --title "提醒" \
  --message "一分钟到了。" \
  --thread-id "codex-one-minute-reminder"
```

`--dry-run` validates the payload shape even when auth is not configured. If it prints `auth_mode=unconfigured`, fix setup before relying on a real notification.

Do not assume the skill directory exists on the target host. Copy the helper to the right scope:

- One-off agent work: copy to `$(mktemp -d)/brrr-send.sh` and call it by absolute path.
- Project behavior: copy or adapt it into the repo, such as `scripts/brrr-send.sh` or `ops/notify/brrr-send.sh`.
- Host/systemd behavior: install a reviewed helper at a stable absolute path such as `/usr/local/libexec/brrr-send` or `/opt/<app>/bin/brrr-send`.

## Integration patterns

Pick the smallest durable hook that observes the real event:

- One-off command: wrap the command and notify success or failure.
- Bash script: source or call a helper, and use an `ERR` trap only when shell semantics are understood.
- systemd service: use `OnFailure=notify-brrr@%p.service` and include recent journal context.
- Long-running host: add a heartbeat timer so silence can be detected.
- Queue or background worker: hook the queue task result, not only the outer launcher process.

For concrete snippets and secret-location guidance, use [`references/integration-patterns.md`](references/integration-patterns.md). For a systemd template, use [`references/systemd-pattern.md`](references/systemd-pattern.md).

## Payloads

For the helper, use flags. For raw public API calls, use JSON.

Core fields:

- `title`: first line of the notification.
- `message`: main body text. Always include this for real notifications.
- `thread_id`: groups related notifications in Notification Center.
- `open_url`: opens when the user taps the notification.
- `sound`: optional alert sound. Use attention-grabbing sounds only for real alerts.
- `interruption_level`: `passive`, `active`, `time-sensitive`, or `critical`.
- `volume`: critical-alert volume from `0` to `1`.

Real notifications should usually include at least `title`, `message`, and a stable `thread_id`.

## Interruption levels

Choose the weakest level that fits:

- Omit `interruption_level` for ordinary completion pings.
- Use `passive` for low-priority FYI updates.
- Use `active` when the user should notice soon.
- Use `time-sensitive` when the update should break through Focus and Notification Summary.
- Use `critical` only for urgent, alarm-style alerts.

Critical alerts are not enabled by default. The user must first enable critical alerts in the brrr app and allow the iOS permission prompt. After that, send JSON with `"interruption_level": "critical"` and optional `"volume": 0..1`.

Ask before using `time-sensitive` or `critical` unless the user's request clearly asks for urgent delivery. Do not use critical alerts for ordinary completion pings, routine status updates, or tests unless the user explicitly asks to test critical delivery.
