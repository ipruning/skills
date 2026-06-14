# Snell Operator Action Patterns

Use this reference only after `audit.json` or `recommended_manual_actions`
identifies a manual operator action to plan. These are patterns for a human
operator; do not apply them from this Skill.

## Proxy Sysctl Baseline

For a pure Snell node, a small proxy sysctl set can look like this:

```ini
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.ip_local_port_range = 20000 65000
net.ipv4.ip_local_reserved_ports = 22,14180
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

This unit shape has been stable on the known existing Snell v5 fleet:

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

It keeps privilege separation and restart behavior without sandboxing that can
break Snell v5 UDP/QUIC. It is not a reason to rewrite a working service.
Do not add aggressive systemd sandboxing by default.
Do not treat this as a mandate to rewrite an app or container host.
