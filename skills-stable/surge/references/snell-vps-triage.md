# Snell VPS Evidence Audit

Surge + Snell failure can be local Surge routing, the Snell listener, systemd,
firewall rules, provider networking, Linux limits, or the VPS outbound path.

Look first. Do not apply changes, restart services, install software, or tune
the VPS during audit.

## Local Surge Policy Smoke Tests

Collect the local state before judging Surge runtime or profile state:

```bash
surge-cli --raw environment
surge-cli --raw dump policy
surge-cli --raw dump profile
```

Test the policy or proxy under investigation:

```bash
surge-cli --raw test-policy <policy-name>
surge-cli --raw test-policy-udp <policy-name>
surge-cli --raw test-policy-external-ip <policy-name>
surge-cli --raw test-policy-nat-type <policy-name>
```

If a policy returns an empty object or a missing-policy error, confirm that the
policy exists in the active profile before blaming the VPS.

## Surge Routing

When Surge enhanced mode or rule mode is active, local CLI tools can route
through the proxy being tested. Before SSH or direct TCP tests touch a Snell
endpoint, check whether the active profile already routes that endpoint as
`DIRECT`.

If a temporary `DIRECT` rule is needed, output it as a manual operator action
with the expected rollback. Do not change Surge runtime or profile state from
the audit path.

## Remote Audit

Audit one VPS:

```bash
uv run --script "$SKILL_DIR/scripts/snell_audit.py" audit-snell \
  --host root@203.0.113.10 \
  --journal-since "6 hours ago" \
  --out /tmp/surge-snell-runs
```

Audit a fleet:

```bash
uv run --script "$SKILL_DIR/scripts/snell_audit.py" audit-fleet \
  --hosts ./snell-hosts.txt \
  --journal-since "6 hours ago" \
  --out /tmp/surge-snell-runs
```

Print manual repair actions:

```bash
uv run --script "$SKILL_DIR/scripts/snell_audit.py" render-repair-plan \
  --audit /tmp/surge-snell-runs/<run_id>/audit.json
```

`audit-snell` exits non-zero only when SSH, upload, remote execution, or
collection failed. A completed audit with `status=issue` exits zero unless
`--fail-on-issue` is set.

## What The Audit Reads

The remote audit reads these commands and files:

```bash
systemctl show snell-server -p ActiveState -p SubState -p Result -p NRestarts -p LimitNOFILE -p User -p Group -p Restart -p MainPID
systemctl cat snell-server
ss -lntup
sshd -T
ufw status verbose
nft list ruleset
iptables -S
ip6tables -S
sysctl net.core.default_qdisc net.ipv4.tcp_congestion_control net.core.somaxconn net.ipv4.tcp_max_syn_backlog net.ipv4.ip_local_port_range net.ipv4.ip_local_reserved_ports
swapon --show --bytes
journalctl -u snell-server --since <window> -o short-iso --no-pager
```

Always inspect `systemctl cat`. Drop-ins can keep hardening active even when
the main service file looks clean.

The raw log is redacted. Snell `psk` must never appear in evidence files.

## Snell v5 And v6

| Version | Listener                                          | Config                                                  | Firewall                                                        |
| ------- | ------------------------------------------------- | ------------------------------------------------------- | --------------------------------------------------------------- |
| v5      | TCP + UDP can be valid in UDP/QUIC deployments    | `listen` and `psk`; old fields can be present           | UDP exposure may be intentional when the service listens on UDP |
| v6      | Usually TCP-only                                  | Avoid old `ipv6`, `obfs`, `reuse`, and `version` fields | Keep UDP closed unless the user gives a concrete reason         |

Do not mark `udp_listen=yes` as always healthy. Do not mark `udp_listen=no` as
always broken.

## Small Snell VPS Baseline

A pure Snell VPS should look plain:

- Debian or Ubuntu minimal
- Snell as one binary and one systemd service
- no panel, Docker, Nginx, dashboard, heavy monitoring, or big IP lists unless
  the machine is also an app host
- key-only SSH, with SSH limits judged from SSH config and inventory
- only SSH and Snell exposed
- small proxy sysctl set
- bounded journald
- swap as an OOM cushion, not a speed trick

Only when the user request, Snell config, listener/firewall inventory, or client
profile identifies a Snell v5 UDP/QUIC deployment, accept the documented
listener shape, such as both TCP and UDP on the configured Snell port.

For ordinary Snell v6, expect TCP unless the user gives a UDP reason.

If `recommended_manual_actions` needs an operator action plan, read
[Snell Operator Action Patterns](snell-operator-action-patterns.md). Do not
treat the baseline as a mandate to rewrite an app or container host. If Docker, x-ui,
nginx-proxy-manager, web ports, or dashboards are real workloads, preserve them
and judge Snell separately.

## UDP Crash Pattern

Snell v5 UDP/QUIC can fail when systemd hardening blocks the socket path. These
lines matter when they appear together:

```text
UDP socket send error: invalid argument
uv_close: Assertion `0' failed
signal 6
Main process exited
```

Drop-ins with `PrivateDevices`, `ProtectSystem`, `RestrictAddressFamilies`,
`CapabilityBoundingSet`, `NoNewPrivileges`, or `PrivateTmp` need manual review.
Do not delete them automatically.

## Audit JSON Result

Start with `audit.json`:

- `facts`: what the audit saw
- `findings`: what looks wrong or worth checking
- `evidence_paths`: local files to inspect
- `recommended_manual_actions`: actions to consider, not commands to run

Important finding ids:

- `snell.service_inactive`
- `snell.tcp_not_listening`
- `snell.v5.udp_crash`
- `systemd.hardening_present`
- `transport.audit_failed`

`Decryption failed` is not automatically a server failure. It can be scanner
traffic, a wrong PSK, a stale client, or the operator's own test. Treat it as a
warning unless load, resource pressure, or crashes point to a real failure.

## Audit CLI Output Contract

Stdout is one JSON object. Logs and command output stay in the run directory.
Remote collection uses Bash; do not require Python packages on the VPS.
