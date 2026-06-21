# Snell Operator Action Patterns

Use these patterns only after an audit finding includes a
`recommended_manual_actions` item that needs a human change plan. They are
examples for the human operator; do not apply them during diagnosis.

## Proxy Sysctl Baseline

For a VPS whose only workload is Snell, a small proxy sysctl set can look like
this:

```ini
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.ip_local_port_range = 20000 65000
net.ipv4.ip_local_reserved_ports = 22,<snell-port>
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_syncookies = 1
```

## Journald Bounds

On noisy VPSes, bounded journald settings can look like this:

```ini
SystemMaxUse=256M
RuntimeMaxUse=64M
```

## Surge Ponte NAT Traversal UFW Plan

Plan an inbound UDP ephemeral-port allowance only when all conditions hold:

- A Surge policy uses Surge Ponte or another UDP traversal workflow.
- The self-managed Snell VPS has a public address and no Docker or provider NAT
  layer explains the result.
- `test-policy`, `test-policy-external-ip`, and `test-policy-udp` return
  successful results, while `test-policy-nat-type` returns NAT Type C
  (`nat-type=3`).
- Snell v6 is active, listens on TCP, and has no Snell UDP listener requirement.
  Do not open `<snell-port>/udp`.

The VPS sends STUN traffic from its IPv4 ephemeral UDP source port range
(`net.ipv4.ip_local_port_range`). Read that range on the VPS:

```bash
sysctl net.ipv4.ip_local_port_range
```

For a human operator on a UFW-managed VPS whose range is `20000 65000`, the
manual plan can back up UFW rules and allow inbound UDP to that range:

```bash
backup_dir="/root/ufw-backup-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 -p "$backup_dir"
cp -a /etc/ufw/user.rules /etc/ufw/user6.rules "$backup_dir"/ 2>/dev/null || true
ufw allow 20000:65000/udp comment 'surge-ponte-nat-traversal'
ufw status verbose
```

Verify from Surge:

```bash
surge-cli --raw test-policy <policy-name>
surge-cli --raw test-policy-external-ip <policy-name>
surge-cli --raw test-policy-udp <policy-name>
surge-cli --raw test-policy-nat-type <policy-name>
```

`test-policy-nat-type` should return NAT Type A (`nat-type=1`) unless another
firewall layer blocks inbound UDP. If it remains Type C (`nat-type=3`), inspect
provider firewall or security-group UDP rules before changing Snell.

To roll back:

```bash
ufw delete allow 20000:65000/udp
```

## Stable Snell v5 Unit

When `audit.json` identifies a VPS whose only workload is Snell v5 and the
manual plan needs a non-sandboxed unit shape, use a small service like this:

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

This keeps privilege separation and restart behavior without sandboxing that can
break Snell v5 UDP/QUIC. It is not a reason to rewrite a working service.
Do not add aggressive systemd sandboxing by default.
Do not treat this as a mandate to rewrite an app or container host.
