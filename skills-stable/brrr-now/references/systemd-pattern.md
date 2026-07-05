# brrr systemd Pattern

Long-running Linux hosts, daemons, and cron replacements need explicit absolute paths and systemd-owned environment files. A user shell `PATH` is not part of the service contract.

## Environment file

A root-owned environment file lives outside the repo:

```bash
install -d -m 700 /root/.config/notify
install -m 600 /dev/null /root/.config/notify/brrr.env
```

Example content:

```bash
BRRR_SECRET='<brrr-secret>'
```

`EnvironmentFile=` exports `BRRR_SECRET` for the sender script. Secret-bearing URLs stay out of unit files.

## Failure wrapper service

Template unit:

```ini
[Unit]
Description=Notify brrr about failure of %i.service

[Service]
Type=oneshot
EnvironmentFile=/root/.config/notify/brrr.env
ExecStart=/usr/local/libexec/notify-brrr-unit "%i"
```

Wrapper script:

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

`notify-brrr-unit` is the systemd wrapper. `/usr/local/libexec/brrr-send` is the sender script. Keep unit name, journal, and host context in the wrapper.

Services that should notify on failure include this unit dependency:

```ini
[Unit]
OnFailure=notify-brrr@%p.service

[Service]
StandardOutput=journal
StandardError=journal
```

`%p` gives `notify-brrr@%p.service` the unit prefix without `.service`. Check templated units and non-service units before relying on this template; adjust the wrapper when `%p` drops required instance details.

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

Heartbeat semantics live in [integration-patterns.md](integration-patterns.md); `Persistent=false` is deliberate — a missed beat must stay missed, because silence is the alert.
