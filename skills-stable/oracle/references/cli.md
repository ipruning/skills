# Oracle CLI

The agent uses Oracle CLI only when Chrome automation is unavailable, the environment is shell-only, or the user asks for CLI submission.

Non-dry-run commands start model work and write session state under `~/.oracle`. The agent treats non-dry-run commands as persistent and possibly billable.

## Safe Probes

The agent runs only documented probes before a real run:

```sh
oracle --version
oracle --help
oracle status --hours 2 --limit 10
```

The agent does not probe unknown subcommands. Positional text can become prompt text and start a model session when the CLI is authenticated.

If `oracle --version` fails, the agent states the toolchain problem. The agent asks before changing global config or installing a package.

If a probe fails with `mise ERROR No version is set for shim: oracle`, the
agent returns `oracle_cli_mise_shim_unconfigured`. The agent does not run
unknown `oracle` subcommands, change global mise config, or install Node. For a
package consultation type, the agent uses `manual-handoff` unless the user asks
to fix the CLI toolchain first.

## Input

The agent uses the prompt file. The agent sets `ZIP_FILE` only when the selected consultation type built a package zip.

```sh
PROMPT="$(cat "$PROMPT_FILE")"
ORACLE_MODEL="<pro-model-id>"

# Package consultation types only:
# ZIP_FILE="$ORACLE_WORK_DIR/<package>.zip"
```

The agent replaces `ORACLE_MODEL` with the newest visible Pro model or the highest-capability Pro model named by the CLI before running. If the CLI cannot confirm model availability, the agent uses `chrome-run` instead.

## Dry Run

```sh
if [ -n "${ZIP_FILE:-}" ]; then
  oracle --engine browser --model "$ORACLE_MODEL" \
    --browser-attachments always \
    --max-file-size-bytes 104857600 \
    --dry-run summary --files-report \
    --file "$ZIP_FILE" \
    --prompt "$PROMPT"
else
  oracle --engine browser --model "$ORACLE_MODEL" \
    --dry-run summary \
    --prompt "$PROMPT"
fi
```

For package consultation types, the agent proceeds only when stdout says `Attachments to upload`. The agent stops if the dry run says the package zip will be pasted inline or omitted. For consultation types without a package, the agent proceeds only when the dry run includes the prompt and no files.

## Run

The agent checks existing sessions before starting:

```sh
oracle status --hours 2 --limit 20
```

If an existing session has the same slug, prompt file, or package zip, or if it has `promptSubmitted: true`, the agent inspects that session instead of starting another run.

The agent starts one Oracle CLI run with the browser engine:

```sh
if [ -n "${ZIP_FILE:-}" ]; then
  oracle --engine browser --model "$ORACLE_MODEL" \
    --browser-attachments always \
    --max-file-size-bytes 104857600 \
    --file "$ZIP_FILE" \
    --prompt "$PROMPT" \
    --slug short-descriptive-slug \
    --write-output "$ANSWER_FILE"
else
  oracle --engine browser --model "$ORACLE_MODEL" \
    --prompt "$PROMPT" \
    --slug short-descriptive-slug \
    --write-output "$ANSWER_FILE"
fi
```

The agent uses the printed `Session: ...` value for later commands.

## Reattach

If the shell times out, the agent inspects the existing session. The agent does not rerun.

```sh
oracle session <slug> --harvest --write-output "$ANSWER_FILE"
```

If the browser tab is still generating, the agent waits or runs:

```sh
oracle session <slug> --live --write-output "$ANSWER_FILE"
```

When the conversation URL is known, the agent binds harvest to the conversation tab:

```sh
oracle session <slug> --harvest \
  --browser-tab 'https://chatgpt.com/c/<conversation-id>' \
  --write-output "$ANSWER_FILE"
```

## Signals

- `promptSubmitted: false`: the prompt never reached ChatGPT. The agent fixes the browser, login, or upload error before retrying.
- `promptSubmitted: true` plus no `ANSWER_FILE`: the agent does not rerun. The agent harvests or waits.
- `browser.harvest.state: completed`: the model completed even if top-level status says `running`.
- `Command timed out after ...`: the shell timed out; the Oracle CLI run may still be alive.
- `chrome-disconnected` or `Chrome window closed before oracle finished`: the agent states the browser automation failure.

The agent reads metadata:

```sh
sed -n '1,220p' "$HOME/.oracle/sessions/<slug>/meta.json"
```

## Verify

The agent treats `ANSWER_FILE` as a draft. The agent verifies paths, line references, cited sources, and claimed behavior locally before writing the user output.
