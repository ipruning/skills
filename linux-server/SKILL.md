---
name: linux-server
description: "Linux server security audit, hardening, and maintenance. Triggers: VPS, remote Linux host, SSH hardening, firewall rules, Debian/Ubuntu patching, unknown server audit, fail2ban, unattended-upgrades. Not for macOS."
metadata:
  version: "6"
---

# VPS Security & Maintenance

For Debian/Ubuntu servers. Use `apt-get`, not `apt`. Apply steps use noninteractive dpkg flags.

## Safety Rules

1. Before changing SSH, firewall, or networking, keep a console/KVM or second live session open. Use `tmux` for long sessions.

2. First round is read-only. Change one surface at a time — SSH, then firewall, then anti-brute-force, then updates, then sysctl — and verify each before moving on.

3. Verify runtime state, not file contents. `sshd -T` shows what SSH is actually enforcing. `nft list ruleset` + `iptables -S` + `ip6tables -S` show what the firewall is actually doing. `ss -tlnup` shows what is actually listening.

4. Patch within the current release only. Major-version upgrades need human approval.

5. Audit and apply are separate phases. Audit uses read-only commands. Package installs, file writes, service reloads, and `nft -f` belong in apply and need human approval.

6. All customizations go into dedicated override files — SSH in `sshd_config.d/`, sysctl in `/etc/sysctl.d/`, fail2ban in `jail.local`, systemd in unit drop-ins. Never modify package-managed defaults. Rollback is always `rm <override> + reload`, and package upgrades never produce conffile conflicts.

## 1. Routine Maintenance

### 1.1 Pre-Maintenance

```bash
whoami && id && date && uptime && uname -r
```

```bash
df -h && free -h && top -bn1 -o %CPU | head -20
```

Stop if `/`, `/var`, or `/boot` is low on space.

```bash
systemctl --failed --no-pager
ss -tlnup
```

```bash
sshd -T | grep -E 'permitrootlogin|passwordauthentication|kbdinteractiveauthentication|x11forwarding|port|allowusers|allowgroups|permituserrc'
grep -i '^Match' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null
sshd -T -C user=root,addr=0.0.0.0,host= | grep -E 'permitrootlogin|passwordauthentication'
```

```bash
nft list ruleset 2>/dev/null | head -50
```

nftables persistence:

```bash
systemctl is-enabled nftables
systemctl is-active nftables
nft -c -f /etc/nftables.conf
```

Compare listeners to allow rules — remove allow rules for ports with no listener:

```bash
echo "=== Listening ===" && ss -tlnp | awk 'NR>1{print $4}' | sort -u
echo "=== Allowed ===" && nft list ruleset 2>/dev/null | grep -oP 'dport \K\S+' | sort -u
```

```bash
systemctl is-active fail2ban && fail2ban-client status sshd
```

```bash
apt-get update
apt-get -s upgrade | head -50
```

### 1.2 During Maintenance

```bash
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y \
  -o Dpkg::Options::=--force-confdef \
  -o Dpkg::Options::=--force-confold \
  upgrade
```

Use `full-upgrade` only for same-release dependency changes. Stop and escalate for major-version upgrades.

`needrestart` below 3.8 has local privilege escalation (CVE-2024-48990), so verify the version before using it:

```bash
needrestart --version
NEEDRESTART_MODE=l needrestart -r l
```

If the running kernel differs from the installed one, schedule a reboot:

```bash
echo "Running: $(uname -r)" && echo "Installed: $(dpkg -l "linux-image-$(dpkg --print-architecture)" 2>/dev/null | awk '/^ii/{print $3}')"
```

### 1.3 Post-Maintenance

```bash
systemctl --failed --no-pager
ss -tlnup
```

```bash
journalctl -p err..alert -b --no-pager | tail -200
journalctl -u ssh -b --no-pager | tail -100
```

```bash
ls -lt /var/log/apt/history.log* 2>/dev/null | head -5
tail -100 /var/log/apt/history.log
ls -lt /var/log/unattended-upgrades/ 2>/dev/null
```

```bash
systemctl is-enabled unattended-upgrades
systemctl list-timers --no-pager 'apt-daily*'
```

## 2. Unknown Server Audit

Establish exposure, access, persistence, and patch status before changing anything.

### 2.1 Preparation

Start a detached `tmux` session and keep a second SSH session open:

```bash
tmux new -d -s audit
```

### 2.2 System Identification

```bash
cat /etc/os-release && uname -a && uptime && hostnamectl && timedatectl
```

### 2.3 Access & Account Audit

```bash
whoami && id
```

```bash
passwd -S root
```

Users with login shells:

```bash
grep -v 'nologin\|false' /etc/passwd
```

SSH authorized keys:

```bash
ls -la /root/.ssh 2>/dev/null
cat /root/.ssh/authorized_keys 2>/dev/null
for d in /home/*/; do echo "=== $d ===" && cat "${d}.ssh/authorized_keys" 2>/dev/null; done
```

Authorized key options like `command=`, `from=`, or `tunnel=` can grant or restrict access in unexpected ways:

```bash
grep -nE 'command=|from=|environment=|permitopen=|tunnel=|principals=' /root/.ssh/authorized_keys 2>/dev/null
for f in /home/*/.ssh/authorized_keys; do
  echo "=== $f ===" && grep -nE 'command=|from=|environment=|permitopen=|tunnel=|principals=' "$f" 2>/dev/null
done
```

### 2.4 SSH Effective Configuration

```bash
sshd -T | grep -E 'port|listenaddress|permitrootlogin|passwordauthentication|pubkeyauthentication|kbdinteractiveauthentication|x11forwarding|allowusers|allowgroups|authenticationmethods|permituserrc'

grep -i '^Match' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null

sshd -T -C user=root,addr=0.0.0.0,host= | grep -E 'permitrootlogin|passwordauthentication|permituserrc'

ls -la /etc/ssh/sshd_config.d/ 2>/dev/null
```

Match blocks can override any global setting per user or address, so always check them.

### 2.5 Network Exposure

```bash
ss -tlnp
ss -ulnp
```

```bash
ip addr && ip route && ip -6 addr && cat /etc/resolv.conf
```

Check nftables, IPv4, and IPv6 separately:

```bash
nft list ruleset 2>/dev/null
iptables -S 2>/dev/null
ip6tables -S 2>/dev/null
```

Use one firewall manager. Mixing nftables with ufw, firewalld, or iptables-persistent causes rules to conflict silently:

```bash
iptables -V
update-alternatives --display iptables 2>/dev/null
```

If the host is in a cloud, inspect security groups in the provider console.

### 2.6 Running Services

```bash
systemctl list-units --type=service --state=running --no-pager
systemctl list-unit-files --state=enabled --no-pager
ps auxf --sort=-%cpu | head -50
```

Look for proxies, tunnels, miners, unfamiliar daemons, and suspicious unit names.

### 2.7 Persistence Mechanisms

```bash
crontab -l 2>/dev/null
ls -la /etc/cron.d/ /etc/cron.daily/ /etc/cron.hourly/ 2>/dev/null
```

```bash
systemctl list-timers --all --no-pager
```

```bash
ls -la /etc/systemd/system/
```

```bash
for d in /home/*/; do
  echo "=== ${d} ===" && ls -la "${d}.config/systemd/user/" 2>/dev/null
done
ls -la /root/.config/systemd/user/ 2>/dev/null
```

`~/.ssh/rc` runs on every SSH login, so it is a common persistence vector:

```bash
for d in /home/*/; do
  echo "=== ${d} ===" && ls -la "${d}.ssh/rc" 2>/dev/null
done
ls -la /root/.ssh/rc 2>/dev/null
```

```bash
find /usr/bin /usr/sbin /bin /sbin -perm /6000 -type f 2>/dev/null | sort
getcap -r / 2>/dev/null | head -200
```

### 2.8 Patch Status

```bash
ls -la /etc/apt/sources.list.d/
cat /etc/apt/sources.list.d/*.sources 2>/dev/null
cat /etc/apt/sources.list.d/*.list 2>/dev/null
```

```bash
apt-get update
apt-get -s upgrade | head -50
```

```bash
systemctl is-enabled unattended-upgrades 2>/dev/null
systemctl list-timers --no-pager 'apt-daily*'
```

### 2.9 Log Analysis

```bash
journalctl -u ssh --since "24 hours ago" --no-pager | tail -200
last -20
lastb -20 2>/dev/null
```

Confirm every source IP in the last 7 days is expected:

```bash
journalctl -u ssh --since "7 days ago" --no-pager | grep -E 'Accepted (publickey|password|keyboard-interactive)' | tail -50
last -50
```

```bash
stat /root/.ssh/authorized_keys 2>/dev/null
for f in /home/*/.ssh/authorized_keys; do stat "$f" 2>/dev/null; done
stat /etc/ssh/sshd_config
ls -la /etc/ssh/sshd_config.d/ 2>/dev/null
```

### 2.10 Remediation Priority

Fix in this order:

1. SSH — `PasswordAuthentication no`, `PermitRootLogin prohibit-password` (then `no` after non-root admin works), `X11Forwarding no`, `PermitUserRC no`, restrict via `AllowUsers`
2. Firewall — default drop, allow only required ports, align allow rules with actual listeners, verify persistence
3. Anti-brute-force — fail2ban or CrowdSec; optional if SSH is key-only and source-restricted
4. Updates — enable unattended-upgrades, verify apt-daily timers fire, confirm Allowed-Origins covers security updates, require needrestart >= 3.8
5. Hardening — sysctl tuning, AppArmor, centralized logging, monitoring, backup

## Reference

### SSH Hardening

Some provider images ship with `PubkeyAuthentication no`. On those systems, write only `PubkeyAuthentication yes` to the drop-in first, restart sshd, and confirm key login works from a second terminal before writing the full hardening config. Disabling passwords and enabling pubkey in the same step risks lockout.

Prefer these settings in `/etc/ssh/sshd_config.d/hardening.conf`:

- `PasswordAuthentication no` — passwords can be guessed, keys cannot
- `PermitRootLogin prohibit-password` — switch to `no` after a non-root admin is verified
- `X11Forwarding no` — Debian defaults to `yes`, but headless servers have no use for it
- `PermitUserRC no` — Debian defaults to `yes`; `~/.ssh/rc` runs on every login and can serve as a backdoor
- `AllowUsers` / `AllowGroups` — supports `user@host` and CIDR for source restriction
- Verify with `sshd -T` and `sshd -T -C user=root,addr=...`
- Audit Match blocks, since they can override any of the above

Debian's openssh-server defaults favor usability over security. After overriding via `sshd_config.d/`, always verify the effective config with `sshd -T`.

To drop legacy algorithms, append the following to `hardening.conf`. The post-quantum KEX algorithms require OpenSSH 9.x+; clients that do not support them will negotiate `curve25519-sha256` instead:

```
KexAlgorithms mlkem768x25519-sha256,sntrup761x25519-sha512,sntrup761x25519-sha512@openssh.com,curve25519-sha256,curve25519-sha256@libssh.org,diffie-hellman-group16-sha512,diffie-hellman-group18-sha512
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com,umac-128-etm@openssh.com,hmac-sha2-512,hmac-sha2-256
```

Verify the server supports all listed algorithms before applying with `sshd -T | grep kexalgorithms`.

### Firewall Modification with Rollback

Save current rules and schedule automatic rollback before changing firewall rules. If connectivity breaks, the old rules restore after 2 minutes:

```bash
nft list ruleset > /tmp/nft-backup.conf
nft -c -f /path/to/new-rules.conf
systemd-run --on-active=120 --unit=nft-rollback nft -f /tmp/nft-backup.conf
nft -f /path/to/new-rules.conf
```

Cancel the rollback timer once connectivity is confirmed:

```bash
systemctl stop nft-rollback.timer 2>/dev/null
```

### Firewall Rule Alignment

Every allow rule should correspond to a listener, and every listener should have an allow rule. Mismatches in either direction are problems: an open port with no listener is unnecessary attack surface, and a listener with no allow rule is either blocked or relying on an implicit permit.

1. Run `ss -tlnp` and `ss -ulnp` to discover listeners
2. Extract allowed ports from `nft list ruleset` (`grep -oP 'dport \K\S+'`)
3. Flag mismatches in both directions
4. If containers are present, inspect `forward` rules for bridge interfaces
5. Write rules based on actual + planned ports only
6. Dry-run with `nft -c -f <ruleset>` before applying
7. Verify with `nft list ruleset` after applying

### nftables Forward Chain and Containers

Docker's iptables rules and nftables `inet` hooks are independent chains evaluated in parallel. If nftables has `inet filter forward` with `policy drop`, container traffic is blocked even though Docker added its own FORWARD rules:

```bash
nft list chain inet filter forward 2>/dev/null
docker run --rm alpine ping -c1 1.1.1.1
```

Add explicit forward rules for container bridges:

```bash
nft add rule inet filter forward iifname "br-*" accept
nft add rule inet filter forward oifname "br-*" accept
nft add rule inet filter forward iifname "docker0" accept
nft add rule inet filter forward oifname "docker0" accept
```

Persist in `/etc/nftables.conf` and verify with `nft -c -f /etc/nftables.conf`. On container hosts, inspect `forward` rules as well as `input` rules.

### ufw Firewall with Docker/Container Compatibility

ufw defaults to `deny routed`, which blocks Docker FORWARD traffic even though Docker's own iptables rules exist. Allow routed traffic on each container bridge interface:

```bash
ufw route allow in on <BRIDGE_IFACE>
ufw route allow out on <BRIDGE_IFACE>
```

Run `docker network ls` and `ip link` to find bridge names. Repeat for each bridge (`docker0`, `br-*`, overlay interfaces like `uncloud`).

Services that bind inside containers but need host-level INPUT access (WireGuard, internal DNS) require rules in `/etc/ufw/before.rules` after the loopback section:

```
-A ufw-before-input -p udp --dport <WIREGUARD_PORT> -j ACCEPT
-A ufw-before-input -i <BRIDGE_IFACE> -d <BRIDGE_IP>/32 -p tcp --dport 53 -j ACCEPT
-A ufw-before-input -i <BRIDGE_IFACE> -d <BRIDGE_IP>/32 -p udp --dport 53 -j ACCEPT
```

Reload with `ufw reload` and verify with `ufw status verbose`.

Use one firewall manager per host. If nftables is already configured, do not install ufw. If ufw is already in use, manage all rules through ufw.

### Hosting Provider Control Plane Security

An attacker who compromises the provider's control panel can bypass all OS defenses via rescue console, KVM, or disk re-imaging.

- Enable 2FA on the provider account
- Restrict and rotate API keys
- Know how to reach rescue console/KVM before you need it

Hetzner-specific: configure Login-OTP / Support-OTP to prevent social-engineering attacks against support. The Rescue System is a PXE-booted Debian live environment in RAM — upload SSH keys to it before you need it. The Robot firewall is a stateless switch-port filter with a 10-rule limit per direction and requires separate IPv6 activation; it is optional if the OS-level firewall is stable.

### Non-Root Admin User Transition

```bash
useradd -m -s /bin/bash -G sudo <ADMIN_USER>
```

Set a local password, because `sudo` still uses it even when SSH password auth is disabled:

```bash
passwd <ADMIN_USER>
```

```bash
mkdir -p /home/<ADMIN_USER>/.ssh
cp /root/.ssh/authorized_keys /home/<ADMIN_USER>/.ssh/authorized_keys
chown -R <ADMIN_USER>:<ADMIN_USER> /home/<ADMIN_USER>/.ssh
chmod 700 /home/<ADMIN_USER>/.ssh && chmod 600 /home/<ADMIN_USER>/.ssh/authorized_keys
```

Verify in a new session while keeping the root session open:

```bash
ssh <ADMIN_USER>@host
sudo -i
```

Lock down SSH only after verifying the new user works:

```bash
# In /etc/ssh/sshd_config.d/hardening.conf:
# PermitRootLogin no
# AllowUsers <ADMIN_USER>
# X11Forwarding no
# PermitUserRC no
sshd -T | grep -E 'permitrootlogin|allowusers|x11forwarding|permituserrc'
systemctl reload ssh
```

Verify from a third session that root login is rejected.

SSH key-only disables remote password login, but the local password still controls `sudo`, `su`, and console login. Locking the admin password while using `NOPASSWD` sudo means key compromise gives immediate root with no second factor.

### SSH Key Separation

Use different SSH keys for daily admin and break-glass access. The daily key lives on your workstation; the break-glass key stays offline or in a hardware token, never loaded in your SSH agent. If the daily key is compromised, the break-glass key remains separate.

For multi-person teams: one key per person, never shared accounts or keys. Revocation is deleting that person's key and account.

### Docker Group Privilege Escalation

The `docker` group is root-equivalent, because any member can `docker run -v /:/host` to read and write the entire filesystem without `sudo`. Prefer `sudo docker ...` for users who need container access. For untrusted users, use rootless Docker or Podman. When auditing an unknown server, check `getent group docker` for unexpected members.

### Service Privilege Separation

Services that listen on unprivileged ports (> 1024) should run as dedicated system users, not root. If the process is compromised, the attacker inherits only the service user's permissions:

```bash
useradd --system --no-create-home --shell /usr/sbin/nologin <SVC_USER>
chown <SVC_USER>:<SVC_USER> /etc/<service>/<config>
chmod 600 /etc/<service>/<config>
```

In the systemd unit:

```ini
[Service]
User=<SVC_USER>
Group=<SVC_USER>
```

Then `systemctl daemon-reload && systemctl restart <service>`. Verify with `ps -o user,pid,comm -p $(pidof <binary>)`.

Services that need a privileged port (< 1024) can use `AmbientCapabilities=CAP_NET_BIND_SERVICE` instead of running as root.

### Kernel Network Tuning

LXC and OpenVZ containers share the host kernel and cannot modify its parameters. Check first:

```bash
systemd-detect-virt
```

If the result is `lxc` or `openvz`, skip this section. Only `kvm`, `vmware`, `xen`, or `none` (bare metal) support sysctl tuning.

BBR requires kernel ≥ 4.9 and the `tcp_bbr` module. Verify before writing the config:

```bash
modprobe tcp_bbr
sysctl net.ipv4.tcp_available_congestion_control
```

If the output does not contain `bbr`, omit the `tcp_congestion_control` and `default_qdisc` lines.

Baseline for proxy/VPN workloads in `/etc/sysctl.d/99-vps-tuning.conf`:

```ini
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.ip_local_port_range = 20000 65000
net.ipv4.ip_local_reserved_ports = 22,<SERVICE_PORT>
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_syncookies = 1
```

- `fq` + `bbr` — per-flow pacing with bandwidth/RTT-based congestion control, well suited for proxy and VPN egress
- `somaxconn` / `tcp_max_syn_backlog` at 8192 — raises the ceiling from the default 4096; the application's `listen()` backlog must also be adequate
- `ip_local_port_range` 20000–65000 — wider than the default 32768–60999 without encroaching on well-known ports
- `ip_local_reserved_ports` — prevents the kernel from assigning SSH or service ports as ephemeral source ports
- `tcp_mtu_probing` — avoids black holes caused by intermediate devices with mismatched MTU
- `tcp_syncookies` — validates SYN requests with cookies when the queue is full, mitigating SYN floods

Apply with `sysctl -p /etc/sysctl.d/99-vps-tuning.conf`.

After deleting the file, `sysctl --system` reloads all remaining drop-ins but does not restore deleted parameters to kernel defaults — the old values persist in memory until reboot. To fully revert without rebooting, use `sysctl -w <param>=<default>` for each changed parameter.

The following parameters appear in many tuning guides but should not be set without specific benchmarks proving their benefit:

| Parameter | Why not |
|---|---|
| `tcp_fastopen = 3` | The server-side bit requires `setsockopt(TCP_FASTOPEN)` in the application; the sysctl alone has no effect |
| `rmem_max / wmem_max` | TCP autotuning adjusts buffers automatically; blind overrides can reduce throughput |
| `tcp_fin_timeout` | Only affects orphan FIN_WAIT_2 sockets, not general connection recycling |
| `tcp_max_tw_buckets` | The kernel documentation says not to lower it; the default scales with system memory |
| `tcp_tw_reuse` | The default value 2 (loopback only) is correct for most workloads |
| `netdev_max_backlog` | Has minimal impact on virtio NICs typical of VMs |
| `keepalive_*` | Applications manage their own keepalive; system-level changes are usually ignored |

### Troubleshooting

A low `MaxAuthTries` can reject the correct key before it is tried, because SSH agent offers all loaded keys in order. Fix with `IdentitiesOnly yes` in `~/.ssh/config` or `ssh -i` to pin the key.

If `AllowUsers` is set, add new admins to the list before testing login. Diagnosis: `journalctl -u ssh` will show `not allowed because not listed in AllowUsers`.

`debsecan` may pull in exim4 as a dependency. After installing, check `ss -tlnp` — if exim4 binds to `0.0.0.0:25` or `[::]:25`, restrict it to localhost or remove it.

### Useful Debian Tools

- `needrestart` — lists services and kernels that need restart after upgrades; require version >= 3.8
- `debsecan` — cross-references installed packages against known CVEs
- `debian-security-support` — checks whether packages are within active security support
