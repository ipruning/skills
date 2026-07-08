# Snell VPS Evidence Audit

A Surge + Snell failure can originate in local Surge routing, the Snell
listener, systemd, firewall rules, provider networking, Linux limits, or the VPS
outbound path.

Look first. The audit may run read-only collection commands over SSH. Do not
apply changes, restart services, install software, or tune the VPS during audit.

## Local Surge Policy Smoke Tests

Collect the local state before judging Surge runtime or profile state:

```bash
surge-cli --raw environment
surge-cli --raw dump policy
surge-cli --raw dump profile
```

Test the Surge policy under investigation:

```bash
surge-cli --raw test-policy <policy-name>
surge-cli --raw test-policy-udp <policy-name>
surge-cli --raw test-policy-external-ip <policy-name>
surge-cli --raw test-policy-nat-type <policy-name>
```

If a policy returns an empty object or a missing-policy error, confirm that the
policy exists in the active profile before blaming the VPS.

In this document, "command succeeds" means `surge-cli` exits successfully and
returns parseable output. "UDP relay works" means `test-policy-udp` reports a
usable relay result. NAT Type A/C is a separate semantic result from
`test-policy-nat-type`; a successful command can still report NAT Type C.

If using `smoke-surge`, top-level `status=ok` means all requested probes passed.
`status=warn` means at least one probe was unsupported. Do not call UDP relay or
NAT traversal healthy until the relevant `results[]` entry has
`status="passed"` and the `parsed` value shows the expected result.

Interpret UDP relay and NAT traversal separately:

- `test-policy-udp` success confirms UDP relay through the selected policy. For
  Snell v6, this normally means UDP over the TCP proxy connection. It does not
  require Snell to listen on or expose UDP on the Snell service port.
- `test-policy-nat-type` checks NAT traversal for the Snell VPS's outbound UDP
  sockets. If TCP, external IP, and UDP relay tests pass but NAT returns
  Type C (`nat-type=3`) for a self-managed Snell VPS used by Surge Ponte, a
  firewall layer is likely blocking third-party STUN replies to the VPS IPv4
  ephemeral UDP source port range (`net.ipv4.ip_local_port_range`).
- Read `net.ipv4.ip_local_port_range` on the VPS and identify the layer that
  controls inbound UDP: UFW, nftables/iptables, or a provider firewall or
  security group. With UFW and `ip_local_port_range = 20000 65000`, plan
  `ufw allow 20000:65000/udp`, not `<snell-port>/udp`.

## Surge Routing

When Surge Enhanced Mode or rule mode is active, local CLI tools can route
through the proxy being tested. Before SSH or direct TCP tests touch a Snell
endpoint, check whether the active profile already routes that endpoint as
`DIRECT`.

If a temporary `DIRECT` rule is needed, output it as a manual operator action
with the expected rollback. Do not change Surge runtime or profile state from
the audit path.

## Remote Audit

Audit one VPS. Pass `--port <snell-port>` unless the endpoint uses the default
`14180`:

```bash
uv run --script "$SKILL_DIR/scripts/snell_audit.py" audit-snell \
  --host root@203.0.113.10 \
  --port <snell-port> \
  --journal-since "6 hours ago" \
  --out /tmp/surge-snell-runs
```

Audit a fleet:

```bash
uv run --script "$SKILL_DIR/scripts/snell_audit.py" audit-fleet \
  --hosts ./snell-hosts.txt \
  --port <snell-port> \
  --journal-since "6 hours ago" \
  --out /tmp/surge-snell-runs
```

`audit-snell` exits non-zero only when SSH, upload, remote execution, or
collection failed. A completed audit with `status=issue` exits zero unless
`--fail-on-issue` is set.

## Remote Audit Evidence Inventory

The remote payload reads state only. It writes logs under the run directory and
reads:

```bash
hostname -f || hostname
date -u
uname -a
snell-server -v
sha256sum <snell-binary>
systemctl show snell-server -p ActiveState -p SubState -p Result -p NRestarts -p LimitNOFILE -p User -p Group -p Restart -p MainPID
systemctl is-enabled snell-server
systemctl cat snell-server
ss -lntup
sshd -T
ufw status verbose
nft list ruleset
iptables -S
ip6tables -S
docker ps --format '{{.ID}} {{.Names}} {{.Ports}}'
sysctl net.core.default_qdisc net.ipv4.tcp_congestion_control net.core.somaxconn net.ipv4.tcp_max_syn_backlog net.ipv4.tcp_syncookies net.ipv4.ip_local_port_range net.ipv4.ip_local_reserved_ports net.ipv4.tcp_mtu_probing net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
swapon --show --bytes
df -Pk / /var /boot
journalctl -u snell-server --since <window> -o short-iso --no-pager
journalctl --disk-usage
```

It also counts readable `/root/.ssh/authorized_keys` entries, reads the Snell
config path found from `ExecStart -c`, and reads `/proc/meminfo`, `/etc/fstab`,
and `/etc/os-release` for the memory, swap, and OS facts.

Always inspect `systemctl cat`. Drop-ins can keep hardening active even when
the main service file looks clean.

The payload redacts `psk = ...` lines when it prints the Snell config. It does
not prove every evidence file is secret-free. Do not put plaintext PSKs in
service units, journal messages, host files, policy names, or run IDs; before
sharing a run directory, scan the evidence for secrets.

## Snell v5 And v6

| Version | Listener                                       | Config                                                  | Firewall                                                        |
| ------- | ---------------------------------------------- | ------------------------------------------------------- | --------------------------------------------------------------- |
| v5      | TCP + UDP can be valid in UDP/QUIC deployments | `listen` and `psk`; old fields can be present           | UDP exposure may be intentional when the service listens on UDP |
| v6      | Usually TCP-only                               | Avoid old `ipv6`, `obfs`, `reuse`, and `version` fields | Keep UDP closed unless the user gives a concrete reason         |

Do not mark `udp_listen=yes` as always healthy. Do not mark `udp_listen=no` as
always broken.

## Snell v6 Canary

Classify Snell v6 work as a beta canary before planning changes.

- Keep the Snell server and Surge client on builds that both support Snell v6.
- Do not add old Snell `obfs` settings. Snell v6 derives protocol diversity
  from the PSK.
- Use a fresh high-entropy PSK for each v6 canary. Do not reuse a v5 PSK or
  share one PSK across nodes.
- Keep ordinary Snell v6 canaries TCP-only. Snell v6 does not use the v5 QUIC
  proxy mode; on the Surge side keep `block-quic=on` or the platform default.
- Keep Snell server `mode` at the default unless the user explicitly asks to
  test `unshaped` or `unsafe-raw`.
- Use v6 server config keys that `snell-server --help` actually accepts:
  `listen`, `psk`, optional `dns`, optional `dns-ip-preference`, optional
  `egress-interface`. `dns-ip-preference` values are `default`, `prefer-ipv4`,
  `prefer-ipv6`, `ipv4-only`, and `ipv6-only`.
- For a previous v5 config with `ipv6 = false`, prefer
  `dns-ip-preference = ipv4-only` over the deprecated `ipv6` key.

Surge profile canary line:

```ini
node-name = snell, <host>, <port>, psk=<fresh-psk>, version=6, block-quic=on
```

Snell server minimal v6 config:

```ini
[snell-server]
listen = 0.0.0.0:<port>
psk = <fresh-psk>
dns-ip-preference = ipv4-only
```

Before a v6 operator change, confirm the VPS is a suitable canary:

- `audit-snell` completes against the host.
- The Snell service is active, and the audit identifies the config path.
- The plan names backup paths for the binary, config, systemd unit, and firewall
  state.
- SSH access works with an explicit key or agent identity.
- The active Surge profile routes the Snell endpoint IP as `DIRECT`.
- The rollback plan restores the old binary, config, and unit. If the previous
  deployment was v5 UDP/QUIC, the rollback plan also reopens UDP.

After a v6 operator change, verify all of these:

- `snell-server -v` reports the expected v6 beta.
- systemd reports `ActiveState=active`, `SubState=running`, and `NRestarts=0`.
- `ss -lntup` shows a TCP listener on the Snell port and no UDP listener.
- The firewall allows `<port>/tcp` and does not allow `<port>/udp`.
- The redacted config contains no legacy `ipv6`, `obfs`, `reuse`, or `version`
  key.
- The journal has no parameter errors; check specifically for invalid
  `dns-ip-preference`.
- The local profile passes `surge-cli --check`.
- The local and remote PSKs match without logging the plaintext value.
- `surge-cli --raw test-policy <policy>` and
  `surge-cli --raw test-policy-external-ip <policy>` succeed.
- `test-policy-udp` succeeds as UDP relay traffic through the TCP proxy. This
  result does not mean the Snell server should expose UDP.
- For a Snell policy used by Surge Ponte, `test-policy-nat-type` should return
  NAT Type A (`nat-type=1`) unless that workflow accepts a lower NAT class. If
  it stays Type C (`nat-type=3`) while ordinary proxy tests pass, allow inbound
  UDP to the VPS IPv4 ephemeral UDP source port range rather than opening the
  Snell service port over UDP.

## Small Snell VPS Baseline

A VPS whose only workload is Snell should look plain:

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

If `recommended_manual_actions` is non-empty, or your reading of `facts` calls
for a tuning change, read
[Snell Operator Action Patterns](snell-operator-action-patterns.md) before
writing the plan. Do not
treat the baseline as a mandate to rewrite an app or container host. If Docker,
x-ui, nginx-proxy-manager, web ports, or dashboards are real workloads, preserve
them and judge Snell separately.

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

Finding ids:

- `snell.service_inactive`
- `snell.service_not_running`
- `snell.tcp_not_listening`
- `snell.v5.udp_crash`
- `snell.v5.historical_crash_markers`
- `snell.v6.udp_listener_present`
- `snell.v6.udp_firewall_exposed`
- `snell.v6.legacy_config_keys`
- `systemd.hardening_present`
- `transport.audit_failed`

Findings stop at structural problems: crash fingerprints, exposure, hardening,
and availability. Performance and capacity tuning is judged from `facts` by the
reader. `facts.sysctl`, `facts.swap`, `facts.systemd.limit_nofile`,
`facts.ssh.max_auth_tries`, and `facts.logs` carry the measured values without
grading them.

`Decryption failed` counts appear in `facts.logs.decryption_failed_count` with
the top source in `facts.logs.top_decryption`. All `facts.logs.*` counts come
from a keyword-filtered journal excerpt capped at 500 lines; treat them as
lower bounds that saturate on noisy hosts. `Decryption failed` is not
automatically a server failure. It can be scanner traffic, a wrong PSK, a stale client, or the
operator's own test. Treat it as noise unless load, resource pressure, or
crashes point to a real failure.

## Audit CLI Output Contract

Stdout is one JSON object. Logs and command output stay in the run directory.
Remote collection uses Bash; do not require Python packages on the VPS.
`audit-snell` uploads a payload to `/var/tmp/surge-snell-runs/<run_id>`, collects
the run directory back to the local `--out` path, then removes the remote run
directory after a successful collect. If collection fails or cleanup fails,
`persistent_effects` names the remote directory that may remain.
