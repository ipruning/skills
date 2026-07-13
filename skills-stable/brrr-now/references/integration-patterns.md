# brrr Integration Patterns

Real-work notifications need a hook that observes completion, failure, liveness, or queue task outcome. One-off tests can call the sender script directly.

## Choose the hook

| Situation                                | Hook                                     | Sender script location                   |
| ---------------------------------------- | ---------------------------------------- | ---------------------------------------- |
| One command in the current agent session | Wrap the command and notify success/fail | Skill dir (copy first if absent on host) |
| Script in a repo                         | Call the sender script or a repo-local wrapper      | `scripts/` or `ops/notify/`              |
| systemd unit                             | `OnFailure=`; source shape changes the specifiers, see the systemd pattern | Stable absolute path                     |
| Cron replacement                         | systemd timer plus `OnFailure`           | Stable absolute path                     |
| Long-running daemon                      | systemd `Restart=` plus `OnFailure`      | Stable absolute path                     |
| Queue worker                             | Queue task result callback               | Repo or worker path                      |
| Host liveness                            | Heartbeat timer                          | Stable absolute path                     |

The hook must observe the real event. A launcher process succeeding does not prove that background jobs, queue tasks, or detached children succeeded.

## One-off commands

Call the sender script through `/bin/bash` by absolute path. One-off copies stay off `PATH`. Durable copies drop the `.sh` suffix and install executable, e.g. `install -m 755 brrr-send.sh /usr/local/libexec/brrr-send`.

```bash
BRRR_SENDER="<brrr-now skill dir>/scripts/brrr-send.sh"

if long_running_command; then
  /bin/bash "$BRRR_SENDER" \
    --title "payments/main: build passed" \
    --subtitle "GitHub Actions · production" \
    --message "All required checks passed. No action needed." \
    --thread-id "payments-main-build"
else
  rc=$?
  /bin/bash "$BRRR_SENDER" \
    --title "payments/main: build failed" \
    --subtitle "GitHub Actions · production" \
    --message "The build exited with status $rc and blocks release. Open the failed run to inspect it." \
    --thread-id "payments-main-build" \
    --open-url "https://example.invalid/builds/123" || true
  exit "$rc"
fi
```

Delayed one-off notifications dry-run the exact final command before waiting, so payload errors and missing configuration fail while someone can still fix them. A live secret is only proven by a real send.

## Bash scripts

An `ERR` trap fits scripts written for `bash` with `set -eE -o pipefail`:

```bash
#!/usr/bin/env bash
set -eEuo pipefail

notify_failure() {
  rc=$?
  line=${1:-?}
  host=$(hostname)
  trap - ERR
  /absolute/path/to/brrr-send \
    --title "$host: $(basename "$0") failed" \
    --subtitle "Scheduled script · production" \
    --message "The script exited with status $rc at line $line. Inspect its run log before retrying." \
    --thread-id "script-$host-$(basename "$0")" || true
  exit "$rc"
}

trap 'notify_failure "$LINENO"' ERR
```

## Content and recurrence

A notification is the interrupting summary, not the diagnostic record. Use the smallest actionable identity in the title. Put role, environment, provider, and an operationally useful IP in the subtitle. Put raw metrics, logs, producer lists, and internal field names behind `--open-url`.

Do not turn every poll into a push. Keep recurrence state at the producer and notify transitions or thresholds:

- First anomaly while the service remains healthy: record it, or send one `passive` notification when the user asked to see it.
- Repeated samples below the escalation threshold: increment the count without sending.
- Frequency, duration, or impact crosses its threshold: send one aggregate notification with the window, count, current impact, and action.
- Recovery: notify only if the onset or escalation was sent.

For example:

```bash
/absolute/path/to/brrr-send \
  --title "ci-host-01: kernel warnings recurring; runtime healthy" \
  --subtitle "GitHub Actions host · production · last 50 minutes" \
  --message "Seven overlay warnings were observed; jobs remain healthy. No action is needed now. Open the diagnostic report for details." \
  --thread-id "ci-host-01-kernel" \
  --open-url "https://example.invalid/hosts/ci-host-01/diagnostics"
```

The sender does not count, suppress, acknowledge, resolve, or replace notifications. `thread_id` only asks the operating system to group related notifications.

Bash may skip an `ERR` trap for a direct `exit N`. If that exit should notify, call the sender script before exiting.

## Credential sources

Use the narrowest credential source that matches the runtime:

| Runtime                     | Credential source                                                                                     |
| --------------------------- | ----------------------------------------------------------------------------------------------------- |
| exe.dev VM with explicit service secret | Load the authorized `BRRR_SECRET`; explicit bearer auth wins over runtime proxy detection.            |
| exe.dev VM without a service secret      | Use the HTTP Proxy integration attached to that exact runtime.                                        |
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
  --title "$(hostname): daily heartbeat received" \
  --subtitle "Linux host" \
  --message "The host reported on schedule. No action needed." \
  --thread-id "heartbeat-$(hostname)" \
  --interruption-level passive
```

The missing heartbeat is the alert. Keep heartbeat messages quiet. brrr only delivers messages it receives; detecting absence needs a standing monitor, and that deployment belongs to the `end-to-end-monitoring` skill.
