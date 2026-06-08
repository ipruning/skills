---
name: agent-friendly-cli-audit
description: |
  Use when auditing whether a CLI is usable by agents, scripts, CI, or other
  automation. Load for questions about command discovery, non-interactive
  execution, stdout/stderr separation, structured output, raw API escape
  hatches, auth/workspace context, actionable errors, or safe runtime probes.
metadata:
  short-description: Audit CLI usability for AI agents from runtime and source evidence
  version: "2.3.0"
---

# Agent-Friendly CLI Audit

## Rules

- Treat the target repository as read-only unless the user explicitly asks for
  changes.
- Use docs and README claims only as leads. Verdicts need runtime probes, source
  evidence, tests, or an explicit `Unknown`.
- Run only safe commands by default: help, version, read-only views, validation,
  dry-run, or disposable fixtures.
- Do not run production writes, billing actions, message sends, deletes, deploys,
  or force pushes unless the user explicitly approves that exact action. Label
  any such action as **persistent** in the report.
- Capture stdout and stderr separately for representative probes. Stdout is for
  requested data; stderr is for diagnostics, prompts, progress, trace, and
  recovery hints.
- Record each probe as command, mode, exit code, stdout summary, stderr summary,
  and parser/pipe result.

## Audit Contracts

Judge the CLI by these contracts. Use the contract names in findings.

- **Command discovery and intent**: user goals map to discoverable commands, and
  help supports progressive drill-down.
- **Protocol-native escape hatch**: long-tail API work can use upstream protocol
  shapes, such as REST path plus method, GraphQL query plus variables, or
  JSON-RPC method plus params.
- **Output and context contract**: stdout is parseable requested data, stderr is
  auxiliary context, and fields, limits, filters, or selectors keep output small.
- **Non-interactive contract**: prompts, auth, setup, confirmations, and
  workspace selection have scriptable paths in non-TTY and CI.
- **Error and recovery contract**: validation, auth, API, domain, and workspace
  failures keep non-zero exit codes and explain the next action.

Source and test quality support those contracts. Treat maintainability as a
separate finding only when it affects CLI behavior or the user asks for it.

## Workflow

1. Find the executable and safety boundary.
   - Check package manifests, `README`, `Makefile`, `bin/`, `cmd/`, release
     scripts, and installed binaries.
   - Run top-level help and version only when they are read-only.
   - Record missing binary, dependency, credential, or build blockers.

2. Map command discovery.
   - Start at top-level help, then sample nested help until command namespaces
     and common flags are clear.
   - Check examples, aliases, completions, plugins/extensions, and whether help
     pages show the next drill-down path.

3. Probe output and parser behavior.
   - Compare one human default command with its structured-output form when one
     exists.
   - Capture stdout/stderr separately.
   - Parse structured stdout with the documented parser, such as `jq empty` for
     JSON, without merging stderr.
   - Check field selection, filters, paging, limits, color, pager behavior, and
     TTY vs non-TTY presentation.

4. Probe non-interactive and error behavior.
   - Test unknown command, invalid flag, missing required argument, and invalid
     enum/value.
   - Test documented prompt suppression or CI paths such as `CI=1`, `NO_COLOR=1`,
     `NO_INPUT=1`, `--yes`, `--force`, or `--dry-run` only after help confirms
     the flag or env behavior.

5. Inspect protocol-native escape hatches.
   - Search for commands named `api`, `request`, `rest`, `graphql`, `schema`,
     `rpc`, `query`, or similar.
   - Verify the escape hatch shares auth, host/workspace context, pagination,
     retry/rate-limit handling, output formatting, and errors with normal
     commands.

6. Read source and tests.
   - Find command registration, option parsing, output/exporter code, API
     clients, query builders, auth/context resolution, prompt/confirmation
     handling, error handling, and CLI-level tests.
   - Prefer tests that exercise the real CLI parser, stdout/stderr, exit codes,
     TTY/non-TTY, CI, prompts, and structured output.

## Probe Templates

Confirm every flag in help before using it. These are shapes, not a checklist.

```bash
<cli> --help
<cli> --version
<cli> <group> --help
<cli> <group> <subcommand> --help
<cli> unknown-command
<cli> <read-only-command>
<cli> <read-only-command> <documented-structured-output-flag>
<cli> <read-only-command> <documented-field-or-filter-flag>
CI=1 <cli> <read-only-command>
NO_COLOR=1 <cli> <read-only-command>
```

Capture stdout/stderr and exit code without piping away the status:

```bash
tmpdir="$(mktemp -d)"
<cli> <read-only-command> >"$tmpdir/stdout" 2>"$tmpdir/stderr"; status=$?
wc -c "$tmpdir/stdout" "$tmpdir/stderr"
head -c 500 "$tmpdir/stdout"
head -c 500 "$tmpdir/stderr"
```

Check structured stdout alone:

```bash
tmpdir="$(mktemp -d)"
<cli> <read-only-command> <json-flag> >"$tmpdir/stdout" 2>"$tmpdir/stderr"; status=$?
jq empty "$tmpdir/stdout"
```

Probe protocol escape hatches only when help shows them and the call is safe:

```bash
<cli> api --help
<cli> request --help
<cli> graphql --help
<cli> schema --help
<cli> rpc --help
<cli> api <documented-read-only-path> <method-flag>
<cli> api 'query { viewer { id } }'
<cli> rpc <documented-method> <params-json-flag> '{"key":"value"}'
```

## Source Search

Adapt terms to the CLI's language and framework.

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

## Finding Triggers

Mark a finding when evidence proves one of these problems.

### Command Discovery and Intent

- Top-level help is a flat wall with no groups, examples, aliases, search path,
  or next drill-down.
- Nested help omits current namespace commands, options, examples, or next steps.
- Similar concepts use different flag names without compatibility aliases.
- Extensions or plugins bypass normal auth, config, output, or errors.

### Protocol-Native Escape Hatch

- A broad API surface has no raw API escape hatch.
- Official API docs cannot be translated into CLI input using native protocol
  shapes.
- The escape hatch uses an undocumented custom DSL.
- Variables or params must be embedded in shell-escaped strings when JSON,
  `key=value`, file, or stdin channels are needed.
- Pagination, schema/introspection, field discovery, shared auth, workspace,
  rate-limit handling, or output formatting is missing.

### Output and Context Contract

- Structured stdout is polluted by banners, progress, prompts, warnings, logs,
  color, request traces, or debug text.
- Requested data is printed to stderr.
- Human output and structured output change the data shape instead of only the
  presentation.
- Lists lack default limits, filters, pagination, or field selection.
- Field filtering happens only after fetching large unbounded payloads.

### Non-Interactive Contract

- A command waits for prompts in non-TTY or CI.
- Missing required input opens a prompt instead of returning a clear error.
- Auth requires browser or TTY with no token/env/config handoff.
- Destructive or persistent commands lack confirmation, explicit force, or
  dry-run.
- `--yes`, `--force`, or dry-run output hides the target resource, operation
  type, or payload summary.
- Debug or trace output can expose tokens, secrets, or raw credentials.

### Error and Recovery Contract

- Validation, auth, protocol, domain, or workspace failures exit with status 0.
- Silent or quiet modes suppress failure status.
- Unknown commands lack close-match suggestions or a path back to help.
- Invalid enum, field, format, params, or variable errors omit valid values or
  examples.
- Auth errors omit login/token/scope/host/workspace recovery hints.
- Protocol blobs are shown without domain context when the CLI has enough
  context to explain the likely cause and next action.
- Debug/verbose modes cannot show redacted request and response details needed
  for recovery.

### Source and Test Signals

- Commands hand-roll JSON, table, prompt, auth, pagination, or error behavior
  instead of sharing helpers.
- Prompt or confirmation calls are buried in business logic without a
  non-interactive branch.
- Output schemas or field names are duplicated across commands.
- Tests stop below the CLI parser for help, output, errors, prompts, exit codes,
  structured output, or API escape hatches.

## Evidence Labels

Use these labels in the report:

- `Runtime`: command output or exit behavior observed in this audit.
- `Source`: file and line reference proving implementation.
- `Test`: file and line reference proving coverage.
- `Inference`: conclusion derived from evidence; say what evidence supports it.
- `Unknown`: not verified.

If the CLI is runnable, verdict-level claims need runtime plus source evidence.
If one side is unavailable, label the verdict `source-only` or `runtime-only`.

## Scoring

Only score when the user asks for a score, comparison, shortlist, or
procurement-style recommendation.

Use 0-3:

- 0: absent or hostile to agents
- 1: present but inconsistent or hard to discover
- 2: usable with specific gaps
- 3: strong, consistent, source-backed behavior

Score the five contracts first. Add auth/workspace, plugin behavior, or
source/test maintainability only when relevant to the task.

## Report Format

Start with the verdict. Lead with findings for a review. Lead with design
lessons when the user asks what to learn from the CLI.

```markdown
## Verdict

Agent-friendly / partially agent-friendly / not agent-friendly.

Evidence basis: runtime + source / source-only / runtime-only.

## Findings

- [severity] Finding.
  Evidence: Runtime ..., Source ...
  Fix: ...

## Runtime Probe Log

| Command     | Mode    | Exit | Stdout              | Stderr           | Parser / Pipe Check |
| ----------- | ------- | ---: | ------------------- | ---------------- | ------------------- |
| `<command>` | non-TTY |    0 | requested data only | diagnostics only | jq passed           |

## What Works

- ...

## Unknowns

- ...

## Recommended Changes

1. ...
2. ...
3. ...
```
