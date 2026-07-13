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

Read effective global and Match-context SSH state with the canonical commands in
[ssh.md](ssh.md). Include `kbdinteractiveauthentication` in both views; a Match
block can restore it even when the global value is disabled.

## Network Exposure

```bash
ss -tulpen
ss -tpuna
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

The service and journal commands below are systemd-only. On another init system, collect the equivalent service/process evidence or report that coverage gap instead of treating command absence as health.

Do not print every command line into an agent transcript: process argv can contain tokens and passwords. Start with executable names and inspect a named suspect through a secret-aware local capture.

```bash
systemctl list-units --type=service --state=running --no-pager
systemctl list-unit-files --state=enabled --no-pager
ps -eo user,pid,ppid,stat,lstart,comm
for proc_exe in /proc/[0-9]*/exe; do
  printf '%s -> %s\n' "$proc_exe" "$(readlink "$proc_exe" 2>/dev/null || true)"
done
```

Record proxies, tunnels, miners, daemons without a user-confirmed purpose, and unit names that do not match installed packages or known services.

## Persistence

```bash
while IFS=: read -r account_name _ account_uid _ _ _ account_shell; do
  if test "$account_uid" -eq 0 || { test "$account_uid" -ge 1000 && test "$account_shell" != /usr/sbin/nologin && test "$account_shell" != /bin/false; }; then
    echo "=== crontab: $account_name ==="
    crontab -u "$account_name" -l 2>/dev/null || true
  fi
done </etc/passwd
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

Read `/etc/os-release` first. Use the matching package manager and security
tracker; the following block is Debian/Ubuntu-only:

```bash
. /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
  *" debian "*|*" ubuntu "*)
    ls -la /etc/apt/sources.list.d/
    find /etc/apt -maxdepth 2 -type f \( -name '*.sources' -o -name '*.list' \) \
      -exec stat -c '%a %U:%G %s %y %n' {} +
    apt-cache policy
    plan_path=$(mktemp)
    if apt-get -s upgrade >"$plan_path"; then
      head -80 "$plan_path"
    else
      echo "apt simulation failed; patch state not verified" >&2
    fi
    rm -f "$plan_path"
    systemctl is-enabled unattended-upgrades 2>/dev/null
    systemctl list-timers --no-pager 'apt-daily*'
    ;;
  *)
    echo "No package audit recipe for ID=${ID:-unknown} ID_LIKE=${ID_LIKE:-unknown}" >&2
    ;;
esac
```

Do not run `apt-get update` in the evidence-collection pass unless the user has approved refreshing package indexes.

## Logs

```bash
ssh_unit=$(systemctl list-unit-files 'ssh.service' 'sshd.service' --no-legend | awk 'NR == 1 { print $1 }')
ssh_log=$(mktemp)
if test -n "$ssh_unit" && journalctl -u "$ssh_unit" --since "7 days ago" --no-pager >"$ssh_log"; then
  tail -200 "$ssh_log"
  grep -E 'Accepted (publickey|password|keyboard-interactive)' "$ssh_log" | tail -80 || true
else
  echo "SSH journal unavailable; authentication evidence not verified" >&2
fi
rm -f "$ssh_log"
last -20
lastb -20 2>/dev/null
last -50
```

Treat login source IPs as benign only when they match known user, provider, VPN, or automation ranges.

## Repair Order

After evidence collection, draft a repair plan in this order. Do not execute delete, disable, rotate, restart, or rewrite actions until the user approves the plan.

1. Access: install and verify a known key from a fresh session, then disable password login; remove unknown keys only after preserving evidence.
2. Firewall: default drop, allow only required ports, align rules with listeners.
3. Persistence: disable or remove malicious timers, units, cron, shell hooks.
4. Updates: patch within current release.
5. Afterward: add monitoring, backups, or stronger account policy when the machine needs them.
