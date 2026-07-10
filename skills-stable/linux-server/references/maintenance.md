# Maintenance

Maintenance includes Debian/Ubuntu package updates, unattended upgrades, and reboot checks.

## Contents

- Pre-maintenance
- Refresh package indexes
- Apply same-release updates
- needrestart
- Reboot check
- Workload drain
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
plan_path=$(mktemp)
trap 'rm -f "$plan_path"' EXIT
apt-get -s upgrade >"$plan_path"
cat "$plan_path"
```

Stop before applying updates if `/`, `/var`, or `/boot` is low on space.

When the upgrade can restart production, container runtime, queue, or runner services, complete
the Workload Drain gate before applying packages, not only before rebooting.

## Refresh Package Indexes

Run only when the user approved refresh, update, upgrade, or maintenance work.

Persistent impact: refreshes apt package indexes under `/var/lib/apt/lists/`; installed packages are not changed.

```bash
apt-get update
plan_path=$(mktemp)
trap 'rm -f "$plan_path"' EXIT
apt-get -s upgrade >"$plan_path"
cat "$plan_path"
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

## Workload Drain

Before rebooting a CI, queue, or batch host, distinguish an idle service from an idle job queue.
Stop accepting work, let active jobs finish, then stop the workers. Confirm both the control plane
and host process state.

The control-plane action is platform-specific; use the runner or queue manager's real drain
procedure rather than inferring availability from systemd alone. Gate production separately:
verify container/service restart policy, state durability, and public-route recovery requirements.
An idle runner queue does not prove that production is ready to reboot.

For GitHub Actions self-hosted runners, load `github-actions-runners` for registration, busy state,
unit mapping, and control-plane verification.

Stopping an enabled systemd service does not keep it stopped across reboot. When post-boot checks
must finish before work resumes, record the current enable state, disable the units before reboot,
then restore the recorded state and start them only after health verification. Do not kill active
jobs merely to shorten the window.

## Approved Reboot

Record the pre-reboot boot ID and prove an out-of-band recovery path before rebooting a remote
host. A successful `systemctl reboot` return only means the request was accepted.

```bash
cat /proc/sys/kernel/random/boot_id
systemctl reboot
```

Reconnect with fresh TCP connections until SSH returns or the declared timeout expires. Prove a
new boot ID before running post-maintenance checks. If the host misses the timeout, inspect the
provider console or rescue path; do not issue repeated blind reboots. After reconnecting, include
the previous boot's errors when diagnosing startup delay:

```bash
cat /proc/sys/kernel/random/boot_id
journalctl -b -1 -p err..alert --no-pager
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

Before restoring workers, repeat the System, Storage, Access, Workloads, and End-To-End Routes
sections of [health-audit.md](health-audit.md). Prove the boot ID changed, the intended kernel is
running, mounts and RAID returned, production routes are healthy, and the recorded worker enable
states were restored. A green systemd summary alone is not post-maintenance verification.

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
