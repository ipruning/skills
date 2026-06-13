# Snell VPS

A good Snell VPS is plain: clean OS, one Snell service, key-only SSH, the
ports it needs, a small proxy sysctl set, bounded logs, and swap as an OOM
cushion. Do not turn a pure proxy node into a panel host.

## First Decide The Host Type

Pure Snell node:

- Keep the machine small and boring.
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

Use a dedicated service user and a small unit:

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

Snell v5 on the existing fleet can use TCP and UDP. Snell v6 is normally
TCP-only unless the user gives a concrete UDP need.

## SSH

For a single-owner Snell VPS:

```text
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
MaxAuthTries 20
```

`MaxAuthTries 20` is there for 1Password SSH agent and other multi-key agents.
Do not force non-root admin users or `AllowUsers` onto a single-owner proxy
node unless the user asks.

## Firewall

For a pure Snell v5 node using port `14180`:

```text
22/tcp
14180/tcp
14180/udp
```

For Snell v6 without a UDP requirement:

```text
22/tcp
14180/tcp
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
net.ipv4.ip_local_reserved_ports = 22,14180
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_syncookies = 1
```

Confirm BBR support and sysctl writability before writing. If the Snell port is
not `14180`, reserve the real port instead.

Do not make `nf_conntrack_max` a required baseline. Raise it only when Docker,
NAT, stateful firewall rules, or observed conntrack pressure justify it.

Do not copy broad TCP buffer, `tcp_tw_reuse`, `tcp_abort_on_overflow`, or
50-line tuning lists.

## Logs And Swap

Bound journald on noisy nodes:

```ini
SystemMaxUse=256M
RuntimeMaxUse=64M
```

Use 2-4 GiB swap on small VPSes as a crash cushion. Swap is not a throughput
tuning. If swap is already present and idle, leave it alone.

## Do Not Do This By Default

| Do not | Reason |
| --- | --- |
| Add complex systemd sandboxing | It can break Snell v5 UDP/QUIC |
| Close UDP on v5 without checking | Existing v5 UDP/QUIC nodes may need it |
| Upgrade a stable fleet to v6 | Treat v6 as a deliberate change, not cleanup |
| Tighten an app/container host like a pure proxy node | Docker and app ports may be real traffic |
| Tune conntrack without evidence | It is not the normal bottleneck on a plain Snell node |
| Copy large sysctl lists | They hide risk and rarely solve the real bottleneck |
