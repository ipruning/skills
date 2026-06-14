---
name: linux-server
description: "Operate Debian/Ubuntu Linux servers over SSH. Use for VPS setup, SSH login policy, firewall exposure, swap, same-release package maintenance, audits of servers with unclear ownership or compromise signs, Docker/container port exposure, and proxy/VPN network tuning. Not for macOS."
---

# Linux Server

First identify what the machine is: personal node, shared admin server, unclear server, container host, public app server, maintenance target, or performance-tuning target. Then use only the commands for that machine and task.

## Operating Rules

1. Start with a read-only pass unless the user explicitly asked to configure, deploy, fix, or apply a known change.
2. Before changing SSH, firewall, or networking, keep the current SSH session open. Open a second live session when credentials and network path are available; otherwise schedule a rollback before applying firewall or SSH changes.
3. Verify runtime state, not only config files:
   - SSH: `sshd -T`
   - listeners: `ss -tulpen`
   - firewall: `ufw status verbose`, `nft list ruleset`, `iptables -S`, `ip6tables -S`
   - services: `systemctl is-active <unit>`
4. Change one area at a time: SSH, then firewall, then packages, then services or tuning.
5. If the user asks for a single-owner VPS setup, change only the requested area plus the verified access and port rules needed to keep the host reachable. Do not add compliance controls, non-root migration, SSH algorithm changes, sysctl tuning, fail2ban, or provider-account work unless the server actually has that need or the user asks.
6. Patch within the current distro release only. Major-version upgrades need explicit user direction.
7. Put local overrides in dedicated files: SSH in `/etc/ssh/sshd_config.d/`, sysctl in `/etc/sysctl.d/`, fail2ban in `jail.local`, systemd in unit drop-ins. Edit package-managed defaults only when the service has no override mechanism.

## Identify The Machine

Name the machine type when that choice changes what gets opened, closed, or rewritten.

### Single-Owner VPS

Personal VPS, proxy nodes, Snell/Xray boxes, and single-user web hosts are machines where the user manages root directly.

Keep:

- Allow root login by key: `PermitRootLogin prohibit-password`
- Disable SSH passwords: `PasswordAuthentication no`, `KbdInteractiveAuthentication no`
- Ensure key auth works: `PubkeyAuthentication yes`
- Use `MaxAuthTries 20` for 1Password SSH agent or other multi-key agents
- Open only currently needed or explicitly planned ports
- Do not force a non-root admin, `AllowUsers`, fail2ban, SSH algorithm lists, or sysctl tuning by default

For Snell VPS setup or repair, use [references/snell-vps.md](references/snell-vps.md). Use [references/ssh.md](references/ssh.md) for SSH changes and [references/firewall.md](references/firewall.md) for firewall changes.

### Team Admin Server

A team admin server has more than one human administrator, and access must be revoked per person.

Keep:

- Create one user per human
- Use `sudo` rather than shared root after admin access is verified
- Disable root SSH only after a replacement admin path works from a fresh session
- Add `AllowUsers` / `AllowGroups` only after all intended users are included and tested

Use [references/ssh.md](references/ssh.md).

### Unclear Or Possibly Compromised Server

Here, ownership, purpose, access paths, or compromise state is unclear.

First:

- Collect evidence before repair
- Do not upgrade, clean, rotate, delete, restart, or rewrite persistence until evidence is collected
- Identify access, listeners, firewall, persistence, logs, patch state, and services without a user-confirmed purpose before remediation

Use [references/unknown-server-audit.md](references/unknown-server-audit.md).

### Container Host

Docker, containerd, Kubernetes, x-ui, nginx-proxy-manager, and similar tools can publish ports outside the ordinary service list.

Before changing rules:

- Map every public port to its process, container, and firewall path
- Remember Docker-published ports can bypass UFW input rules
- Do not add broad route rules unless a real container forwarding problem is confirmed

Use [references/containers.md](references/containers.md) and [references/firewall.md](references/firewall.md).

### Public Web Or App Server

HTTP(S), app ports, reverse proxies, and dashboards may be intentionally public.

Keep:

- Keep `80/tcp` and `443/tcp` only when a listener or planned service needs them
- Treat dashboards and admin panels as management ports; bind to localhost or restrict source only when the service has no public clients or the user confirms the allowed source range
- Preserve Docker or reverse-proxy ports that are actively serving traffic unless the user asks to remove them

Use [references/firewall.md](references/firewall.md) and [references/containers.md](references/containers.md) when containers are involved.

### Maintenance Window

Package maintenance changes installed software or the schedule that updates it.

First:

- Use `apt-get`, not `apt`, in noninteractive commands
- Stay within the current distro release
- Check disk, failed units, listeners, apt simulation, and reboot need

Use [references/maintenance.md](references/maintenance.md).

### Performance Or Network Tuning

Performance tuning belongs to proxy/VPN performance, BBR, sysctl, latency, throughput, or kernel/network parameter work.

First:

- Measure or identify the performance goal before writing sysctls
- Do not add copied tuning lists to an ordinary SSH or firewall change
- Leave SSH algorithms unchanged unless the user asked for crypto policy work

Use [references/performance-tuning.md](references/performance-tuning.md).

## First Read-Only Commands

When no narrower command set fits, start here:

```bash
whoami && id && hostname && date -Is && uptime && uname -a
df -h / /var /boot 2>/dev/null || df -h
free -h
systemctl --failed --no-pager
ss -tulpen
sshd -T | awk '$1 ~ /^(port|listenaddress|permitrootlogin|passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|maxauthtries|maxsessions|logingracetime|allowusers|allowgroups|authenticationmethods|permituserrc|x11forwarding)$/ { print }'
if command -v ufw >/dev/null 2>&1; then ufw status verbose; fi
if command -v nft >/dev/null 2>&1; then nft list ruleset 2>/dev/null; fi
iptables -S 2>/dev/null
ip6tables -S 2>/dev/null
```

## Changing Files

When the user has asked to apply changes:

1. Summarize the planned change in one or two sentences.
2. Back up the specific file being changed.
3. Validate syntax before reload where available: `sshd -t`, `nft -c -f`, `systemd-analyze verify`.
4. Reload instead of restart when the service supports reload and syntax validation has passed.
5. Open a fresh SSH connection after SSH/firewall changes.
6. Re-read runtime state and report the exact effective settings.

## Command Files

- SSH access, 1Password agent friendliness, root policy, non-root admin migration: [references/ssh.md](references/ssh.md)
- UFW/nftables, port/process alignment, rollback, listener exposure: [references/firewall.md](references/firewall.md)
- Package updates, unattended-upgrades, needrestart, reboot checks: [references/maintenance.md](references/maintenance.md)
- Swap inventory and resizing: [references/swap.md](references/swap.md)
- Snell VPS minimal setup: [references/snell-vps.md](references/snell-vps.md)
- Unclear-server or compromise-sign read-only audit: [references/unknown-server-audit.md](references/unknown-server-audit.md)
- Docker, container firewalls, Docker group risk, service users: [references/containers.md](references/containers.md)
- BBR/sysctl/network tuning and crypto-algorithm caution: [references/performance-tuning.md](references/performance-tuning.md)
