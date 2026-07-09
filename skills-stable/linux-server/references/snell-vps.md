# Snell VPS

A pure Snell VPS has a clean OS, one Snell service, key-only SSH, the ports it
needs, a small proxy sysctl set, bounded logs, and swap as an OOM cushion. Do
not turn a pure Snell VPS into a panel host.

## First Decide The Host Type

Pure Snell VPS:

- Keep the host plain.
- Do not add Docker, Nginx, panels, dashboards, heavy monitoring, or broad
  firewall lists unless the user asks.
- Open SSH and Snell, nothing else.

Container or app host:

- Preserve Docker, x-ui, nginx-proxy-manager, web ports, and admin ports that
  are already serving real workloads.
- Map public ports before closing anything.
- Bring Snell itself toward the baseline; do not force the whole host into a
  pure-node firewall shape.

## Snell Service

Get `snell-server` from the official zip, `https://dl.nssurge.com/snell/snell-server-v<VERSION>-linux-<ARCH>.zip`; current versions and release notes are on the Surge Knowledge Base Snell page. Do not use third-party one-click installers — they add panels and firewall rules this baseline rejects.

Use a dedicated service user (creation recipe in [containers.md](containers.md) Service Users) and a small unit:

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

Do not add aggressive systemd sandboxing by default. In particular, do not
copy in `PrivateDevices`, `ProtectSystem`, `RestrictAddressFamilies`, broad
capability restrictions, `NoNewPrivileges`, or `PrivateTmp` unless the user
asked for that hardening and the Snell UDP path has been tested afterward.

Snell v5 can use TCP and UDP when the user request, Snell config,
listener/firewall inventory, or client profile shows UDP/QUIC use. Snell v6 is
normally TCP-only unless the user gives a concrete UDP need. Version behavior
drifts with releases; check the Surge KB Snell release notes when in doubt.

## SSH

Use the single-owner VPS shape and the `MaxAuthTries` rule from
[ssh.md](ssh.md). Do not force non-root admin users or `AllowUsers` onto a
single-owner Snell VPS unless the user asks.

## Firewall

For a pure Snell v5 VPS using the configured Snell port:

```text
22/tcp
<snell-port>/tcp
<snell-port>/udp
```

For Snell v6 without a UDP requirement:

```text
22/tcp
<snell-port>/tcp
```

UFW and nftables are both fine. Keep one clear owner for host firewall rules.
Do not mix UFW, hand-written iptables, nftables, Docker rules, and large IP
blacklists without a reason.

## Proxy Sysctl

Use this only for proxy/VPN tuning work, not for ordinary SSH or firewall
changes:

```ini
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.ip_local_port_range = 20000 65000
net.ipv4.ip_local_reserved_ports = <snell-port>
net.ipv4.tcp_syncookies = 1
```

Confirm BBR support and sysctl writability before writing. Reserve the real
Snell port, not a copied example port; reserved ports only matter inside
`ip_local_port_range`. Add `tcp_mtu_probing` only per the evidence table in
[performance-tuning.md](performance-tuning.md).

Do not make `nf_conntrack_max` a required baseline. Raise it only when Docker,
NAT, stateful firewall rules, or observed conntrack pressure justify it.

Do not copy broad TCP buffer, `tcp_tw_reuse`, `tcp_abort_on_overflow`, or
50-line tuning lists.

## Logs And Swap

Bound journald on noisy nodes through a drop-in in `/etc/systemd/journald.conf.d/`:

```ini
SystemMaxUse=256M
RuntimeMaxUse=64M
```

For small Snell VPSes, size swap per [swap.md](swap.md). Swap is not a
throughput tuning. If swap is already present and idle, leave it alone.

## Do Not Do This By Default

| Do not | Reason |
| --- | --- |
| Add complex systemd sandboxing | It can break Snell v5 UDP/QUIC |
| Close UDP on v5 without checking | v5 UDP/QUIC deployments may need it |
| Upgrade a stable fleet to v6 | Treat v6 as a deliberate change, not cleanup |
| Tighten an app/container host like a pure Snell VPS | Docker and app ports may be real traffic |
| Tune conntrack without evidence | It is not the normal bottleneck on a plain Snell node |
| Copy large sysctl lists | They hide risk and rarely solve the real bottleneck |
