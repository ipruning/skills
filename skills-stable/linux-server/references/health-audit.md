# Whole-Host Health Audit

Use this audit when the host purpose, ownership, and expected workloads are known. Use [unknown-server-audit.md](unknown-server-audit.md) instead when compromise or ownership is unclear.

## Evidence Boundary

Record the audit start and end time, boot ID, current boot age, and log window. A healthy result applies only to the observed host and time window. State provider firewall, snapshots, backups, DNS control, and external monitoring as separate coverage boundaries unless they were verified directly.

Do not infer whole-host health from `systemctl --failed`, container status, or one HTTP response.

## System And Scheduled Work

```bash
date -Is
cat /proc/sys/kernel/random/boot_id
uptime
systemctl is-system-running
systemctl --failed --no-pager
systemctl list-timers --all --no-pager
journalctl -p warning..alert -b --no-pager
```

For important services and timers, read `Result`, `ExecMainStatus`, restart counts, and the recent unit journal. A green timer row proves only that it is scheduled. Verify the service result produced by its latest run.

Validate mount declarations separately:

```bash
findmnt --verify --verbose --tab-file /etc/fstab
findmnt
swapon --show
```

## Storage And Filesystem Consistency

```bash
df -hT
df -ih
lsblk -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS
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
command -v smartctl nvme || true
smartctl -H /dev/<DEVICE>
nvme smart-log /dev/<CONTROLLER>
```

Missing SMART or NVMe tooling is a coverage gap, not evidence that disks are healthy.

## Capacity And Temporary Storage

Read RAM, swap, filesystem usage, inode usage, and every tmpfs. For a growing temporary path, compare four facts: current bytes, creation rate over a recent window, cleanup age, and whether active processes still reference the files.

A cleanup age longer than the time-to-fill is a failure even when current usage is below the alert threshold. Preserve active job handoff files; change retention only after identifying their producer and consumer contract.

## Access And Exposure

Map every public listener through the host firewall, container publishing rules, and provider firewall when available. Audit successful SSH authentication sources and key fingerprints as well as failures and bans. Repeated accepted sessions can be expected forwarding or automation, but the key restrictions, source range, owner, and expiry must all be explicit.

## Workloads And End-To-End Routes

For each workload, check service state, restart count, healthcheck, recent errors, log rotation, and resource placement. Test both the internal health endpoint and the configured public route, including TLS expiry. A reverse proxy's root `404` is not a failed application healthcheck when the service is routed by host or path.

On mixed CI and production Docker hosts, treat membership in the `docker` group as root-equivalent. Read actual cgroup placement from `systemctl show ... -p ControlGroup`, `/proc/<PID>/cgroup`, and `/sys/fs/cgroup`; config names, comments, and declared slices do not prove runtime isolation. A daemon-wide Docker cgroup parent also applies to production containers unless each workload overrides it.

## Log Interpretation

Check the current boot and a recent wall-clock window for OOM kills, I/O errors, filesystem errors, hardware faults, service crash loops, and repeated OverlayFS warnings. Count events and align timestamps with jobs, deploys, reboots, and maintenance. Internet scanner `404` noise is not a compromise finding without an authentication success, unexpected process, persistence, or other supporting evidence.

## Report Shape

Return four explicit groups:

1. Verified healthy in the observed window.
2. Fixed and re-verified.
3. Requires a maintenance window or architecture change.
4. Not verified because the evidence source was unavailable.

Never collapse the fourth group into a healthy conclusion.
