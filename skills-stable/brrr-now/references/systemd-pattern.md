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

Use `BRRR_SECRET` for public API sends. Avoid secret-bearing URLs.

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

`notify-brrr-unit` is a small systemd-specific wrapper around the general `/usr/local/libexec/brrr-send` sender. Keep the sender generic and put unit-name, journal, and host context in the wrapper.

Add this to any service that should notify on failure:

```ini
[Unit]
OnFailure=notify-brrr@%p.service

[Service]
StandardOutput=journal
StandardError=journal
```

Use `%p` so `notify-brrr@%p.service` receives the unit prefix without `.service`. For templated units or non-service units, verify the expanded unit name before relying on this template; adjust the wrapper if `%p` drops instance details you need.

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
systemctl enable --now heartbeat.timer
```

The alert is the missing heartbeat. brrr does not detect missing messages by itself; use a separate monitor if absence must trigger a page.
