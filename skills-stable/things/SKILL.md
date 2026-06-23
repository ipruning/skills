---
name: things
description: "Read-only local macOS Things queries and summaries when the user asks about their Things tasks, Today list, Inbox, projects, tags, or task search."
---

# Things

## Core Rule

Use `scripts/things_query.py` through `uv run --script` for local Things reads. This skill is read-only. If the user asks to modify Things, say this skill does not support writes and ask whether to switch to a separate approved write mechanism.

Set `SKILL_DIR` to the directory containing this `SKILL.md`, then prefer exact local evidence over memory:

```bash
SKILL_DIR=/path/to/things
uv run --script "$SKILL_DIR/scripts/things_query.py" --collection today --format json
```

## Workflow

1. Confirm the local date when the user says "today", "tomorrow", "yesterday", or Chinese equivalents.

```bash
date '+%Y-%m-%d %H:%M:%S %Z %z'
```

2. Query the smallest useful collection.

```bash
uv run --script "$SKILL_DIR/scripts/things_query.py" --collection today --format json
uv run --script "$SKILL_DIR/scripts/things_query.py" --collection inbox --format json
uv run --script "$SKILL_DIR/scripts/things_query.py" --collection todos --search "visa" --format json
```

3. Do not dump notes, UUIDs, or every task unless the user asks. Titles are acceptable when the user asks to see tasks. Use counts or high-level summaries for exploratory checks.

4. State boundaries plainly:

- `things.py` reads the Things SQLite database in read-only mode.
- Things data may reflect the last opened/synced Things database state.
- `today()` follows Things Today semantics, not only `start_date == <today>`.
- `today()` predicts scheduled and overdue tasks, but may not include repeating tasks that Things has not generated yet.

Read `references/things-semantics.md` when date semantics, missing recurring tasks, database paths, or permission errors matter.

## Script Usage

Read script options when the request needs filters beyond these examples:

```bash
uv run --script "$SKILL_DIR/scripts/things_query.py" --help
uv run --script "$SKILL_DIR/scripts/things_query.py" --collection today --limit 20 --format markdown
uv run --script "$SKILL_DIR/scripts/things_query.py" --collection todos --search "Korea" --include-notes --format json
```

Collections:

- `today`, `inbox`, `anytime`, `upcoming`, `someday`, `deadlines`
- `todos`, `projects`, `areas`, `tags`
- `completed`, `canceled`, `logbook`, `trash`

Use `--db-path` only when the default Things database path fails or the user supplies an exported database path.

## Response Style

For Chinese user prompts, answer in Chinese and use the local absolute date from `date` for relative-day results, for example: "按本机 <YYYY-MM-DD> <TZ> 的 Today 列表...".

Keep personal task output tight:

- Start with count and collection/date.
- List titles in Things order when asked to "show" or "see" tasks.
- Include project, heading, deadline, reminder, or tags only when present or relevant.
- Mention if the result is a Things Today view rather than an exact date filter.
