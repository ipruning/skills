# brrr systemd Pattern

Long-running Linux hosts, daemons, and cron replacements need explicit absolute paths and systemd-owned environment files. A user shell `PATH` is not part of the service contract. Install the sender and systemd wrapper once at stable paths; the units below assume them:

```bash
install -d -m 755 /usr/local/libexec
install -m 755 "<brrr-now skill dir>/scripts/brrr-send.sh" /usr/local/libexec/brrr-send
install -m 755 "<brrr-now skill dir>/scripts/notify-brrr-unit.sh" /usr/local/libexec/notify-brrr-unit
```

## Environment file

A root-owned environment file lives outside the repo:

```bash
install -d -m 700 /root/.config/notify
if [ -L /root/.config/notify/brrr.env ]; then
  echo "refusing symlinked brrr env file" >&2
  exit 1
fi
if [ ! -e /root/.config/notify/brrr.env ]; then
  install -m 600 /dev/null /root/.config/notify/brrr.env
fi
chown root:root /root/.config/notify/brrr.env
chmod 600 /root/.config/notify/brrr.env
```

Example content:

```bash
BRRR_SECRET='<brrr-secret>'
```

`EnvironmentFile=` exports `BRRR_SECRET` for the sender script. Secret-bearing URLs stay out of unit files.

## Failure wrapper service

Template unit, saved as `/etc/systemd/system/notify-brrr@.service`:

```ini
[Unit]
Description=Notify brrr about unit failure (%i)

[Service]
Type=oneshot
EnvironmentFile=/root/.config/notify/brrr.env
ExecStart=/usr/local/libexec/notify-brrr-unit "%i"
```

Install [`scripts/notify-brrr-unit.sh`](../scripts/notify-brrr-unit.sh) as `/usr/local/libexec/notify-brrr-unit`. It keeps the unit identity, named service-result fields, and host context in one tested wrapper. `/usr/local/libexec/brrr-send` remains the transport-only sender.

The handler has its own execution environment. It does not inherit `EnvironmentFile=` from the failed service, so load the authorized brrr env file in `notify-brrr@.service` itself.

For a non-templated service or non-templated unit such as `backup.timer`, use the complete unit name:

```ini
[Unit]
OnFailure=notify-brrr@%n.service
```

For a source service, keep its own output in the journal when that is part of the local runbook. Do not add a `[Service]` section to timer or other non-service units.

For a templated service such as `worker@blue.service`, systemd's documented handler shape is different:

```ini
[Unit]
OnFailure=notify-brrr@%p-%i.service
```

On systemd 251 and later, a handler triggered by a service receives the exact source unit in `MONITOR_UNIT`; the wrapper prefers it over `%i`. Check `systemctl --version` before relying on this. On older systemd, use a service-specific handler that reconstructs and passes the exact unit name, then test it with `systemd-analyze verify`; the wrapper rejects the lossy `%p-%i` value when `MONITOR_UNIT` is absent.

`MONITOR_UNIT` applies only when a service triggers the handler. For a non-templated non-service unit, `%n` remains the exact fallback argument. For a templated timer or other templated non-service unit, use a unit-specific handler that can reconstruct `<prefix>@%i.<type>` unambiguously.

Test a templated service through a controlled source failure, which lets systemd inject `MONITOR_UNIT`. Directly starting `notify-brrr@worker-blue.service` does not reproduce that runtime and is rejected instead of producing a false-positive notification.

`OnFailure=` on `backup.timer` reports failure of the timer unit itself. It does not report failure of the `backup.service` activated by that timer; put the task-failure hook on the service, and add a timer hook only when scheduler-unit failure is also part of the contract.

The default wrapper sends named state and service-result fields, not journal excerpts. Logs can contain tokens, payloads, or user data; include only an explicitly authorized and filtered excerpt when the notification contract requires it.

The source of truth for the two service handler forms and `MONITOR_UNIT` is the [systemd execution-environment documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#%24MONITOR_SERVICE_RESULT%2C%20%24MONITOR_EXIT_CODE%2C%20%24MONITOR_EXIT_STATUS%2C%20%24MONITOR_INVOCATION_ID%2C%20%24MONITOR_UNIT).

## Heartbeat

Heartbeat service, saved as `/etc/systemd/system/heartbeat.service`:

```ini
[Unit]
Description=Daily brrr heartbeat
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/root/.config/notify/brrr.env
ExecStart=/usr/local/libexec/brrr-send --title "heartbeat" --message "host=%H daily heartbeat" --thread-id "heartbeat-%H" --interruption-level passive
```

Heartbeat timer, saved as `/etc/systemd/system/heartbeat.timer`:

```ini
[Unit]
Description=Daily brrr heartbeat trigger

[Timer]
OnCalendar=*-*-* 12:00:00 UTC
Persistent=false

[Install]
WantedBy=timers.target
```

Enable with:

```bash
systemctl daemon-reload
systemctl enable --now heartbeat.timer
```

Heartbeat semantics live in [integration-patterns.md](integration-patterns.md); `Persistent=false` is deliberate — a missed beat must stay missed, because silence is the alert.
