---
name: observability-contracts
description: |
  Use when a user wants to make a host, service, cron job, crawler, external dependency, data pipeline, or AI workflow observable and alertable. Use to define and verify an end-to-end monitoring contract covering the protected subject, signal producer, observability backend evidence, alert, notification channel, responder, runbook, credential scope, freshness, and evidence. Do not use for standalone telemetry queries, dashboard edits, alert CRUD, or general Linux operations unless they are part of that contract.
---

# Observability Contracts

Deliver a verified operating contract, not a monitoring stack.

A delivery is complete only when this path is designed and verified, or the unverified step is named:

```text
protected subject -> signal producer -> observability backend evidence -> alert rule -> notification channel -> responder -> runbook
```

## Operating Loop

1. Define the protected subject and the promise.
2. Discover machine, project, scheduler, service, and backend facts with available tools.
3. Choose the smallest signal producer that satisfies the promise.
4. Create stable identity before creating credentials or alerts.
5. Configure the producer and secret boundary.
6. Create freshness and semantic or threshold alerts.
7. Verify signal, backend query, alert execution, notification delivery, and responder handoff.
8. Report what is implemented, verified, and still unverified.

## First Move

Ask only the questions that change the design. Do not ask for facts you can inspect with SSH, shell, MCP, browser, CLI, repository files, or provider docs.

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
secret storage: root-owned env file, chmod 600
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
backend:
identity:
credential / revoke boundary:
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

- Use backend MCP tools for read-only telemetry queries, dashboards, channels, alert definitions, and run history when exploring.
- Create or update alerts, dashboards, channels, and credentials only when the user asked to deploy, configure, rotate, repair, or verify that contract.
- Use SSH for host facts, runtime state, systemd status, service logs, file permissions, and config validation.
- Use Chrome or another authenticated UI when MCP cannot complete a required credential action or the user explicitly asks for it, such as creating a named Logfire write token. Do not inspect cookies, local storage, or passwords.
- Use current official docs when provider endpoints, token behavior, collector config, or alert syntax may have changed.
- Keep secrets out of durable or unnecessary surfaces: chat summaries, shell history, process argv, unit files, git, and ordinary user-writable files.

## Design Rules

- Use existing observability primitives: logs, spans, metrics, severity, alert rules, freshness / absence checks, notification channels, and runbooks.
- Do not invent a custom `NEED_HUMAN` protocol. Human involvement is expressed by severity, channel, responder, interruption behavior, and runbook.
- Use the smallest mechanism that satisfies the contract. Reuse existing monitoring if present.
- For standard host CPU / memory / disk / network metrics, prefer an OpenTelemetry Collector hostmetrics setup over a custom script unless the user asks otherwise.
- For business-specific checks, external dependency checks, crawler checks, or AI workflow checks, a small probe run by systemd timer is usually enough.
- Do not call something an agent unless it observes, decides, and can take multi-step actions. A one-shot program that emits telemetry is a probe, check, or reporter.
- Create stable identity before credentials: project, environment, service name, subject id, host id, monitor id, and token name.
- Use one write token per revoke boundary. A deployed producer needs a write token, not a read token, admin key, or personal API key.
- Treat temporary dev-session tokens as bootstrapping only. Replace them with a named, non-expiring or policy-expiring token before claiming durable monitoring.
- Always add a freshness alert for any monitor that is meant to protect a promise. It catches host down, collector stopped, revoked token, DNS/export failure, and network break.
- Do not claim the system is complete until both the signal path and notification path are verified, or explicitly mark what remains unverified.

## Progressive disclosure

Read only the relevant reference files:

- Logfire chosen, token scope, alerts, channels, or backend queries: [`references/logfire.md`](references/logfire.md)
- systemd service, timer, secret file, or runtime verification: [`references/systemd.md`](references/systemd.md)
- host CPU / memory / disk / filesystem / load / network / paging / process-count monitoring with Logfire hostmetrics: [`references/system-host-monitoring/CASE.md`](references/system-host-monitoring/CASE.md)
- custom business probe, binary, crawler check, AI check, cron semantic check, or external dependency check: [`references/custom-probe/CASE.md`](references/custom-probe/CASE.md)

The skill provides design intent, not a frozen copy of every vendor instruction.

## Delivery report

At the end, separate four things:

```text
Contract:
  the agreed operating contract.

Implemented:
  what was actually deployed or configured.

Verified:
  commands, dashboard evidence, backend query results, alert test, and notification receipt.

Not verified / still needs user action:
  anything you could not prove end-to-end.
```

If only the local command succeeded, say that. If telemetry reached the backend but no alert/channel was tested, say that. If notification was sent but the real responder has not confirmed receipt, say that.
