# Custom Probe or Binary

Use this when the user needs to monitor a business condition rather than generic host metrics: crawler output, external website state, cron completion, data freshness, AI workflow result, or a domain-specific invariant.

## Default implementation

A probe is a small program that runs once, emits one structured telemetry record, exits, and is scheduled by systemd timer or an existing scheduler.

The probe may be a Bun/TypeScript binary, Python script, Go binary, Rust binary, or any other deployable artifact. Choose based on the repo and host constraints. Do not make runtime language choice the center of the design.

Prefer a custom probe when hostmetrics cannot answer the question. Examples:

- a systemd timer completed and produced fresh data.
- a crawler found the expected external state.
- a queue is draining.
- a business API returns a valid semantic result.
- an AI workflow produced a bounded verdict.

## Identity

Use stable resource attributes as the canonical backend identity:

```text
service.namespace=<org-or-system>
service.name=<system>-probe
service.instance.id=<probe>-<host-or-worker-id>
monitor.id=<system>/<subject>/<check>
subject.id=<domain-subject-id>
deployment.environment.name=<production|staging|development|test>
```

Create a dedicated write token when the probe has a different revocation boundary from hostmetrics or app telemetry.

Use one source of truth for identity. The probe should read identity from environment or platform metadata, set the dotted OpenTelemetry resource attributes above, and only mirror those values into the event body for human readability. Alert filters should use the resource attributes, not body mirrors, unless the backend cannot query resource attributes.

Choose one export mode before deployment:

```text
Logfire SDK mode:
  use the SDK's LOGFIRE_* environment variables and configure missing resource attributes in the probe startup path.

Generic OTLP mode:
  use standard OTEL_EXPORTER_OTLP_* variables, including endpoint and authorization headers.
```

Do not mix the two modes in one default env file unless the probe code explicitly bridges those settings.

## Probe Output

Emit one structured span/log per run:

```json
{
  "schema_version": "1",
  "run_id": "<stable-or-random-run-id>",
  "monitor_id": "<body mirror of monitor.id>",
  "subject_id": "<body mirror of subject.id>",
  "environment": "<body mirror of deployment.environment.name>",
  "status": "ok|warn|error|fatal",
  "checked_at": "<iso8601>",
  "reason": "<short human-readable reason>",
  "evidence": {
    "summary": "<minimal evidence>",
    "url_or_trace": null,
    "raw_artifact_path": null
  }
}
```

Keep the probe deterministic where possible. If it uses AI, the AI should produce a structured verdict and the probe should still emit a bounded result.

## Severity mapping

Let the user define what each severity means for this subject. As a default:

```text
ok:
  expected state.

warn:
  worth reviewing, not interruptive.

error:
  contract may be violated unless handled in the repair window.

fatal:
  the protected promise cannot be met without immediate attention or an approved automatic action.
```

Map both record attributes and alert behavior to this severity. For example, `warn` may be dashboard-only, while `error` and `fatal` notify.

## Failure Modes

Do not rely only on semantic failure records. A probe can fail before emitting telemetry. Use both:

```text
semantic alert:
  status in ('error', 'fatal') or a domain-specific bad result.

freshness alert:
  no probe record for monitor.id within the allowed window.
  start the window at 2x the probe cadence; cap it at cadence + repair window.
  a cap below 2x cadence means the cadence is too slow for the promise:
  shorten the cadence or declare the contract unsatisfiable at that cadence.
```

If the probe exits nonzero after emitting an error record, systemd can show local failure. The backend alert is still the source of notification truth.

## systemd templates

- [`templates/probe.service`](templates/probe.service)
- [`templates/probe.timer`](templates/probe.timer)
- [`templates/probe.env.example`](templates/probe.env.example)
- [`templates/probe-event-schema.example.json`](templates/probe-event-schema.example.json)

## Verification

1. Run the probe manually and inspect exit status and local logs.
2. Verify the telemetry record arrived in the backend with correct attributes.
3. Verify the semantic alert matches a `status` or domain-condition failure.
4. Verify the freshness alert matches when the expected record is absent.
5. Trigger a safe test failure if possible.
6. Walk the alert-to-responder steps of the verification checklist in [`logfire.md`](logfire.md), or the selected backend's equivalent.

A probe that runs locally but has no backend record is not delivered. A probe with backend records but no alert/channel test is only a signal path, not a verified notification system.
