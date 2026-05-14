# brrr Integration Patterns

Use this reference when the user wants notifications to be part of real work, not just a one-off test.

## Choose the hook

| Situation                                | Recommended hook                                          | Helper location             |
| ---------------------------------------- | --------------------------------------------------------- | --------------------------- |
| One command in the current agent session | Wrap the command and notify success/failure               | `$(mktemp -d)/brrr-send.sh` |
| Script in a repo                         | Call a repo-local helper or source a small notify library | `scripts/` or `ops/notify/` |
| systemd service                          | `OnFailure=notify-brrr@%p.service`                        | Stable absolute path        |
| Cron replacement                         | Prefer systemd timer plus `OnFailure`                     | Stable absolute path        |
| Long-running daemon                      | systemd `Restart=` plus `OnFailure`                       | Stable absolute path        |
| Queue worker                             | Hook task result inside the queue/watcher                 | Repo or worker helper       |
| Host liveness                            | Heartbeat timer                                           | Stable absolute path        |

The hook must observe the real event. A launcher process succeeding does not prove that background jobs, queue tasks, or detached children succeeded.

## One-off commands

For temporary agent work, copy `scripts/brrr-send.sh` to a temp directory and call it by absolute path:

```bash
tmpdir="$(mktemp -d)"
cp /path/to/skill/scripts/brrr-send.sh "$tmpdir/brrr-send.sh"
chmod +x "$tmpdir/brrr-send.sh"

if long_running_command; then
  "$tmpdir/brrr-send.sh" --title "Task complete" --message "long_running_command finished" --thread-id "agent-task"
else
  rc=$?
  "$tmpdir/brrr-send.sh" --title "Task failed" --message "long_running_command failed with rc=$rc" --thread-id "agent-task" --interruption-level active || true
  exit "$rc"
fi
```

Do not leave one-off helpers on `PATH`.

For delayed one-off notifications, dry-run the final command before sleeping:

```bash
"$tmpdir/brrr-send.sh" --dry-run \
  --title "Reminder" \
  --message "One minute passed." \
  --thread-id "agent-reminder"

sleep 60
"$tmpdir/brrr-send.sh" \
  --title "Reminder" \
  --message "One minute passed." \
  --thread-id "agent-reminder"
```

The helper accepts flags, not positional JSON.

`--dry-run` validates the payload shape even when auth is not configured. If it prints `auth_mode=unconfigured`, fix setup before relying on a real notification.

## Bash scripts

Use an `ERR` trap when the script is written for `bash` and uses `set -eE -o pipefail`:

```bash
#!/usr/bin/env bash
set -eEuo pipefail

notify_failure() {
  rc=$?
  line=${1:-?}
  trap - ERR
  /absolute/path/to/brrr-send \
    --title "Script failed" \
    --message "$(basename "$0") failed rc=$rc line=$line on $(hostname)" \
    --thread-id "script-$(basename "$0")" \
    --interruption-level active || true
  exit "$rc"
}

trap 'notify_failure "$LINENO"' ERR
```

Important: in bash, a direct `exit N` may bypass the `ERR` trap. If a failure should notify through the trap, let a command fail under `set -e`, or call the notifier explicitly before exiting.

## Secret locations

Use the narrowest secret scope that matches the runtime:

| Runtime                     | Recommended storage                                                                      |
| --------------------------- | ---------------------------------------------------------------------------------------- |
| exe.dev VM                  | No brrr secret. Use the HTTP Proxy integration.                                          |
| Current interactive shell   | `read -rsp "brrr secret: " BRRR_SECRET; export BRRR_SECRET`                              |
| Project local dev           | Untracked local env such as `.env.local`, `.mise/config.local.toml`, or a secret manager |
| Root-owned host service     | `/root/.config/notify/brrr.env`, mode `600`                                              |
| Service-specific Linux unit | `/etc/<app>/notify.env`, root-owned, mode `600`                                          |
| User systemd unit           | `%h/.config/notify/brrr.env`, mode `600`                                                 |

For files consumed by both systemd `EnvironmentFile=` and bash `source`, single-quote values:

```bash
BRRR_SECRET='br_usr_a1b2c3d4e5f6g7h8i9j0'
```

Single quotes keep the file safe for both bash and systemd parsing. Do not store secrets in `.bashrc` by default; shell profiles are not loaded by cron or systemd and are too broad for service secrets.

## Heartbeats

Failure notifications do not cover host outages, scheduler failure, broken networking, or expired credentials. For important hosts, add a low-noise heartbeat:

```bash
/absolute/path/to/brrr-send \
  --title "heartbeat" \
  --message "host=$(hostname) time=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --thread-id "heartbeat-$(hostname)" \
  --interruption-level passive
```

The alert is the missing heartbeat, not the heartbeat itself. Keep heartbeat messages quiet. If missed heartbeats must page someone, use a separate monitor to detect absence; brrr only delivers the heartbeat messages it receives.
