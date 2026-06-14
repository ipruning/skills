---
name: observability-contracts
description: |
  Use when a user needs end-to-end monitoring and alerting ownership for a host,
  service, cron job, crawler, external dependency, data pipeline, or AI workflow.
  Use to define and verify the observability contract from signal production
  through backend ingestion, alerting, notification, response, and runbook. Do
  not use for standalone telemetry queries, dashboard edits, alert CRUD, or
  general Linux operations unless they are part of that contract.
---

# Observability Contracts

Deliver a verified observability contract, not a monitoring stack.

The contract is complete only when each step in this path is designed and verified, or when an unverified step is named:

```text
protected subject -> signal producer -> observability backend -> alert rule -> notification channel -> responder -> runbook
```

## Operating Loop

1. Define the protected subject and the promise.
2. Inspect machine, project, scheduler, service, and observability backend facts.
3. Choose the smallest signal producer that satisfies the promise.
4. Create stable identity before creating credentials or alerts.
5. Configure the producer and secrets boundary.
6. Create freshness alerts and semantic or threshold alerts.
7. Verify signal, observability backend query, alert execution, notification delivery, and responder handoff.
8. Report what is implemented, verified, and still unverified.

## First Move

Ask only the questions that change the design. Do not ask for facts available through local inspection, authenticated tooling, repository files, or current provider docs.

Prefer these questions:

- What is the protected subject, and what counts as success or failure?
- How late can detection happen while still leaving enough time to repair or rerun?
- Who or what will receive the notification, and is that channel allowed to interrupt them?

Pick conservative defaults when missing details do not change the design:

```text
hostmetrics cadence: 30s for a small number of hosts; use 60s when cost or cardinality matters
hostmetrics freshness threshold: 5m without expected data
custom probe freshness: derive from cadence and repair window; do not reuse 5m for hourly jobs
disk threshold: root filesystem >= 90%
notification mode: onset-only
secret storage: Linux/systemd hosts use root-owned env file, chmod 600; otherwise use the platform or deployment secret store
```

## Contract To Maintain

Keep a compact contract while working:

```text
subject:
success signal:
failure signal:
producer:
cadence:
freshness / absence threshold:
severity mapping:
observability backend:
identity:
credential / revocation boundary:
alert rule:
channel:
responder:
runbook:
interruption behavior:
deadline / repair window:
secrets boundary:
verification evidence:
not verified yet:
```

Only fill fields that are actually needed. If a missing field changes the implementation or alert behavior, ask the user. If it does not, pick the simplest reasonable default and state it.

## Tool Use

- Use observability backend MCP tools for read-only telemetry queries, dashboards, channels, alert definitions, and run history when exploring.
- Create or update alerts, dashboards, channels, and credentials only when the user asked to deploy, configure, rotate, repair, or verify that contract.
- Use SSH for host facts, runtime state, systemd status, service logs, file permissions, and config validation.
- Use Chrome or another authenticated UI when MCP cannot complete a required credential action or the user explicitly asks for it, such as creating a named Logfire write token. Do not inspect cookies, local storage, or passwords.
- Use current official docs when provider endpoints, token behavior, collector config, or alert syntax may have changed.
- Keep secrets out of durable or unnecessary surfaces: chat summaries, shell history, process argv, unit files, git, and ordinary user-writable files.

## Design Rules

- Use existing observability primitives: logs, spans, metrics, severity, alert rules, freshness / absence checks, notification channels, and runbooks.
- Human involvement is expressed by severity, channel, responder, interruption behavior, and runbook.
- Use the smallest mechanism that satisfies the contract. Reuse existing monitoring if present.
- For standard host CPU / memory / disk / network metrics, prefer an OpenTelemetry Collector hostmetrics setup over a custom script unless the user asks otherwise.
- For business-specific checks, external dependency checks, crawler checks, or AI workflow checks, attach the probe to the scheduler or runtime that owns the promise. On Linux hosts, a small probe run by systemd timer is usually enough.
- Do not call something an agent unless it observes, decides, and can take multi-step actions. A one-shot program that emits telemetry is a probe, check, or reporter.
- Create stable identity before credentials: project, environment, service name, subject id, host id, monitor id, and token name.
- Use one write credential per revocation boundary. A deployed producer needs a scoped write credential, not a read credential, admin key, or personal API key.
- Treat temporary dev-session credentials as bootstrapping only. Replace them with a named, non-expiring or policy-expiring credential before claiming durable monitoring.
- Always add a freshness alert for any monitor that is meant to protect a promise. It catches host down, collector stopped, revoked credential, DNS/export failure, and network break.
- Do not claim the system is complete until both the signal path and notification path are verified, or explicitly mark what remains unverified.

## Progressive disclosure

Read only the relevant reference files:

- Logfire chosen, token scope, alerts, channels, or backend queries: [`references/logfire.md`](references/logfire.md)
- systemd service, timer, secret file, or runtime verification: [`references/systemd.md`](references/systemd.md)
- host CPU / memory / disk / filesystem / load / network / paging / process-count monitoring with Logfire hostmetrics: [`references/system-host-monitoring/CASE.md`](references/system-host-monitoring/CASE.md)
- custom business probe, binary, crawler check, AI check, cron semantic check, or external dependency check: [`references/custom-probe/CASE.md`](references/custom-probe/CASE.md)

## Delivery report

At the end, separate four things:

```text
Contract:
  the agreed observability contract.

Implemented:
  what was actually deployed or configured.

Verified:
  commands, dashboard evidence, observability backend query results, alert test, and notification receipt.

Not verified / still needs user action:
  anything you could not prove end-to-end.
```

If only the local command succeeded, say that. If telemetry reached the backend but no alert/channel was tested, say that. If notification was sent but the real responder has not confirmed receipt, say that.
