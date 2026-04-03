---
name: linux-server
description: "Linux server security audit, hardening, and maintenance. Triggers: VPS, remote Linux host, SSH hardening, firewall rules, Debian/Ubuntu patching, unknown server audit, fail2ban, unattended-upgrades. Not for macOS."
metadata:
  version: "4"
---

# VPS Security & Maintenance

Use on Debian/Ubuntu servers for audit, hardening, and maintenance. Use `apt-get`, not `apt`. Apply steps use noninteractive dpkg flags.

## Safety Rules

1. **Fallback path.** Before changing SSH, firewall, or networking, keep console/KVM or a second live session open. Use `tmux` for long sessions.

2. **Audit first.** First round is read-only. Change one surface at a time: SSH → firewall → anti-brute-force → updates → sysctl. Verify each step.

3. **Verify runtime state.** `sshd -T` for SSH config; `sshd -T -C user=...,addr=...` for Match-aware config; `nft list ruleset` + `iptables -S` + `ip6tables -S` for firewall; `ss -tlnup` for listeners; `systemctl status` for services.

4. **Patch within the current release only.** Major-version upgrades need human approval.

5. **Keep audit and apply separate.** Audit uses read-only commands. Package installs, file writes, service reloads, and `nft -f` belong in apply and need human approval.

## 1. Routine Maintenance

### 1.1 Pre-Maintenance

Identity, uptime, and kernel:

```bash
whoami && id && date && uptime && uname -r
```

Disk, memory, and CPU. Stop if `/`, `/var`, or `/boot` is low on space:

```bash
df -h && free -h && top -bn1 -o %CPU | head -20
```

Failed services and listening ports:

```bash
systemctl --failed --no-pager
ss -tlnup
```

SSH effective config and Match blocks:

```bash
sshd -T | grep -E 'permitrootlogin|passwordauthentication|kbdinteractiveauthentication|x11forwarding|port|allowusers|allowgroups|permituserrc'
grep -i '^Match' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null
sshd -T -C user=root,addr=0.0.0.0,host= | grep -E 'permitrootlogin|passwordauthentication'
```

Current firewall rules:

```bash
nft list ruleset 2>/dev/null | head -50
```

nftables persistence — check enabled, active, and config parses:

```bash
systemctl is-enabled nftables
systemctl is-active nftables
nft -c -f /etc/nftables.conf
```

Compare listeners to allow rules. Remove allow rules for ports with no listener:

```bash
echo "=== Listening ===" && ss -tlnp | awk 'NR>1{print $4}' | sort -u
echo "=== Allowed ===" && nft list ruleset 2>/dev/null | grep -oP 'dport \K\S+' | sort -u
```

fail2ban:

```bash
systemctl is-active fail2ban && fail2ban-client status sshd
```

Preview upgrades:

```bash
apt-get update
apt-get -s upgrade | head -50
```

### 1.2 During Maintenance

Apply upgrades non-interactively:

```bash
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y \
  -o Dpkg::Options::=--force-confdef \
  -o Dpkg::Options::=--force-confold \
  upgrade
```

Use `full-upgrade` only for same-release dependency changes. Stop and escalate for major-version upgrades.

If `needrestart` is installed, verify version first. Versions below 3.8 have local privilege escalation (CVE-2024-48990). Use list-only mode:

```bash
needrestart --version
NEEDRESTART_MODE=l needrestart -r l
```

Compare running vs installed kernel. If they differ, schedule a reboot:

```bash
echo "Running: $(uname -r)" && echo "Installed: $(dpkg -l "linux-image-$(dpkg --print-architecture)" 2>/dev/null | awk '/^ii/{print $3}')"
```

### 1.3 Post-Maintenance

Check for broken services:

```bash
systemctl --failed --no-pager
ss -tlnup
```

Recent error logs:

```bash
journalctl -p err..alert -b --no-pager | tail -200
journalctl -u ssh -b --no-pager | tail -100
```

Upgrade logs:

```bash
ls -lt /var/log/apt/history.log* 2>/dev/null | head -5
tail -100 /var/log/apt/history.log
ls -lt /var/log/unattended-upgrades/ 2>/dev/null
```

Automatic updates still enabled:

```bash
systemctl is-enabled unattended-upgrades
systemctl list-timers --no-pager 'apt-daily*'
```

## 2. Unknown Server Audit

Establish exposure, access, persistence, and patch status before changing anything.

### 2.1 Preparation

Start a detached `tmux` session. Keep a second SSH session or console open:

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

Root account password status:

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

Search authorized_keys for options (`command=`, `from=`, `environment=`, `permitopen=`, `tunnel=`, `principals=`):

```bash
grep -nE 'command=|from=|environment=|permitopen=|tunnel=|principals=' /root/.ssh/authorized_keys 2>/dev/null
for f in /home/*/.ssh/authorized_keys; do
  echo "=== $f ===" && grep -nE 'command=|from=|environment=|permitopen=|tunnel=|principals=' "$f" 2>/dev/null
done
```

### 2.4 SSH Effective Configuration

Check effective SSH config and Match overrides:

```bash
sshd -T | grep -E 'port|listenaddress|permitrootlogin|passwordauthentication|pubkeyauthentication|kbdinteractiveauthentication|x11forwarding|allowusers|allowgroups|authenticationmethods|permituserrc'

grep -i '^Match' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null

sshd -T -C user=root,addr=0.0.0.0,host= | grep -E 'permitrootlogin|passwordauthentication|permituserrc'

ls -la /etc/ssh/sshd_config.d/ 2>/dev/null
```

Inspect `PermitRootLogin`, `PasswordAuthentication`, `PermitUserRC`, and any `Match` blocks that relax security per user or address.

### 2.5 Network Exposure

Listening ports, TCP and UDP:

```bash
ss -tlnp
ss -ulnp
```

IPv4, IPv6, routes, and resolver config:

```bash
ip addr && ip route && ip -6 addr && cat /etc/resolv.conf
```

Firewall rules — check nftables, IPv4, and IPv6 separately:

```bash
nft list ruleset 2>/dev/null
iptables -S 2>/dev/null
ip6tables -S 2>/dev/null
```

Identify the active iptables backend. Use one firewall manager. Do not mix nftables with competing managers (ufw, firewalld, iptables-persistent):

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

Cron jobs:

```bash
crontab -l 2>/dev/null
ls -la /etc/cron.d/ /etc/cron.daily/ /etc/cron.hourly/ 2>/dev/null
```

Systemd timers:

```bash
systemctl list-timers --all --no-pager
```

Custom systemd units:

```bash
ls -la /etc/systemd/system/
```

User-level systemd units:

```bash
for d in /home/*/; do
  echo "=== ${d} ===" && ls -la "${d}.config/systemd/user/" 2>/dev/null
done
ls -la /root/.config/systemd/user/ 2>/dev/null
```

Login-time persistence and SSH rc scripts:

```bash
for d in /home/*/; do
  echo "=== ${d} ===" && ls -la "${d}.ssh/rc" 2>/dev/null
done
ls -la /root/.ssh/rc 2>/dev/null
```

SUID binaries and capabilities:

```bash
find /usr/bin /usr/sbin /bin /sbin -perm /6000 -type f 2>/dev/null | sort
getcap -r / 2>/dev/null | head -200
```

### 2.8 Patch Status

Package sources:

```bash
ls -la /etc/apt/sources.list.d/
cat /etc/apt/sources.list.d/*.sources 2>/dev/null
cat /etc/apt/sources.list.d/*.list 2>/dev/null
```

Upgradable packages:

```bash
apt-get update
apt-get -s upgrade | head -50
```

Automatic security updates:

```bash
systemctl is-enabled unattended-upgrades 2>/dev/null
systemctl list-timers --no-pager 'apt-daily*'
```

### 2.9 Log Analysis

Failed and successful logins from the last 24 hours:

```bash
journalctl -u ssh --since "24 hours ago" --no-pager | tail -200
last -20
lastb -20 2>/dev/null
```

Successful logins from the last 7 days. Confirm every source IP is expected:

```bash
journalctl -u ssh --since "7 days ago" --no-pager | grep -E 'Accepted (publickey|password|keyboard-interactive)' | tail -50
last -50
```

Modification times on authorized_keys and SSH config:

```bash
stat /root/.ssh/authorized_keys 2>/dev/null
for f in /home/*/.ssh/authorized_keys; do stat "$f" 2>/dev/null; done
stat /etc/ssh/sshd_config
ls -la /etc/ssh/sshd_config.d/ 2>/dev/null
```

### 2.10 Remediation Priority

Fix in this order:

1. **SSH** — `PasswordAuthentication no`, `PermitRootLogin prohibit-password` (then `no` after non-root admin works), `X11Forwarding no`, `PermitUserRC no`, restrict via `AllowUsers`
2. **Firewall** — default drop, allow only required ports, align allow rules with actual listeners, verify nftables persistence
3. **Anti-brute-force** — fail2ban or CrowdSec. Optional if SSH is key-only and source-restricted
4. **Updates** — enable unattended-upgrades, verify apt-daily timers fire, confirm Allowed-Origins covers security updates, require needrestart >= 3.8
5. **Hardening** — sysctl tuning, AppArmor, centralized logging, monitoring, backup

## Reference

### SSH Hardening

Prefer these SSH settings:

- `PasswordAuthentication no`
- `PermitRootLogin prohibit-password` — switch to `no` after non-root admin is verified
- `X11Forwarding no` — Debian defaults to `yes`; disable on headless servers
- `PermitUserRC no` — Debian defaults to `yes`; `~/.ssh/rc` runs on login
- `AllowUsers` / `AllowGroups` — supports `user@host` and CIDR for source restriction
- Verify with `sshd -T` and `sshd -T -C user=root,addr=...`
- Audit Match blocks — they can override any of the above

**Debian default pitfall:** Debian's openssh-server defaults are designed for usability, not hardened servers. After overriding via `/etc/ssh/sshd_config.d/`, always verify with `sshd -T`.

### Firewall Modification with Rollback

Save current rules and schedule automatic rollback before changing firewall rules. If connectivity breaks, old rules restore after 2 minutes:

```bash
nft list ruleset > /tmp/nft-backup.conf
nft -c -f /path/to/new-rules.conf
systemd-run --on-active=120 --unit=nft-rollback nft -f /tmp/nft-backup.conf
nft -f /path/to/new-rules.conf
```

If connectivity is good, cancel the rollback timer:

```bash
systemctl stop nft-rollback.timer 2>/dev/null
```

### Firewall Rule Alignment

Match allow rules to listeners:

- **Listening but not allowed** — a service opened a port the firewall does not cover
- **Allowed but not listening** — close allowed ports with no listener unless they are planned

Workflow:

1. Run `ss -tlnp` and `ss -ulnp` to discover listeners
2. Extract allowed ports from `nft list ruleset` (`grep -oP 'dport \K\S+'`)
3. Flag mismatches in both directions
4. If containers are present, inspect `forward` rules for bridge interfaces
5. Write rules based on actual + planned ports only
6. Dry-run with `nft -c -f <ruleset>` before applying
7. Verify with `nft list ruleset` after applying

### nftables Forward Chain and Containers

If nftables has `inet filter forward` with `policy drop`, Docker/Podman traffic also needs allow rules there. Docker's iptables rules do not bypass nftables `inet` hooks — they are independent chains evaluated in parallel.

Diagnosis:

```bash
nft list chain inet filter forward 2>/dev/null
docker run --rm alpine ping -c1 1.1.1.1
```

If the chain has `policy drop` and no container interface rules, that confirms the cause.

Fix — add explicit forward rules for container bridges:

```bash
nft add rule inet filter forward iifname "br-*" accept
nft add rule inet filter forward oifname "br-*" accept
nft add rule inet filter forward iifname "docker0" accept
nft add rule inet filter forward oifname "docker0" accept
```

Persist in `/etc/nftables.conf` and verify with `nft -c -f /etc/nftables.conf`. On container hosts, inspect `forward` rules as well as `input` rules.

### Hosting Provider Control Plane Security

OS-level hardening is insufficient if the provider's control panel is compromised. An attacker can bypass all OS defenses via rescue console, KVM, or disk re-imaging.

For any provider:

- Enable 2FA on the provider account
- Restrict and rotate API keys
- Know how to reach rescue console/KVM before you need it

**Hetzner-specific:**

- Configure Login-OTP / Support-OTP for anti-social-engineering
- Rescue System: PXE-booted Debian live environment in RAM; upload SSH keys to it before you need it
- Robot firewall (optional): stateless switch-port filter, 10-rule limit per direction. IPv6 filtering requires separate activation. If the OS-level nftables firewall is stable, the Robot firewall is optional

### Non-Root Admin User Transition

After initial root-based bootstrap:

Create admin user with sudo:

```bash
useradd -m -s /bin/bash -G sudo <ADMIN_USER>
```

Set a local password. `sudo` still uses it even when SSH password auth is disabled:

```bash
passwd <ADMIN_USER>
```

Copy SSH public key:

```bash
mkdir -p /home/<ADMIN_USER>/.ssh
cp /root/.ssh/authorized_keys /home/<ADMIN_USER>/.ssh/authorized_keys
chown -R <ADMIN_USER>:<ADMIN_USER> /home/<ADMIN_USER>/.ssh
chmod 700 /home/<ADMIN_USER>/.ssh && chmod 600 /home/<ADMIN_USER>/.ssh/authorized_keys
```

Verify in a new session. Keep the root session open:

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

**Password pitfall:** SSH key-only disables remote password login. The local password still controls `sudo`, `su`, and console login. Locking the admin password while using `NOPASSWD` sudo means key compromise = immediate root with no second factor.

### SSH Key Separation

Use different SSH keys for daily admin and break-glass access:

- **Daily admin key** — used for `ssh <ADMIN_USER>@host`, carried on your workstation
- **Break-glass key** — stored offline or in a hardware token, used only for emergency recovery. Never loaded in your SSH agent day-to-day

If the daily key is compromised, the break-glass key remains separate. For multi-person teams: one key per person, never shared accounts or keys. Revocation = delete that person's key and account.

### Docker Group Privilege Escalation

The `docker` group is root-equivalent. Any member can `docker run -v /:/host` to read/write the entire filesystem without `sudo`.

- Do not add users to the `docker` group by default
- Prefer `sudo docker ...` for users who need container access
- For untrusted users, use rootless Docker or Podman
- When auditing an unknown server, check `getent group docker` for unexpected members

### Troubleshooting

**MaxAuthTries + SSH agent:** if low `MaxAuthTries` rejects the correct key before it is tried, use `IdentitiesOnly yes` in `~/.ssh/config` or `ssh -i` to pin the key.

**AllowUsers lockout:** if `AllowUsers` is set, add new admins there before testing login. Diagnose with `journalctl -u ssh` (look for `not allowed because not listed in AllowUsers`).

**debsecan installs an MTA:** `debsecan` may pull in exim4. After installing, verify its listening address with `ss -tlnp` — if it binds to `0.0.0.0:25` or `[::]:25`, lock it down.

### Useful Debian Tools

- **needrestart** — lists services and kernels that need restart after upgrades. Require version >= 3.8
- **debsecan** — cross-references installed packages against known CVEs
- **debian-security-support** — checks whether packages are within active security support
