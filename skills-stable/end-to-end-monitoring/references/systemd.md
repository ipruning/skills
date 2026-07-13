# systemd Reference

Read this when deploying a service, timer, probe, collector, or long-running process on a Linux host with systemd.

## Choose The Shape

```text
periodic check:
  .service Type=oneshot + .timer

continuous daemon:
  .service with Restart=on-failure

standard host metrics collector:
  OpenTelemetry Collector service
```

Use a timer for probes that should run once per cadence. Use a daemon only when the process must continuously listen, stream, or maintain state.

## Naming

Use stable, grep-able names:

```text
<system>-<purpose>.service
<system>-<purpose>.timer
```

Examples:

```text
acme-orders-probe.service
acme-orders-probe.timer
hostmetrics-logfire-collector.service
```

## Secrets

Do not put tokens in unit files or command-line arguments. Prefer:

```text
/etc/<name>/env        root-owned, chmod 600
systemd credentials   when available and worth the extra setup
platform secret store when running under a platform
```

Use these rules when rotating a secret:

1. Create or receive the new secret on the configuring side.
2. Back up the exact env file being changed in the same root-owned secret directory.
3. Write the new secret into the target store without leaving it in durable logs,
   final reports, shell history, unit files, or other unnecessary surfaces.
4. Preserve owner and mode. Secret backups must stay root-owned and `0600`.
5. Restart or reload only the affected service.
6. Verify runtime state and backend telemetry before deleting the old secret or its backup.

For SSH automation, pass the secret over stdin or a secret manager when that
fits the available transport. Do not let secret-hiding mechanics prevent an
authorized rotation from completing; protect the secrets boundary and verify the
runtime.

## Hardening

For hardened example units, ensure the service user exists or deliberately choose `DynamicUser=yes`. Relax `ProtectHome`, `ProtectSystem`, or add explicit writable paths only when the probe's contract requires it; record that exception in the delivery report.

## Deploy As A Transaction

Updating an enabled timer is a state transition, not a file-copy step. `OnBootSec=` may already be elapsed, and an `OnCalendar=` timer with `Persistent=true` may catch up a missed run as soon as the timer starts. When the protected service and its monitor change together, use this order:

1. Record `UnitFileState` and `ActiveState` separately for the timer and service, the deployed versions, the intended final state, and the exact rollback set.
2. Stage every executable, environment file, and unit outside its live path. Check ownership, mode, checksum, and unit syntax before stopping anything.
3. Stop the timer, then stop any in-flight oneshot service. Verify both are inactive, no start job remains queued, and no old probe process remains. A stop failure aborts the deployment; do not hide it with `|| true`.
4. Publish the staged set atomically or through versioned paths. Avoid a mixed generation of executable, environment, service, and timer files. Run `systemd-analyze verify` on the final unit set, then `systemctl daemon-reload`.
5. Start or restart the protected service and prove its business readiness, expected version, and dependencies. This is only part of the re-arm gate.
6. While the timer is stopped, run the monitor once with blocking `systemctl start`. Record a run id or start timestamp, then verify the expected probe version, `Result`, `ExecMainCode`, `ExecMainStatus`, journal, `ActiveState=inactive`, and backend signal from that run. A periodic oneshot must not use `RemainAfterExit=yes`, or later timer starts become no-ops. The complete re-arm gate is consistent artifacts, valid units, protected-subject readiness, and a correlated successful manual probe.
7. Before arming, prove the timer's effective `Triggers` target, calendar or interval, randomized delay, and next elapse match the contract. If it was already enabled, use `systemctl start`; use `enable --now` only for a fresh or previously disabled timer whose intended final state is enabled. Arming may queue an immediate run, so wait for that job to finish before reading its result. A manual probe does not consume an `OnCalendar=` timer's persistent catch-up; two consecutive runs can be correct. Finish by checking the intended `is-enabled` state, active state, trigger target, and next elapse again.
8. Use an `EXIT` or equivalent failure finalizer in deployment automation. Restore the prior timer only after the complete old set has been rolled back and its readiness gate passes. If files are mixed, the subject is unready, or either probe run fails, use `disable --now` so reboot cannot silently re-arm the timer, and report the monitoring gap explicitly.

For a fresh standalone monitor whose protected subject is already ready, the sequence can be shorter, but the possible immediate first run still applies.

## Verification Commands

Use the target host's actual service names. Verify the oneshot before arming the timer:

```bash
sudo systemd-analyze verify /etc/systemd/system/<name>.service /etc/systemd/system/<name>.timer
sudo systemctl daemon-reload
sudo systemctl start <name>.service
sudo systemctl show <name>.service -p ActiveState -p Result -p ExecMainStatus -p ExecMainCode
sudo journalctl -u <name>.service -n 100 --no-pager
sudo systemctl show <name>.timer -p Triggers -p NextElapseUSecRealtime -p NextElapseUSecMonotonic
sudo systemctl start <name>.timer  # existing enabled timer
sudo systemctl is-enabled <name>.timer
sudo systemctl is-active <name>.timer
sudo systemctl status <name>.timer --no-pager
sudo systemctl status <name>.service --no-pager
```

For a fresh timer whose intended state is enabled, replace the timer `start` above with `systemctl enable --now <name>.timer`. If arming queues an immediate run, wait for the job and re-check the oneshot result instead of reading the previous manual run's result.

For a continuous daemon or collector, verify active state:

```bash
sudo systemctl is-active <name>.service
```

For a `Type=oneshot` probe, successful services usually return to `inactive`. Verify the last run result instead:

```bash
sudo systemctl show <name>.service -p Result -p ExecMainStatus -p ExecMainCode
sudo systemctl is-failed <name>.service
sudo journalctl -u <name>.service -n 100 --no-pager
sudo systemctl list-timers --all --no-pager
```

For a continuous daemon, also verify restart behavior if the contract depends on it.

A collector reload or `SIGHUP` can rebuild internal components without changing the main PID or incrementing systemd's `NRestarts`. Collector self-metrics may reset during that rebuild. Take a fresh post-reload baseline and prove counters increase from it; do not compare absolute self-metric counters across the reload boundary.

Check runtime, not only files:

```bash
systemctl --failed --no-pager
systemctl list-timers --all --no-pager
ss -tulpen
journalctl -u <name>.service --since '<absolute time>' -p warning --no-pager
```

## Timer Policy

Choose timer semantics based on the contract:

```text
OnCalendar=hourly:
  wall-clock cadence, good for hourly checks.

OnUnitActiveSec=...:
  interval after the last run completed.

Persistent=true:
  catch up missed OnCalendar runs after downtime; it has no effect without OnCalendar.

Persistent=false:
  skip missed runs; useful when only current freshness matters.

RandomizedDelaySec=...:
  stagger many hosts or probes.
```

Record the chosen cadence and freshness threshold in the contract.

## Report Boundaries

Say exactly which layer was verified:

```text
local service active:
  systemd can run the producer.

observability backend evidence received:
  telemetry arrived with the expected identity.

alert evaluated:
  the rule ran without errors and matched or did not match as expected.

notification delivered:
  the intended channel received the test alert and the responder confirmed it.
```
