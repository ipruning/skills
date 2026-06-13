# Maintenance

Maintenance includes Debian/Ubuntu package updates, unattended upgrades, and reboot checks.

## Contents

- Pre-maintenance
- Refresh package indexes
- Apply same-release updates
- needrestart
- Reboot check
- Post-maintenance
- unattended-upgrades
- Debian security tools

## Pre-Maintenance

```bash
whoami && id && date -Is && uptime && uname -r
df -h / /var /boot 2>/dev/null || df -h
free -h
systemctl --failed --no-pager
ss -tulpen
apt-get -s upgrade | head -80
```

Stop before applying updates if `/`, `/var`, or `/boot` is low on space.

## Refresh Package Indexes

Run only when the user approved refresh, update, upgrade, or maintenance work.

Persistent impact: refreshes apt package indexes under `/var/lib/apt/lists/`; installed packages are not changed.

```bash
apt-get update
apt-get -s upgrade | head -80
```

## Apply Same-Release Updates

Use `apt-get`, not `apt`, in scripts:

Persistent impact: upgrades installed packages within the current distro release; rollback is package-specific and may require snapshots or backups.

```bash
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y \
  -o Dpkg::Options::=--force-confdef \
  -o Dpkg::Options::=--force-confold \
  upgrade
```

Use `full-upgrade` only for same-release dependency changes. Stop and ask before major distro upgrades.

## needrestart

`needrestart` has had local privilege escalation vulnerabilities. Debian and Ubuntu backport fixes to distro-specific versions, so check the distro security tracker rather than comparing only to upstream version numbers.

Read package state before running `needrestart`:

```bash
command -v needrestart >/dev/null 2>&1 && dpkg-query -W needrestart
apt-cache policy needrestart 2>/dev/null
```

Run the scanner only after the installed package comes from the distro or another source the user trusts:

Runtime impact: scans running processes and loaded libraries; no services are restarted with `NEEDRESTART_MODE=l`.

```bash
NEEDRESTART_MODE=l needrestart -r l
```

## Reboot Check

```bash
echo "Running: $(uname -r)"
echo "Installed: $(dpkg -l 'linux-image-*' 2>/dev/null | awk '/^ii.*linux-image-[0-9]/{print $2, $3}' | sort -V | tail -1)"
test -f /var/run/reboot-required && cat /var/run/reboot-required /var/run/reboot-required.pkgs 2>/dev/null
```

## Post-Maintenance

```bash
systemctl --failed --no-pager
ss -tulpen
journalctl -p err..alert -b --no-pager | tail -200
journalctl -u ssh -b --no-pager | tail -100
ls -lt /var/log/apt/history.log* 2>/dev/null | head -5
tail -100 /var/log/apt/history.log
```

## unattended-upgrades

Read state first:

```bash
systemctl is-enabled unattended-upgrades 2>/dev/null
systemctl list-timers --no-pager 'apt-daily*'
ls -lt /var/log/unattended-upgrades/ 2>/dev/null
```

Enable only when the user wants automatic security updates or the machine is maintained without interactive package sessions.

Persistent impact: enabling unattended upgrades changes future package update behavior without an interactive session.

## Debian Security Tools

- `needrestart`: lists services and kernels that need restart after upgrades; verify installed version against the distro security tracker.
- `debsecan`: cross-references installed packages against known CVEs. Installing it can install mail transport dependencies; after installation, check `ss -tlnp` and restrict or remove any newly listening mail service.
- `debian-security-support`: checks whether installed packages remain within active Debian security support.
