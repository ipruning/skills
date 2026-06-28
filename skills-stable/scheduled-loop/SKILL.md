---
name: scheduled-loop
description: Create recurring Codex loops for scheduled work, monitors, heartbeat checks, periodic follow-ups, and repeated verification. Use when the user asks to schedule, loop, monitor, wake up, keep checking, periodically verify, or remind Codex to continue work, especially when deciding between a fresh Scheduled Task and a current-thread Scheduled Message.
---

# Scheduled Loop

## Core Decision

First decide whether each run can start fresh or whether the next check needs this thread's current context.

Use a **Scheduled Task** when a fresh run can succeed from the schedule prompt alone:

- The recurring work can be described as a self-contained instruction.
- Required state is in durable files, URLs, tickets, dashboards, APIs, or other retrievable sources.
- The next run does not need this thread's private conversation state, live plan, open browser, or current tool session.

Use a **Scheduled Message** when the next run must continue this thread:

- The check depends on current thread context, active goal state, worker thread IDs, local notes from this conversation, or an ongoing gatekeeping loop.
- The next run should resume a coordination state rather than start a new independent agent.
- Losing the current thread context would materially change what Codex should do.

If either option could work, prefer Scheduled Task and put the needed context in the schedule prompt or a durable note file. Use Scheduled Message only when continuity is part of the job.

## Question Filter

Infer everything possible from the conversation. Ask only missing questions that materially change the workflow:

- What should Codex do each time?
- How often should it run?
- What change is important enough to report?
- When should it stop?
- When should it ask me for input?

Do not ask questions already answered by the user's wording, local goal files, prior notes, URLs, ticket IDs, or obvious defaults. When a safe default is available, state it briefly and proceed.

## Creation Workflow

1. Summarize the loop in one sentence.
2. State the fresh-vs-current-thread decision and why.
3. If required information is missing, ask only the material question(s) from the filter above.
4. Once enough information exists, use the automation tooling to create the scheduled item:
   - Search for and use `automation_update` for reminders, monitors, scheduled tasks, scheduled messages, or heartbeat loops.
   - Create a Scheduled Task for fresh runs.
   - Create a Scheduled Message for current-thread continuation.
5. Include a concise schedule prompt with:
   - The exact task to perform.
   - Sources of truth to read each run.
   - Report threshold.
   - Stop condition.
   - When to ask the user for input.
6. Confirm the automation id, cadence, and what will cause a user-visible report.

## Prompt Shape

For a Scheduled Task, make the prompt self-contained:

```text
Every run, start fresh. Read [sources]. Check [condition]. Report only if [threshold].
Stop when [condition]. Ask the user only if [input condition].
```

For a Scheduled Message, make the prompt continuity-oriented:

```text
Continue this thread's active loop. Re-read [durable state]. Preserve the current gate/goal.
Check [condition]. Report only if [threshold]. Stop when [condition].
Ask the user only if [input condition].
```

## Defaults

Use these defaults only when the user has not specified otherwise and they are low risk:

- Report threshold: report only material state changes, blockers, completion, or failed verification.
- Stop condition: stop when the requested outcome is complete, impossible, or explicitly canceled.
- Ask-for-input condition: ask when Codex cannot proceed without a user secret, approval, account access, product decision, or ambiguous irreversible action.
- Cadence: do not invent a cadence for high-cost or externally noisy work; ask. For lightweight monitoring, suggest a practical cadence based on urgency.

## Final Response

After creation, keep the response short:

- Name the scheduled item.
- Say whether it is a Scheduled Task or Scheduled Message.
- Give the cadence.
- State the report threshold and stop condition.
