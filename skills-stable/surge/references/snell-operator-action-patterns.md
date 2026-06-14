# Snell Operator Action Patterns

These patterns apply only after `audit.json` or `recommended_manual_actions`
identifies a manual operator action to plan. They are for a human operator; do
not apply them during diagnosis.

## Proxy Sysctl Baseline

For a pure Snell VPS, a small proxy sysctl set can look like this:

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

On noisy nodes, bounded journald settings can look like this:

```ini
SystemMaxUse=256M
RuntimeMaxUse=64M
```

## Stable Snell v5 Unit

When `audit.json` identifies a pure Snell v5 VPS and the manual plan needs a
non-sandboxed unit shape, use a small service like this:

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
