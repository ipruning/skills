# Whole-Host Health Audit

Use this audit when the host purpose, ownership, and expected workloads are known. Use [unknown-server-audit.md](unknown-server-audit.md) instead when compromise or ownership is unclear.

The unit, timer, and journal blocks are systemd-only. On another init system, collect equivalent evidence or list that section as not verified; do not interpret missing systemd commands as a healthy result.

## Evidence Boundary

Record the audit start and end time, boot ID, current boot age, and one canonical log window. Run the audit blocks in one shell, or export the same fixed `AUDIT_START` and `LOG_SINCE` into every separate SSH invocation; shell-local variables do not cross connections. A healthy result applies only to the observed host and time window. State provider firewall, snapshots, backups, DNS control, and external monitoring as separate coverage boundaries unless they were verified directly.

Do not infer whole-host health from `systemctl --failed`, container status, or one HTTP response.

## System And Scheduled Work

```bash
AUDIT_START=${AUDIT_START:-$(date -Is)}
LOG_SINCE=${LOG_SINCE:-'24 hours ago'}
export AUDIT_START LOG_SINCE
printf 'audit_start=%s log_since=%s\n' "$AUDIT_START" "$LOG_SINCE"
cat /proc/sys/kernel/random/boot_id
uptime
systemctl is-system-running
systemctl --failed --no-pager
systemctl list-timers --all --no-pager
journalctl -p warning --since "$LOG_SINCE" --no-pager
```

For important services and timers, read `Result`, `ExecMainStatus`, restart counts, and the recent unit journal. A green timer row proves only that it is scheduled. Verify the service result produced by its latest run.

Validate mount declarations separately:

```bash
findmnt --verify --verbose --tab-file /etc/fstab
findmnt
swapon --show
```

## Configuration Drift And Persistence

Known ownership does not make every persistent file expected. Inventory custom units, cron,
user-level services, shell/SSH hooks, and superseded backup files. Compare each item with the
current workload or an explicit rollback need.

```bash
systemctl list-unit-files --state=enabled --no-pager
find /etc/systemd/system -maxdepth 3 \( -type f -o -type l \) -print
ls -la /etc/cron.d/ /etc/cron.daily/ /etc/cron.hourly/ 2>/dev/null
find /etc -xdev -type f \( -name '*.bak*' -o -name '*~' \) -print
for home_dir in /home/*/ /root/; do
  ls -la "${home_dir}.config/systemd/user/" "${home_dir}.ssh/rc" 2>/dev/null
done
```

On Debian/Ubuntu, inspect package drift without assuming every conffile change is malicious:

```bash
dpkg -V
if command -v debsums >/dev/null 2>&1; then debsums -s; fi
```

For shared CI or service accounts, inventory credential-bearing config by path, owner, mode,
mtime, and marker count without printing values. Persistent Git URL rewrites, registry tokens,
package-manager credentials, and runner-global HOME state need a named producer and lifecycle.
Removing one file is not a fix when a workflow or setup action writes it back.

```bash
find <SHARED_HOME> -xdev -maxdepth 3 -type f \
  \( -name '.gitconfig' -o -name '.npmrc' -o -name 'settings.xml' -o -name 'config.json' \) \
  -print
for config_path in <DISCOVERED_CREDENTIAL_CONFIGS>; do
  stat -c '%a %U:%G %s %y %n' "$config_path"
  marker_count=$(grep -Eic 'token|password|_auth|authorization|secret' "$config_path" || true)
  printf 'credential-marker-count=%s %s\n' "$marker_count" "$config_path"
done
```

Before deleting an unexpected-file candidate, record its producer, consumers, rollback purpose,
owner, mode, and mtime. Remove only named candidates. Re-run syntax and workload checks, then
check whether automation recreated the path; deletion without a recurrence test is incomplete.

Discover local backup jobs and their latest result. A timer or uploaded artifact proves neither
restorability nor provider-side coverage; verify a recent restore or report that boundary as
unverified.

## Storage And Filesystem Consistency

```bash
df -hT
df -ih
if lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS >/dev/null 2>&1; then
  lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS
else
  lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT
fi
cat /proc/mdstat 2>/dev/null
for md_path in /sys/block/md*/md; do
  test -d "$md_path" || continue
  printf '%s degraded=%s mismatch_cnt=%s sync_action=%s\n' \
    "${md_path%/md}" \
    "$(cat "$md_path/degraded")" \
    "$(cat "$md_path/mismatch_cnt")" \
    "$(cat "$md_path/sync_action")"
done
```

RAID `[UU]` proves both members are present. It does not prove mirrored data agrees. Read `mismatch_cnt` and scrub history. Do not start `repair` until disk health, the intended source of truth, workload impact, and rollback or restore path are known.

Use the installed storage tool for each device:

```bash
if command -v smartctl >/dev/null 2>&1; then
  smartctl -H /dev/<SMART_DEVICE>
  smartctl -l selftest /dev/<SMART_DEVICE>
else
  echo "smartctl unavailable; SMART not verified" >&2
fi
if command -v nvme >/dev/null 2>&1; then
  nvme smart-log /dev/<NVME_CONTROLLER>
  nvme self-test-log /dev/<NVME_CONTROLLER>
else
  echo "nvme unavailable; NVMe health not verified" >&2
fi
```

Missing SMART or NVMe tooling is a coverage gap, not evidence that disks are healthy. A passing
health summary with no self-test history is also incomplete evidence. Starting a short or
extended device self-test is active maintenance; obtain approval and account for workload impact.

`mismatch_cnt` is not durable evidence across array reassembly or reboot. When an earlier audit
recorded mismatches, a post-reboot zero does not close the finding. Run a read-only RAID `check`
in an approved maintenance window and read the resulting count. Do not start `repair` without a
known source of truth and restore path.

## Capacity And Temporary Storage

Read RAM, swap, filesystem usage, inode usage, and every tmpfs. For a growing temporary path, compare four facts: current bytes, creation rate over a recent window, cleanup age, and whether active processes still reference the files.

A cleanup age longer than the time-to-fill is a failure even when current usage is below the alert threshold. Preserve active job handoff files; change retention only after identifying their producer and consumer contract.

## Access And Exposure

Map every public listener through the host firewall, container publishing rules, and provider firewall when available. Audit successful SSH authentication sources and key fingerprints as well as failures and bans. Repeated accepted sessions can be expected forwarding or automation, but the key restrictions, source range, owner, and expiry must all be explicit.

Use [ssh.md](ssh.md) for effective Match-context SSH state and [firewall.md](firewall.md) for listener-to-rule mapping. On container hosts, include [containers.md](containers.md). At minimum retain these results:

```bash
: "${LOG_SINCE:?export the canonical audit log boundary}"
ss -H -tulpen | sort -k5,5
ss -H -tpuna
ssh_unit=$(systemctl list-unit-files 'ssh.service' 'sshd.service' --no-legend | awk 'NR == 1 { print $1 }')
ssh_log=$(mktemp)
if test -n "$ssh_unit" && journalctl -u "$ssh_unit" --since "$LOG_SINCE" --no-pager >"$ssh_log"; then
  grep -E 'Accepted (publickey|password|keyboard-interactive)' "$ssh_log" | tail -100 || true
else
  echo "SSH journal unavailable; accepted-login evidence not verified" >&2
fi
rm -f "$ssh_log"
```

If provider firewall or SSH key ownership is unavailable, put it in the not-verified group.

## Workloads And End-To-End Routes

For each workload, check service state, restart count, healthcheck, recent errors, log rotation, and resource placement. Test both the internal health endpoint and the configured public route, including TLS expiry. A reverse proxy's root `404` is not a failed application healthcheck when the service is routed by host or path.

Discover runtime evidence instead of reporting only declared configuration:

```bash
: "${LOG_SINCE:?export the canonical audit log boundary}"
systemctl --no-pager --type=service --state=running
systemctl show <UNIT> -p ActiveState -p SubState -p Result -p ExecMainStatus -p NRestarts -p ControlGroup
workload_log=$(mktemp)
chmod 600 "$workload_log"
if journalctl -u <UNIT> --since "$LOG_SINCE" --no-pager >"$workload_log"; then
  printf 'workload-log lines=%s error-markers=%s secret-markers=%s path=%s\n' \
    "$(wc -l <"$workload_log")" \
    "$(grep -Eic 'error|fatal|panic|exception' "$workload_log" || true)" \
    "$(grep -Eic 'authorization|bearer|token|password|secret|connection[_ -]?string' "$workload_log" || true)" \
    "$workload_log"
else
  echo "workload journal unavailable; not verified" >&2
fi
```

Do not print raw workload captures into an agent transcript. Inspect named suspect events locally, redact values before quoting, and remove the capture after the audit artifact is complete.

For each public TLS route, record the exact host/path tested, response, certificate expiry, and whether DNS and provider routing were verified from outside the host.

On mixed CI and production Docker hosts, treat membership in the `docker` group as root-equivalent. Read actual cgroup placement from `systemctl show ... -p ControlGroup`, `/proc/<PID>/cgroup`, and `/sys/fs/cgroup`; config names, comments, and declared slices do not prove runtime isolation. A daemon-wide Docker cgroup parent also applies to production containers unless each workload overrides it.

## Log Interpretation

Check the current boot and a recent wall-clock window for OOM kills, I/O errors, filesystem errors, hardware faults, service crash loops, and repeated OverlayFS warnings. Count events and align timestamps with jobs, deploys, reboots, and maintenance. Internet scanner `404` noise is not a compromise finding without an authentication success, unexpected process, persistence, or other supporting evidence.

## Report Shape

Record the end of the evidence window before reporting:

```bash
: "${AUDIT_START:?export the audit start from the first block}"
: "${LOG_SINCE:?export the canonical audit log boundary}"
AUDIT_END=$(date -Is)
printf 'audit_start=%s audit_end=%s log_since=%s\n' "$AUDIT_START" "$AUDIT_END" "$LOG_SINCE"
```

Return four explicit groups:

1. Verified healthy in the observed window.
2. Fixed and re-verified.
3. Requires a maintenance window or architecture change.
4. Not verified because the evidence source was unavailable.

Never collapse the fourth group into a healthy conclusion.
