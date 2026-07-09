# System Host Monitoring With Logfire

Use this when the user wants CPU, memory, disk, filesystem, load, network, paging, or process-count history for a VPS, VM, or bare-metal Linux host, and Logfire is the selected observability backend.

## Default implementation

For standard host metrics, prefer the OpenTelemetry Collector hostmetrics receiver sending to Logfire. It avoids custom scripts and does not require instrumenting an application.

Use a custom binary only when the user wants business-specific checks, non-standard host facts, repair logic, or a constrained deployment where Collector is not acceptable.

Hostmetrics does not prove that business timers, crawlers, databases, proxy services, or external dependencies are healthy. Add custom probes for those contracts.

## Cadence And Cost

Choose the collection interval from the monthly bill, not from habit:

```text
monthly datapoints ~= hosts x 520M / interval_seconds
520M = ~200 datapoints per scrape x 2.59M seconds per month
```

- Default 60s (~8.6M/host/month). For fleets of >=5 hosts, or any backend that bills per datapoint or record, use 300s (~1.7M/host/month). Host-level semantics such as host down, disk filling, and service dead survive 300s granularity.
- Price the estimate against the backend's rate before deploying and state it in the delivery report. Treat the formula as a floor: real fleets run above it in proportion to their device, mount, and interface counts.
- Freshness thresholds couple to cadence: use >=3x the collection interval (60s -> 3m, 300s -> 15m). Below 3x the alert races the scrape cycle and flaps.
- The alert evaluator's scan window must cover the freshness threshold plus at least one collection interval and ingestion slack. For a 300s cadence and 15m freshness threshold, use a 30m scan window. Never make the scan window shorter than the SQL freshness threshold when the query uses `MAX(...) IS NULL`: an empty scan then fires at the scan-window boundary instead of the stated freshness threshold.
- When changing cadence on an already-monitored fleet, widen every freshness alert first, then roll the collector interval, then watch one full alert cycle for false fires.
- Backend UIs may have their own fixed staleness badge (for example the Logfire Hosts panel marks a host stale after ~5 minutes without data). At 300s that badge is cosmetic; the alert threshold, not the badge, defines the contract.

## Identity And Token

Before creating a token or alert, decide:

```text
project:
region / OTLP endpoint:
deployment.environment.name:
host.name:
host.id:
service.namespace:
service.name: hostmetrics
service.instance.id: hostmetrics-<host.id>
monitor.id: hostmetrics/<host.name>
write token name: <project>/hostmetrics/<host.name>
revoke owner / path:
```

Use `/etc/machine-id` or cloud instance id for `host.id`. Use OS hostname for `host.name` only when it is stable and meaningful.

When deploying more than one host, compare `/etc/machine-id` values before finalizing identity. Cloned VPS images can reuse the same machine id. If two protected hosts share it, do not use that value for `host.id` or `service.instance.id`. Use a stable hostname, provider instance id, or IP-derived id and record why.

## Deployment SOP

1. Read host facts: OS, hostname, machine id, disk, memory, failed units, listeners, existing monitoring, and existing timers.
2. Create or confirm a dedicated Logfire write token after naming the host identity and confirming that the target host can write its root-owned secret. Do not create a one-time visible token until it can be installed, and do not use a temporary MCP dev-session token for durable monitoring.
3. Store the token in a root-owned env file or systemd credential. Keep it out of config YAML, unit files, shell history, final reports, and unnecessary command output.
4. Install or confirm `otelcol-contrib`.
5. Configure hostmetrics with CPU, memory, load, disk, filesystem, network, paging, and aggregate process scrapers.
6. Configure resource attributes through environment or a resource processor.
7. Validate collector config on the target host.
8. Restart the collector and verify systemd state and recent logs.
9. Query Logfire for fresh metrics with exact identity filters.
10. Create at least one freshness alert and any agreed threshold alerts.
11. Verify alert run history and notification delivery, or mark notification delivery unverified.
12. After the new signal path is verified, delete temporary or superseded write tokens, remove deployment-only sudoers or elevated access, stop temporary transfer/listener processes, remove temporary firewall rules, and delete secret backups that contain obsolete tokens unless the runbook deliberately keeps them.

## Collector Notes

A minimal hostmetrics config should include stable resource attributes and avoid high-cardinality per-process metrics unless explicitly needed.

Prefer aggregate process counts over per-PID process metrics for the first version. Per-PID metrics can create many time series on busy hosts.

Example file: [`templates/otel-collector-hostmetrics.example.yaml`](templates/otel-collector-hostmetrics.example.yaml)

Use current docs and the target collector binary as the source of truth for component names. Always run the collector's own validation command before restart.

`otelcol-contrib` release packages can be large enough to expose weak VPS routes. If `scp` or a one-shot `curl` is unreliable, switch to a resumable download such as `aria2c -c`. Keep the official checksum file with the package and require `sha256sum -c` before installing. Do not install a partially transferred package.

## Standard Alerts

Before writing threshold SQL, inspect the metric shape for the target collector and Logfire project:

```sql
SELECT metric_name,
       metric_type,
       attributes,
       otel_resource_attributes,
       MAX(recorded_timestamp) AS last_seen
FROM metrics
WHERE metric_name IN ('system.cpu.utilization', 'system.filesystem.utilization')
  AND service_name = 'hostmetrics'
GROUP BY metric_name, metric_type, attributes, otel_resource_attributes
LIMIT 20
```

Use the discovered attribute keys in alert SQL. For filesystem mountpoints, common keys include `mountpoint` and `system.filesystem.mountpoint`; do not assume one without checking.

After the first metrics arrive, query the real `service_instance_id`, `host.name`, and `monitor.id` from Logfire and use those exact values in alert SQL. Do not assume the value from the intended identity plan is what the backend stored, especially when a resource detector or machine-id-based `service.instance.id` is involved.

Create a freshness alert for every durable host monitor:

```sql
SELECT '<monitor.id>' AS monitor_id,
       '<service.instance.id>' AS service_instance_id,
       MAX(recorded_timestamp) AS last_seen
FROM metrics
WHERE service_namespace = '<service.namespace>'
  AND service_name = 'hostmetrics'
  AND service_instance_id = '<service.instance.id>'
  AND metric_name = 'system.cpu.utilization'
  AND otel_resource_attributes->>'host.name' = '<host.name>'
  AND otel_resource_attributes->>'monitor.id' = '<monitor.id>'
  AND otel_resource_attributes->>'deployment.environment.name' = '<deployment.environment.name>'
HAVING MAX(recorded_timestamp) IS NULL OR MAX(recorded_timestamp) < now() - interval '<freshness-threshold, >=3x collection interval>'
LIMIT 10
```

Create a root filesystem threshold alert when storage matters:

```sql
SELECT otel_resource_attributes->>'monitor.id' AS monitor_id,
       service_instance_id,
       otel_resource_attributes->>'host.name' AS host_name,
       attributes->>'<mountpoint-attribute-key>' AS mountpoint,
       MAX(<value-column-from-metric-shape>) AS utilization,
       MAX(recorded_timestamp) AS last_seen
FROM metrics
WHERE service_namespace = '<service.namespace>'
  AND service_name = 'hostmetrics'
  AND service_instance_id = '<service.instance.id>'
  AND metric_name = 'system.filesystem.utilization'
  AND otel_resource_attributes->>'host.name' = '<host.name>'
  AND otel_resource_attributes->>'monitor.id' = '<monitor.id>'
  AND otel_resource_attributes->>'deployment.environment.name' = '<deployment.environment.name>'
  AND attributes->>'<mountpoint-attribute-key>' = '/'
GROUP BY otel_resource_attributes->>'monitor.id', service_instance_id, otel_resource_attributes->>'host.name', attributes->>'<mountpoint-attribute-key>'
HAVING MAX(<value-column-from-metric-shape>) >= 0.90
LIMIT 10
```

Use `starts_having_matches` / onset-only notification by default.

## Fleet-Wide Stale Alert Triage

When several independent hosts become stale in the same minute, test the shared path before treating them as separate host failures:

1. Query `MAX(recorded_timestamp)` per monitor over a window longer than the freshness threshold and calculate the observed gaps.
2. Inspect alert run history, query errors, duplicates, and the exact server-side scan window. Do not infer the effective window from the SQL alone.
3. SSH to a representative host and verify collector state, exporter errors, queue health, and recent logs.
4. Fan out to every host only when backend evidence or the representative host points to producer-side failure.

If stored metrics remain on cadence while many alerts fire together, report a backend query/evaluator visibility incident rather than a fleet-wide token or host outage.

## Verification

A host monitoring delivery is only fully verified when:

1. Collector service is running on the target host.
2. Metrics appear in Logfire with the expected host identity.
3. CPU / memory / disk / network are visible in dashboard or query.
4. If freshness alert is part of the contract, the absence rule exists.
5. The alert has evaluated without errors after creation or update.
6. If notification is part of the contract, the intended alert rule produced a safe match and the real responder confirmed receipt. A generic channel test alone is not enough.

If only metrics appear but alert/channel is not verified, report "host metrics signal path verified; notification path not verified".
