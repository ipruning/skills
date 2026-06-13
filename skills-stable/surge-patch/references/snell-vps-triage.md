# Snell VPS Triage

Surge + Snell incidents start with classification. The failure may sit in
local Surge routing, the Snell listener, systemd, firewall rules, provider
networking, or the VPS outbound path.

## Local Classification

Collect a Surge baseline before mutating runtime or profile state:

```bash
surge-cli --raw environment
surge-cli --raw dump policy
surge-cli --raw dump profile
```

Then test the policy or proxy under investigation:

```bash
surge-cli --raw test-policy <policy-name>
surge-cli --raw test-policy-udp <policy-name>
surge-cli --raw test-policy-external-ip <policy-name>
surge-cli --raw test-policy-nat-type <policy-name>
```

If a policy returns an empty object or a missing-policy error, confirm the
policy exists in the active profile before treating the VPS as broken.

## Enhanced Mode Pitfall

When Surge enhanced mode or rule mode is active, local CLI tools can route
through the same proxy being tested. Before SSH or direct TCP tests touch a
Snell endpoint, route that endpoint as `DIRECT` with a temporary rule.

Permanent `DIRECT` rules are profile changes. Add them only after confirming
the endpoint belongs to the user's fleet and after recording the rollback path.

## Run Directory

Remote work moves as a directory:

```bash
uv run --script scripts/surge_patch.py prepare --operation audit-snell --host root@203.0.113.10
uv run --script scripts/surge_patch.py upload --run-dir /tmp/surge-patch-runs/<run_id>
uv run --script scripts/surge_patch.py run --run-dir /tmp/surge-patch-runs/<run_id>
uv run --script scripts/surge_patch.py collect --run-dir /tmp/surge-patch-runs/<run_id>
```

For repair or installation, choose the Snell version from the official release
notes. A persistent run names its effects before it is prepared:

```bash
uv run --script scripts/surge_patch.py prepare \
  --operation install-snell \
  --host root@203.0.113.10 \
  --snell-version 5.0.1 \
  --confirm-persistent
```

The uploaded directory is the recovery boundary. It contains the run id, input,
captured stdout, captured stderr, exit code, parsed result, and raw logs. The
private Debian payload is copied into that directory during `prepare`.

## VPS Checks

The remote audit records these facts:

```bash
systemctl show snell-server -p ActiveState -p SubState -p Result -p NRestarts -p LimitNOFILE
systemctl cat snell-server
ss -lntup
journalctl -u snell-server --since <window> --no-pager
```

Always inspect the effective unit with `systemctl cat`, because drop-ins can
keep incompatible hardening active after the main service file is replaced.

## Known Bad Pattern

Snell UDP/QUIC paths can fail under over-aggressive systemd hardening. These
log lines identify the failure mode:

```text
UDP socket send error: invalid argument
uv_close: Assertion `0' failed
signal 6
```

Treat active drop-ins containing directives such as `PrivateDevices`,
`ProtectSystem`, `RestrictAddressFamilies`, or empty capability sets as suspect.

## Stable Service Baseline

Stable Debian/systemd baseline:

```ini
[Service]
Type=simple
User=snell
Group=snell
ExecStart=/usr/local/bin/snell-server -c /etc/snell/snell-server.conf
Restart=always
RestartSec=2
LimitNOFILE=1048576
UMask=0077
```

This keeps privilege separation and restart behavior without sandboxing that
can break Snell UDP/QUIC.

## Reading Results

A healthy Snell audit has `status` set to `ok` or `warn`, no
`failed_checks`, `active=active`, `sub=running`, `tcp_listen=yes`,
`udp_listen=yes`, `hardening_mentions=0`, and `udp_crash_markers=0`.

`Decryption failed` is not automatically a server failure. It may come from
naked TCP probes, wrong PSK clients, stale devices, scanners, or the operator's
own tests. Treat it as a warning unless there is load, resource exhaustion, or
confirmed abuse.

## Output and Evidence

Structured CLI stdout is JSON. Raw command output belongs in stderr or run-dir
logs. Clean Debian hosts may have no Python packages, so the VPS payload uses
Bash for package, systemd, and Snell steps.
