# Performance And Network Tuning

Use these commands only when the user asks for proxy/VPN performance tuning, BBR, sysctl, latency, throughput, or crypto algorithm policy.

Network tuning is not SSH or firewall security. Do not add sysctls to a normal VPS security change.

## Virtualization Check

```bash
systemd-detect-virt
uname -r
```

LXC and OpenVZ containers share the host kernel. Node-level sysctls such as `net.core.default_qdisc` may not be writable from inside the container. Some `net.*` sysctls are namespaced and can be set per container; verify before writing.

## BBR

BBR requires kernel support:

```bash
sysctl net.ipv4.tcp_available_congestion_control
modinfo tcp_bbr >/dev/null 2>&1 && echo "tcp_bbr module present"
```

If output does not include `bbr`, and `modinfo tcp_bbr` succeeds, load the module in a separate step:

Runtime impact: loads `tcp_bbr` into the running kernel until the module is unloaded or the host reboots; persistence requires a separate module-load configuration.

```bash
modprobe tcp_bbr
sysctl net.ipv4.tcp_available_congestion_control
```

If output still does not include `bbr`, omit `net.ipv4.tcp_congestion_control` and `net.core.default_qdisc`.

## Proxy/VPN Sysctls

These are conditional proxy/VPN tuning candidates, not a generic VPS security
baseline. Use them only after confirming BBR support, VM/container sysctl
writability, and the service port that must be reserved:

```ini
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.ip_local_port_range = 20000 65000
net.ipv4.ip_local_reserved_ports = 22,<SERVICE_PORT>
net.ipv4.tcp_syncookies = 1
```

Apply through a dedicated file:

Persistent impact: writes `/etc/sysctl.d/99-vps-tuning.conf` and changes kernel network parameters until the file is removed and the parameters are explicitly reset or the host reboots.

```bash
cat >/etc/sysctl.d/99-vps-tuning.conf <<'EOF'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.ip_local_port_range = 20000 65000
net.ipv4.ip_local_reserved_ports = 22,<SERVICE_PORT>
net.ipv4.tcp_syncookies = 1
EOF
sysctl -p /etc/sysctl.d/99-vps-tuning.conf
```

After deleting a sysctl drop-in, `sysctl --system` does not restore deleted parameters to kernel defaults. Revert explicitly with `sysctl -w <param>=<default>` or reboot.

## Settings Requiring Evidence

Do not set these from copied tuning lists without benchmarks:

| Parameter | Reason |
| --- | --- |
| `tcp_fastopen = 3` | Server-side support still depends on listener behavior; set only when the listener and client path are tested |
| `rmem_max` / `wmem_max` | TCP autotuning adjusts buffers automatically; overrides can reduce throughput |
| `tcp_fin_timeout` | Only affects orphan FIN_WAIT_2 sockets |
| `tcp_max_tw_buckets` | Kernel defaults scale with memory; lowering can harm busy hosts |
| `tcp_tw_reuse` | Keep the kernel default unless packet capture or connection metrics show TIME_WAIT reuse as the bottleneck |
| `netdev_max_backlog` | Tune only when NIC receive drops are visible in `ip -s link` or driver counters |
| `keepalive_*` | Tune in the application first when the application exposes keepalive settings |
| `tcp_mtu_probing = 1` | Use as a fleet convention or when PMTU black-hole symptoms are visible; do not make it a universal default |

## SSH Crypto Algorithms

Do not rewrite `KexAlgorithms`, `Ciphers`, or `MACs` during an ordinary VPS security change. Algorithm pinning can break clients and distract from the stronger controls: key-only login, password disabled, correct firewall, and checked package updates.

Only change SSH algorithms when the user explicitly asks for crypto policy work. Verify support first:

```bash
sshd -T | awk '$1 ~ /^(kexalgorithms|ciphers|macs)$/ { print }'
```
