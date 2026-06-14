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
spider2-delist-probe.service
spider2-delist-probe.timer
hostmetrics-logfire-collector.service
```

Avoid `agent` unless the program really has autonomous decision/action behavior.

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
authorized rotation from completing; protect the durable boundary and verify the
runtime.

## Hardening

For hardened example units, ensure the service user exists or deliberately choose `DynamicUser=yes`. Relax `ProtectHome`, `ProtectSystem`, or add explicit writable paths only when the probe's contract requires it; record that exception in the delivery report.

## Verification Commands

Use the target host's actual service names.

```bash
sudo systemd-analyze verify /etc/systemd/system/<name>.service /etc/systemd/system/<name>.timer
sudo systemctl daemon-reload
sudo systemctl enable --now <name>.timer
sudo systemctl start <name>.service
sudo systemctl status <name>.service --no-pager
sudo systemctl status <name>.timer --no-pager
sudo journalctl -u <name>.service -n 100 --no-pager
```

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
  catch up after downtime; useful for required batch jobs.

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
