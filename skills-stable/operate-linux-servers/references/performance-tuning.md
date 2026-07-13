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
net.ipv4.ip_local_reserved_ports = <EXISTING_RESERVATIONS>,<SERVICE_PORT>
net.ipv4.tcp_syncookies = 1
```

`ip_local_reserved_ports` is replacement-valued: writing one service port clears every existing reservation. Read the live value and merge it before staging the file.

Apply through a dedicated file with Bash. The transaction records live values and the previous persistent file before applying. A failed key restores both layers; any failed restoration is a critical unresolved state, not a successful rollback.

Persistent impact: writes `/etc/sysctl.d/99-vps-tuning.conf` and changes kernel network parameters until the file is removed and the parameters are explicitly reset or the host reboots.

```bash
: "${SERVICE_PORT:?set SERVICE_PORT to the verified service port}"
case "$SERVICE_PORT" in *[!0-9]*|'') exit 1;; esac
test "$SERVICE_PORT" -ge 1 && test "$SERVICE_PORT" -le 65535 || exit 1
sysctl -n net.ipv4.tcp_available_congestion_control | grep -qw bbr || exit 1

target=/etc/sysctl.d/99-vps-tuning.conf
rollback_dir=$(mktemp -d /run/linux-server-sysctl.XXXXXX)
chmod 700 "$rollback_dir" || exit 1
candidate="$rollback_dir/candidate.conf"
runtime_backup="$rollback_dir/runtime.tsv"
had_target=0
current_reserved=$(sysctl -n net.ipv4.ip_local_reserved_ports) || exit 1
if test -n "$current_reserved"; then
  merged_reserved="${current_reserved},${SERVICE_PORT}"
else
  merged_reserved=$SERVICE_PORT
fi
cat >"$candidate" <<EOF
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.ip_local_port_range = 20000 65000
net.ipv4.ip_local_reserved_ports = $merged_reserved
net.ipv4.tcp_syncookies = 1
EOF
chmod 600 "$candidate" || exit 1
mapfile -t sysctl_keys < <(awk -F= '/^[[:space:]]*[^#[:space:]]/ { key=$1; gsub(/[[:space:]]/, "", key); print key }' "$candidate")
declare -A old_values
: >"$runtime_backup" || exit 1
chmod 600 "$runtime_backup" || exit 1
for sysctl_key in "${sysctl_keys[@]}"; do
  old_values["$sysctl_key"]=$(sysctl -n "$sysctl_key") || exit 1
  printf '%s\t%s\n' "$sysctl_key" "${old_values[$sysctl_key]}" >>"$runtime_backup" || exit 1
done
if test -e "$target"; then
  cp -a "$target" "$rollback_dir/persistent.conf" || exit 1
  had_target=1
else
  : >"$rollback_dir/target-was-absent" || exit 1
fi
restore_sysctl() {
  restore_failed=0
  if test "$had_target" -eq 1; then
    cp -a "$rollback_dir/persistent.conf" "$target" || restore_failed=1
  else
    rm -f "$target" || restore_failed=1
  fi
  while IFS=$'\t' read -r sysctl_key old_value; do
    sysctl -q -w "$sysctl_key=$old_value" || restore_failed=1
  done <"$runtime_backup"
  test "$restore_failed" -eq 0
}
if ! install -o root -g root -m 0644 "$candidate" "$target"; then
  restore_sysctl || echo "CRITICAL: persistent sysctl install failed and rollback was incomplete" >&2
  exit 1
fi
if ! sysctl -p "$target"; then
  if ! restore_sysctl; then
    echo "CRITICAL: sysctl apply failed and rollback was incomplete" >&2
  fi
  exit 1
fi
printf 'sysctl_rollback_dir=%s\n' "$rollback_dir"
```

Keep the printed root-only rollback directory until the proxy/VPN listener and a real client path pass. If a later check fails, restore from a new root Bash shell:

```bash
rollback_dir=<PRINTED_ROLLBACK_DIR>
target=/etc/sysctl.d/99-vps-tuning.conf
restore_failed=0
if test -e "$rollback_dir/persistent.conf"; then
  cp -a "$rollback_dir/persistent.conf" "$target" || restore_failed=1
elif test -e "$rollback_dir/target-was-absent"; then
  rm -f "$target" || restore_failed=1
else
  echo "rollback metadata is incomplete" >&2
  exit 1
fi
while IFS=$'\t' read -r sysctl_key old_value; do
  sysctl -q -w "$sysctl_key=$old_value" || restore_failed=1
done <"$rollback_dir/runtime.tsv"
test "$restore_failed" -eq 0 || { echo "CRITICAL: sysctl rollback was incomplete" >&2; exit 1; }
```

Verify the persistent file, every live key, listener, and client path before removing the directory. `sysctl --system` alone does not restore deleted or replaced values.

`ip_local_reserved_ports` only affects ephemeral allocation inside `ip_local_port_range`; listing ports outside the range is dead configuration.

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
