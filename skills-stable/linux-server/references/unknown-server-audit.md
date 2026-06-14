# Unclear Or Possibly Compromised Server

Use these commands when the server purpose, access paths, ownership, or compromise state is unclear.

Start read-only. Do not upgrade, clean, delete, rotate, restart, or rewrite persistence until evidence is collected and the user chooses a repair plan.

## Contents

- Preparation
- System identification
- Accounts and SSH access
- Network exposure
- Running services
- Persistence
- Patch state
- Logs
- Repair order

## Preparation

Keep the current SSH session open.

Only create the `audit` tmux session when the user approves active collection or
the audit must continue after disconnect.

Runtime impact: creates a detached `tmux` session named `audit` until it is killed or the host reboots.

```bash
tmux new -d -s audit
```

## System Identification

```bash
cat /etc/os-release
uname -a
uptime
hostnamectl
timedatectl
whoami && id
```

## Accounts And SSH Access

```bash
passwd -S root
grep -v 'nologin\|false' /etc/passwd
ls -la /root/.ssh 2>/dev/null
cat /root/.ssh/authorized_keys 2>/dev/null
for d in /home/*/; do echo "=== $d ==="; cat "${d}.ssh/authorized_keys" 2>/dev/null; done
```

Key options can force commands, restrict source IPs, inject environment variables, or create tunnels:

```bash
grep -nE 'command=|from=|environment=|permitopen=|tunnel=|principals=' /root/.ssh/authorized_keys 2>/dev/null
for f in /home/*/.ssh/authorized_keys; do
  echo "=== $f ==="
  grep -nE 'command=|from=|environment=|permitopen=|tunnel=|principals=' "$f" 2>/dev/null
done
```

Read effective SSH config:

```bash
sshd -T | awk '$1 ~ /^(port|listenaddress|permitrootlogin|passwordauthentication|pubkeyauthentication|kbdinteractiveauthentication|allowusers|allowgroups|authenticationmethods|permituserrc|x11forwarding|maxauthtries)$/ { print }'
grep -i '^Match' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null
sshd -T -C user=root,addr=0.0.0.0,host= | awk '$1 ~ /^(permitrootlogin|passwordauthentication|permituserrc)$/ { print }'
ls -la /etc/ssh/sshd_config.d/ 2>/dev/null
```

## Network Exposure

```bash
ss -tlnp
ss -ulnp
ip addr
ip route
ip -6 addr
cat /etc/resolv.conf
```

```bash
nft list ruleset 2>/dev/null
iptables -S 2>/dev/null
ip6tables -S 2>/dev/null
iptables -V
update-alternatives --display iptables 2>/dev/null
```

If the host is in a cloud, OS-level firewall is not the whole boundary. Inspect provider security groups or provider firewall when available.

Provider control panels can bypass OS settings through rescue console, KVM, snapshots, or disk re-imaging. When the user reports compromise, unknown ownership, or unexplained access, verify provider account 2FA, API keys, and rescue-console access paths with the user instead of treating the OS as the full access boundary.

## Running Services

```bash
systemctl list-units --type=service --state=running --no-pager
systemctl list-unit-files --state=enabled --no-pager
ps auxf --sort=-%cpu | head -80
```

Record proxies, tunnels, miners, daemons without a user-confirmed purpose, and unit names that do not match installed packages or known services.

## Persistence

```bash
crontab -l 2>/dev/null
ls -la /etc/cron.d/ /etc/cron.daily/ /etc/cron.hourly/ 2>/dev/null
systemctl list-timers --all --no-pager
ls -la /etc/systemd/system/
```

```bash
for d in /home/*/; do
  echo "=== ${d} ==="
  ls -la "${d}.config/systemd/user/" 2>/dev/null
  ls -la "${d}.ssh/rc" 2>/dev/null
done
ls -la /root/.config/systemd/user/ 2>/dev/null
ls -la /root/.ssh/rc 2>/dev/null
```

```bash
find /usr/bin /usr/sbin /bin /sbin -perm /6000 -type f 2>/dev/null | sort
getcap -r / 2>/dev/null | head -200
```

## Patch State

```bash
ls -la /etc/apt/sources.list.d/
cat /etc/apt/sources.list.d/*.sources 2>/dev/null
cat /etc/apt/sources.list.d/*.list 2>/dev/null
apt-get -s upgrade | head -80
systemctl is-enabled unattended-upgrades 2>/dev/null
systemctl list-timers --no-pager 'apt-daily*'
```

Do not run `apt-get update` in the evidence-collection pass unless the user has approved refreshing package indexes.

## Logs

```bash
journalctl -u ssh --since "24 hours ago" --no-pager | tail -200
last -20
lastb -20 2>/dev/null
journalctl -u ssh --since "7 days ago" --no-pager | grep -E 'Accepted (publickey|password|keyboard-interactive)' | tail -80
last -50
```

Treat login source IPs as benign only when they match known user, provider, VPN, or automation ranges.

## Repair Order

After evidence collection, draft a repair plan in this order. Do not execute delete, disable, rotate, restart, or rewrite actions until the user approves the plan.

1. Access: disable password login, verify key access, remove unknown keys only after preserving evidence.
2. Firewall: default drop, allow only required ports, align rules with listeners.
3. Persistence: disable or remove malicious timers, units, cron, shell hooks.
4. Updates: patch within current release.
5. Afterward: add monitoring, backups, or stronger account policy when the machine needs them.
