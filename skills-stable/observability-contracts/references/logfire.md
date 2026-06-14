# Logfire Reference

Read this only when the user has selected Logfire or is evaluating it.

## Role

Logfire is the observability backend and alerting surface. It is not the contract by itself. The contract is the user-facing promise: what is monitored, how stale the signal may become, which severity triggers which channel, and who responds.

## Project And Region

Confirm the project that will receive data before creating alerts. Alerts must live in the same project as the telemetry they query.

Confirm the OTLP endpoint from current docs or a working setup. The endpoint must match the project and write-token region. Do not keep using an endpoint that fails DNS or export checks, and do not hard-code a region in copyable templates.

## Identity

Create identity before token and alerts. Use stable values in all telemetry and alert queries:

```text
service.namespace=<org-or-system>
service.name=<logical-producer>
service.instance.id=<producer>-<stable-instance-id>
host.name=<stable-os-hostname>          # for hosts
host.id=<machine-id-or-cloud-instance>  # for hosts
subject.id=<stable-domain-subject>      # for non-host subjects
deployment.environment.name=<production|staging|development|test>
monitor.id=<producer>/<subject-or-host>
```

Use `deployment.environment.name` as the canonical OpenTelemetry resource attribute for environment identity. In Logfire SQL, prefer `otel_resource_attributes->>'deployment.environment.name'` unless a metric-shape probe proves that a flat convenience column is populated for the records you are querying.

Example for one host monitor:

```text
service.namespace=jihuanshe
service.name=hostmetrics
service.instance.id=hostmetrics-462d20d08ed34e57b817df6ed7d2423d
host.name=debian-16gb-hil-1
host.id=462d20d08ed34e57b817df6ed7d2423d
deployment.environment.name=production
monitor.id=hostmetrics/debian-16gb-hil-1
```

## Write Token SOP

- A deployed machine or probe needs a Logfire write token, not an admin key.
- Create one write token per revoke boundary. For one host, name it like `<project>/<service.name>/<host.name>` or `<project>/<monitor.id>`.
- Use a temporary dev-session token only for bootstrapping. Replace it before calling the monitor durable.
- Prefer no expiration for infrastructure monitors unless the user has a rotation system. Expiring tokens need an alert and runbook for rotation.
- If MCP cannot list, rename, create, or revoke write tokens, use the authenticated Logfire UI through Chrome or the official API with the needed scope before falling back to a temporary token or reporting the task blocked.
- Confirm the target host can accept the token into its root-owned secret store before creating a one-time visible token.
- If a token was named wrong, create a new token, update the producer, verify fresh telemetry, then revoke or delete the old token.
- Put the write token on the target host through a root-owned env file, systemd credential, platform secret, or equivalent secret store.
- Use separate tokens when monitors need different revoke boundaries; sharing one dedicated host token is acceptable only when the lifecycle and access boundary are the same.
- Record how to revoke the token.

When the user authorized token creation, an agent may read, copy, paste, and transiently pass the one-time token through Chrome and SSH to finish the deployment. Protect the durable boundary: do not commit the token, leave it in shell history, store it in unit files or config YAML, place it in ordinary user-writable files, or repeat it in the final report.

After installing a one-time token, finish the credential UI path: click Done or otherwise leave the reveal screen, then close or finalize the Chrome tab. Do not leave a one-time token visible in the browser after deployment.

## Signal Shape

For custom probes, emit one structured span/log per run with stable attributes:

```text
service.name
host.name or subject.id
monitor.id
deployment.environment.name
status: ok | warn | error | fatal
checked_at
reason
evidence summary
```

For host metrics, prefer the OpenTelemetry Collector hostmetrics receiver. For app or probe telemetry, use the Logfire SDK or standard OpenTelemetry OTLP export.

## Alert Path

Use Logfire alerts to encode the contract. Typical alert classes:

```text
freshness / absence:
  no expected heartbeat or check result within the agreed window.

threshold:
  metric or query result crosses a limit.

semantic failure:
  check result emits warn / error / fatal.
```

Prefer onset-only notification, such as `starts_having_matches`, when repeated notifications would create noise. Use change-based notification only when recovery messages are part of the contract.

Before claiming a channel verified, confirm the destination can consume Logfire's alert payload. A webhook URL alone does not prove delivery semantics. If Logfire sends a Slack-format payload to Feishu, Discord, enterprise chat, PagerDuty, or a custom webhook receiver, add an adapter or bridge and verify the translated notification end to end. In this contract, `responder` means the person or service that takes the response action, not the payload receiver.

Before creating or updating an alert:

- Inspect metric shape when using metrics: `metric_type`, `is_monotonic`, `aggregation_temporality`, value columns, and resource identity.
- Query the backend for the exact resource identity that actually arrived, then generate alert SQL from those values. Intended names can differ from stored `service_instance_id` when host detectors or cloned machine ids are involved.
- Validate SQL over the same effective window.
- Use exact resource filters, especially `service.namespace`, `service.name`, `service.instance.id`, `monitor.id`, and `deployment.environment.name`.
- Avoid relying on SQL aliases in `GROUP BY`; repeat the expression when the query engine requires it.
- Include `LIMIT`, even for aggregate alerts.

## Verification Checklist

Do not stop at "the program exited 0". Verify in order:

1. A real span/log/metric reached Logfire.
2. The record has the expected service, host or subject identity, `monitor.id`, and `deployment.environment.name`.
3. The dashboard or query can find the signal over the intended time window.
4. The alert rule exists and matches the intended freshness, threshold, or severity condition.
5. The alert has run at least once without query errors.
6. The intended alert rule, not only a generic channel test, produces a safe match and reaches the intended channel. If you cannot safely trigger the same rule, mark notification-path verification as incomplete.
7. The real responder or user confirms the notification was received and matches the intended interruption level.

If any step is impossible with available access, mark it under `Not verified` in the final delivery report.

## Do not overbuild

Do not design a separate incident protocol when Logfire severity, alert rule, channel, and runbook are enough. Do not add an AI loop to the deployed monitor unless the user explicitly wants diagnosis or repair behavior inside the runtime.
