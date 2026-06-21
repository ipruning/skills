# brrr Integration Patterns

Real-work notifications need a hook that observes completion, failure, liveness, or queue task outcome. One-off tests can call the sender script directly.

## Choose the hook

| Situation                                | Hook                                      | Sender script location      |
| ---------------------------------------- | ----------------------------------------- | --------------------------- |
| One command in the current agent session | Wrap the command and notify success/fail  | `$(mktemp -d)/brrr-send.sh` |
| Script in a repo                         | Call the sender script or a wrapper       | `scripts/` or `ops/notify/` |
| systemd service                          | `OnFailure=notify-brrr@%p.service`        | Stable absolute path        |
| Cron replacement                         | systemd timer plus `OnFailure`            | Stable absolute path        |
| Long-running daemon                      | systemd `Restart=` plus `OnFailure`       | Stable absolute path        |
| Queue worker                             | Queue task result callback                | Repo or worker path         |
| Host liveness                            | Heartbeat timer                           | Stable absolute path        |

The hook must observe the real event. A launcher process succeeding does not prove that background jobs, queue tasks, or detached children succeeded.

## One-off commands

Temporary work copies `scripts/brrr-send.sh` to a temp directory and calls that copy through `/bin/bash` by absolute path:

```bash
tmpdir="$(mktemp -d)"
BRRR_SKILL_DIR="<directory containing the brrr-now SKILL.md>"
cp "$BRRR_SKILL_DIR/scripts/brrr-send.sh" "$tmpdir/brrr-send.sh"

if long_running_command; then
  /bin/bash "$tmpdir/brrr-send.sh" --title "Task complete" --message "long_running_command finished" --thread-id "agent-task"
else
  rc=$?
  /bin/bash "$tmpdir/brrr-send.sh" --title "Task failed" --message "long_running_command failed with rc=$rc" --thread-id "agent-task" --interruption-level active || true
  exit "$rc"
fi
```

One-off sender scripts stay off `PATH`.

Delayed one-off notifications dry-run the final command before sleeping:

```bash
/bin/bash "$tmpdir/brrr-send.sh" --dry-run \
  --title "Reminder" \
  --message "One minute passed." \
  --thread-id "agent-reminder"

sleep 60
/bin/bash "$tmpdir/brrr-send.sh" \
  --title "Reminder" \
  --message "One minute passed." \
  --thread-id "agent-reminder"
```

The sender script accepts flags, not positional JSON.

`--dry-run` validates the payload shape without sending. If it prints `auth_mode=unconfigured`, delivery configuration is missing.

## Bash scripts

An `ERR` trap fits scripts written for `bash` with `set -eE -o pipefail`:

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

Bash may skip an `ERR` trap for a direct `exit N`. If that exit should notify, call the sender script before exiting.

## Credential sources

Use the narrowest credential source that matches the runtime:

| Runtime                     | Credential source                                                                                     |
| --------------------------- | ----------------------------------------------------------------------------------------------------- |
| exe.dev VM                  | No brrr secret. Use the HTTP Proxy integration.                                                       |
| Current interactive shell   | Export `BRRR_SECRET` in the shell that runs the sender script.                                        |
| macOS local user            | `~/.config/brrr/env` or `~/.config/notify/brrr.env`, readable only by the user.                       |
| Project local dev           | Set `BRRR_ENV_FILE` to an untracked env file or load `BRRR_SECRET` from a local secret manager.       |
| Root-owned Linux service    | `/root/.config/notify/brrr.env`, mode `600`, or a systemd `EnvironmentFile=` that exports the secret. |
| Service-specific Linux unit | `/etc/<app>/notify.env`, root-owned, mode `600`, loaded through `EnvironmentFile=`.                   |
| User systemd unit           | `%h/.config/notify/brrr.env`, mode `600`, loaded through `EnvironmentFile=`.                          |

Files consumed by both systemd `EnvironmentFile=` and bash `source` use single-quoted values:

```bash
BRRR_SECRET='<brrr-secret>'
```

Single quotes keep the file safe for both bash and systemd parsing. Do not store service secrets in `.bashrc`; cron and systemd do not load shell profiles by default, and shell profiles are too broad for service secrets.

## Heartbeats

Failure notifications do not cover host outages, scheduler failure, broken networking, or expired credentials. For important hosts, add a low-noise heartbeat:

```bash
/absolute/path/to/brrr-send \
  --title "heartbeat" \
  --message "host=$(hostname) time=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --thread-id "heartbeat-$(hostname)" \
  --interruption-level passive
```

The missing heartbeat is the alert. Keep heartbeat messages quiet. Use a separate monitor if absence must trigger a page; brrr only delivers messages it receives.
