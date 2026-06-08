---
name: agent-friendly-cli-audit
description: |
  Use when judging whether a CLI is usable by agents, scripts, or automation.
  Load when the task calls for safe runtime probes and source evidence about
  command discovery, raw or protocol-native API access, stdout/stderr
  separation, non-interactive execution, errors, auth, or workspace context.
metadata:
  short-description: Audit CLI usability for AI agents from runtime and source evidence
  version: "2.2.0"
---

# Agent-Friendly CLI Audit

## Rules

- Treat the target repository as read-only unless the user explicitly asks for changes.
- Inspect runtime behavior and source code. If the CLI cannot run, report the exact blocker and mark the audit as source-only.
- Treat docs and README claims as leads. Use live help, safe commands, source code, or tests as evidence.
- Mock-server tests are test evidence, not runtime evidence. Use them to verify CLI boundary behavior when live external APIs are unavailable.
- Do not run mutating commands unless the command is documented as dry-run, the target is a fixture or disposable sandbox, or the user explicitly approved the mutation.
- Mark production writes, billing actions, messages, deletes, force pushes, and remote deployments as persistent or irreversible in the report.
- For each runtime probe, record command, exit code, stdout/stderr summary, and mode: TTY, non-TTY, CI, piped, or silent.
- Treat stdout and stderr as separate contracts: stdout is for the requested data; stderr is for auxiliary diagnostics, progress, prompts, trace, and recovery hints.

## Audit Model

Judge the CLI by five contracts. Use these names for contract findings:

- Command discovery and intent: user goals map to stable commands, such as login, clone, start, view, merge, deploy, status, or comment, and help output supports progressive drill-down by namespace.
- Protocol-native escape hatch: long-tail API operations can use the upstream protocol directly, such as REST path plus method, GraphQL query plus variables, or JSON-RPC method plus params.
- Output and context contract: stdout carries parseable requested data, stderr carries auxiliary context, and field selection, paging, and filtering keep only useful state in the next context.
- Non-interactive contract: prompts, auth, setup, and workspace selection have scriptable paths in TTY, non-TTY, and CI modes.
- Error and recovery contract: validation, auth, API, domain, and workspace failures preserve failure exit codes, explain likely causes, and provide actionable next steps.

Source and test signals support these contracts. Treat them as separate scoring or maintainability findings only when the user asks for a score, comparison, or maintainability review.

## Workflow

1. Find the executable and safety boundary.
   - Check `README`, `Makefile`, package manifests, release scripts, `cmd/`, `bin/`, and installed binaries.
   - Run `--version` and top-level help when the command is read-only.
   - Record any missing binary, dependency, credential, or build step.

2. Map the command surface.
   - Start from top-level help and drill into representative nested help until the command tree shape and namespace boundaries are clear.
   - Count or sample command groups when the surface is large.
   - Check whether each help page is exhaustive for its current namespace and gives a clear next drill-down path.
   - Look for aliases, extensions, plugins, shell completions, examples, and common flag vocabulary.

3. Inspect protocol-native escape hatches.
   - Search for commands named `api`, `request`, `schema`, `graphql`, `rest`, `rpc`, `query`, or similar.
   - Check whether official API docs can be written as commands without a separate CLI mapping table.
   - For REST, GraphQL, or JSON-RPC, look for the protocol's own shape: path and method, query and variables, or method and params.
   - Check whether auth, host/workspace context, pagination, and output handling stay shared with normal commands.

4. Probe the output and context contract.
   - Compare default output with structured output for one read-only command.
   - Capture stdout and stderr separately for representative default and structured-output commands.
   - If structured output is documented, verify stdout alone can be consumed by the documented parser or downstream tool; diagnostics stay on stderr.
   - Check field limiting through CLI flags, templates, jq-like filters, query selectors, or protocol-native field selection.
   - Check stdout vs stderr separation, paging, color, TTY/non-TTY differences, and default limits.

5. Probe non-interactive and error contracts.
   - Probe representative failure paths such as unknown command, invalid flag, missing argument, and invalid value.
   - Capture real exit codes without losing them through a pipe.
   - Check whether default errors provide the likely cause and next command, and whether documented verbose/debug modes expand redacted request or response details.
   - Test prompt suppression only through documented flags or env vars such as `CI`, `NO_COLOR`, `NO_INPUT`, `--yes`, `--force`, or `--dry-run`.

6. Read source architecture.
   - Find command registration, option parsing, run-function boundaries, output/exporter code, API clients, query builders, auth/context resolution, prompt handling, error handling, and CLI-level tests.

## Runtime Probes

Use these as probe shapes, not a mandatory checklist. Do not invent flags; confirm every flag in help before using it.

```bash
<cli> --help
<cli> help
<cli> --version
<cli> <group> --help
<cli> <group> <subcommand> --help
<cli> unknown-command
<cli> <read-only-command>
<cli> <read-only-command> <documented-structured-output-flag>
<cli> <read-only-command> <documented-field-selection-or-filter-flag>
CI=1 <cli> <read-only-command>
NO_COLOR=1 <cli> <read-only-command>
```

When testing failures, use `set -o pipefail` or capture `$?` before piping.

Use an explicit capture shape when checking stdout/stderr:

```bash
tmpdir="$(mktemp -d)"
<cli> <read-only-command> >"$tmpdir/stdout" 2>"$tmpdir/stderr"; status=$?
wc -c "$tmpdir/stdout" "$tmpdir/stderr"
head -c 500 "$tmpdir/stderr"
```

In the report, summarize whether stdout contains only requested data and stderr contains only auxiliary diagnostics.

For documented structured output, test parser compatibility without merging stderr. Use the documented parser for the format:

```bash
tmpdir="$(mktemp -d)"
<cli> <read-only-command> <documented-structured-output-flag> >"$tmpdir/stdout" 2>"$tmpdir/stderr"; status=$?
<documented-parser> "$tmpdir/stdout"
# For JSON, this is often: jq empty "$tmpdir/stdout"
```

## API Escape Hatch Probes

Use these as probe shapes, not a mandatory checklist. Run only probes that are supported by help output and safe for the current credentials. The goal is to see whether public API docs become CLI input directly.

```bash
<cli> api --help
<cli> request --help
<cli> schema --help
<cli> graphql --help
<cli> rpc --help
```

REST-like intent:

```bash
<cli> api <documented-read-only-path> <documented-method-flag>
<cli> api <documented-read-only-path> <documented-output-filter-flag>
```

GraphQL-like intent:

```bash
<cli> schema <documented-output-file-flag> /tmp/schema.graphql
<cli> api 'query { viewer { id } }'
<cli> api 'query Q($id: ID!) { node(id: $id) { id } }' <documented-variable-flag> id=value
```

JSON-RPC-like intent:

```bash
<cli> rpc <documented-method> <documented-params-json-flag> '{"key":"value"}'
<cli> rpc <documented-method> <documented-params-file-flag> params.json
```

## Source Search

Use these search intents as starting points. Adapt terms to the target language, framework, and command runner:

```bash
# command surface
rg -n "Command|cobra|click|argparse|commander|clap|urfave|yargs|subcommand|alias|completion" .
rg -n -i "usage:|available commands|commands:|subcommands|examples?:|namespace" .

# protocol-native escape hatch
rg -n "api|request|schema|introspection|GraphQL|REST|JSON-RPC|rpc|query|variables|params|endpoint|method" .
rg -n "paginate|pagination|pageInfo|cursor|after|nextPage|Link|rate limit|retry" .

# output and context
rg -n "json|jq|template|format|fields|selector|schema|Exporter|stdout|stderr|pager|color|NO_COLOR|progress" .
rg -n "isatty|isTTY|tty|stdin|console\\.log|console\\.error|print\\(|eprint|println|stderr|stdout" .

# non-interactive, safety, and errors
rg -n "prompt|interactive|confirm|yes|force|dry-run|NO_INPUT|CI|tty|stdin|silent|quiet" .
rg -n "error|usage|invalid|unknown|suggest|valid values|scope|exit|debug|stack" .

# auth and workspace context
rg -n "auth|token|host|repo|workspace|profile|config|context|credential|keyring" .

# tests
rg -n "snapshot|golden|fixture|mock server|CLI|parse|exit|stderr|stdout|help" test tests spec specs 2>/dev/null || true
```

## Problem Checks

Use these checks to write findings. Each bullet is a problem when runtime, source, test evidence, or a labeled inference proves it.

### Command Discovery and Intent

Mark as a problem when:

- a high-level intent requires manual low-level API calls
- top-level help is a flat wall of commands, with no groups, aliases, search path, or examples
- nested help pages are not exhaustive for their namespace or omit the next subcommands, options, or examples needed to keep drilling down
- every long-tail API or domain operation needs a first-class command because no escape hatch exists
- the same concept uses different flag names across commands without compatibility aliases
- extensions, plugins, or aliases bypass normal auth, config, output, or error handling

### Protocol-Native Escape Hatch

Mark as a problem when:

- a broad API surface has no raw API escape hatch
- official API docs cannot be translated into native CLI input, such as REST path plus method, GraphQL query plus variables, or JSON-RPC method plus params
- the escape hatch needs a custom DSL unrelated to public docs or stable domain objects
- protocol syntax is indistinguishable from high-level intent commands
- domain fields and CLI behavior flags share the same syntax with no clear boundary
- variables or params must be embedded in shell-escaped strings when JSON, `key=value`, file, or stdin channels are needed
- schema, introspection, field discovery, or method discovery is missing when the underlying protocol supports it
- pagination or cursor handling is missing, unbounded, or requires hand-written loops for common list queries
- raw API commands bypass shared auth, host/workspace, rate limit, retry, output, or error handling

### Output and Context Contract

Mark as a problem when:

- default `view`, `status`, or `list` output is raw JSON for a human-intent command
- structured output cannot limit returned fields through field flags, templates, jq-like filters, query selectors, or protocol-native field selection
- structured output invents CLI-specific shapes that hide or rename stable upstream or domain fields without a documented reason
- list commands have no default limit, pagination, or query filter
- source evidence shows field filtering happens only after large payloads are fetched
- output can only be trimmed after entering the caller context because built-in filters, templates, or selectors are missing
- stdout mixes data with warnings, progress, prompts, logs, or debug output
- verbose, debug, or trace output is printed to stdout when requested data is also printed to stdout
- structured stdout cannot be piped to the documented parser because banners, progress, color, prompts, or request logs corrupt it
- stderr carries the requested data instead of auxiliary information
- TTY and non-TTY output change data shape instead of presentation only

### Non-Interactive Contract

Mark as a problem when:

- a command waits for prompts in non-TTY or CI mode
- missing required input triggers a prompt instead of a clear non-interactive error
- auth requires a browser or TTY with no documented token, env, config, or credential path
- interactive auth, setup, or resource workflows lack a documented non-interactive fallback such as a URL handoff, wait command, token env var, config key, app/web handoff, or explicit resource override
- destructive commands can mutate persistent state without confirmation, explicit force, or dry-run
- `--yes` or `--force` hides the persistent action that will happen
- dry-run output omits the target resource, operation type, or payload summary
- debug output can expose tokens, secrets, or raw credentials

### Error and Recovery Contract

Mark as a problem when:

- validation, auth, HTTP, GraphQL, JSON-RPC, or domain errors exit with status 0
- silent or quiet modes suppress failure status instead of only suppressing text
- unknown commands lack close-match suggestions or a path back to help
- invalid enum, field, format, variable, or params errors omit valid values or examples
- auth errors omit login, token, host/workspace, or scope recovery hints
- missing repo, workspace, or context errors omit the explicit override flag or config key
- errors report only protocol status, such as HTTP 404, when the CLI has enough context to explain the likely domain cause and next action
- documented verbose or debug modes cannot reveal redacted request and response details needed to debug the failure
- raw HTTP or API error blobs are shown without domain context when the CLI has enough context to improve them

### Source and Test Signals

Mark as a problem when:

- every command hand-rolls JSON, table, error, prompt, auth, or pagination behavior
- prompt calls are buried inside business logic with no non-interactive branch or test seam
- output field names or JSON schemas are duplicated across commands
- API or query builders fetch fixed large payloads regardless of requested fields
- tests stop below the CLI parser for output, help, error, prompt, exit-code, or API escape-hatch behavior
- tests do not assert stdout/stderr separation for default, verbose, and structured-output commands
- tests do not simulate TTY, non-TTY, and CI behavior for commands that can prompt
- snapshot or golden tests are missing for stable help, default output, structured output, and actionable errors

## Evidence Labels

Use these labels in the report:

- Runtime: command output or exit behavior observed in this audit
- Source: file and line reference proving implementation
- Test: file and line reference proving coverage
- Inference: conclusion derived from evidence, explicitly labeled
- Unknown: not verified

Verdict-level claims need runtime plus source evidence when the CLI is runnable. If one side is unavailable, say source-only or runtime-only in the verdict.

## Scoring

Only score when the user asks for a score, comparison, shortlist, or procurement-style recommendation.

Use 0-3:

- 0: absent or hostile to agents
- 1: present but inconsistent or hard to discover
- 2: usable with specific gaps
- 3: strong, consistent, source-backed behavior

Score the five contracts first. Add the supporting surfaces when they matter to the task:

- command discovery and intent
- protocol-native escape hatch
- output and context contract
- non-interactive contract
- error and recovery contract
- auth/workspace handling
- plugin/extension behavior
- source/test maintainability

## Report Format

Start with the verdict. Lead with findings for a review. Lead with design lessons when the user asks what to learn from the CLI.

Default audit or review format:

```markdown
## Verdict

Agent-friendly / partially agent-friendly / not agent-friendly.

Evidence basis: runtime + source / source-only / runtime-only.

## Findings

- [severity] Finding.
  Evidence: Runtime ..., Source ...
  Fix: ...

## Runtime Probe Log

| Command     | Mode    | Exit | Stdout              | Stderr           | Parser / Pipe Check                                         |
| ----------- | ------- | ---: | ------------------- | ---------------- | ----------------------------------------------------------- |
| `<command>` | non-TTY |    0 | requested data only | diagnostics only | documented parser passed / not structured / stdout polluted |

## What Works

- ...

## Unknowns

- ...

## Recommended Changes

1. ...
2. ...
3. ...
```

When the user asks for design lessons, redesign guidance, or comparison, include this section before `What Works`:

```markdown
## Design Lessons

- Command discovery lesson: ...
- Protocol escape-hatch lesson: ...
- Output and context lesson: ...
- Non-interactive lesson: ...
- Error and recovery lesson: ...
```
