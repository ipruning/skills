# brrr systemd Pattern

Use this reference for long-running Linux hosts, daemons, and cron replacements. Prefer explicit absolute paths. Do not rely on a user shell `PATH`.

## Environment file

Create a root-owned file outside the repo:

```bash
install -d -m 700 /root/.config/notify
install -m 600 /dev/null /root/.config/notify/brrr.env
```

Example content:

```bash
BRRR_SECRET='br_usr_a1b2c3d4e5f6g7h8i9j0'
```

Use `BRRR_SECRET` for integrations. Avoid secret-bearing URLs.

## Failure notifier service

Template unit:

```ini
[Unit]
Description=Notify brrr about failure of %i.service

[Service]
Type=oneshot
EnvironmentFile=/root/.config/notify/brrr.env
ExecStart=/usr/local/libexec/notify-brrr-unit "%i"
```

Helper:

```bash
#!/usr/bin/env bash
set -uo pipefail

unit_short="${1:-unknown}"
unit="${unit_short}.service"
host="$(hostname)"
when="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
state="$(systemctl show "$unit" --property=ActiveState,Result,ExecMainStatus --value 2>/dev/null | tr '\n' ' ')"
context="$(journalctl -u "$unit" -n 15 --no-pager --output=cat 2>/dev/null | tail -15 || true)"

message="[${host}] systemd FAILED
unit:  ${unit}
state: ${state}
time:  ${when}
last logs:
${context}"

/usr/local/libexec/brrr-send \
  --title "systemd failed: ${unit}" \
  --message "$message" \
  --thread-id "systemd-${unit_short}" \
  --interruption-level active
```

Business unit:

```ini
[Unit]
Description=Example job
After=network-online.target
Wants=network-online.target
OnFailure=notify-brrr@%p.service

[Service]
Type=oneshot
WorkingDirectory=/opt/example
ExecStart=/opt/example/bin/run-job
StandardOutput=journal
StandardError=journal
```

Use `%p` so `notify-brrr@%p.service` receives the unit prefix without `.service`.

## Timer

For cron-like scheduling:

```ini
[Unit]
Description=Example job trigger

[Timer]
OnCalendar=hourly
Persistent=false

[Install]
WantedBy=timers.target
```

Decide `Persistent=` deliberately. `true` replays missed runs after downtime; `false` avoids a backlog.

## Heartbeat

Heartbeat service:

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

Heartbeat timer:

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
systemctl enable --now example.timer heartbeat.timer
```

## Checks

```bash
systemctl list-timers --all
systemctl status example.service
journalctl -u example.service -n 50 --no-pager
systemctl start example.service
```

Before enabling a timer that replaces cron, disable the old cron entry to avoid double runs.
