# Oracle CLI

The agent uses the CLI only when Chrome control is unavailable, the environment is shell-only, or the user asks for the CLI.

Non-dry-run commands start model work and write session state under `~/.oracle`. The agent treats non-dry-run commands as persistent and possibly billable.

## Safe Probes

The agent runs only documented probes before a real run:

```sh
oracle --version
oracle --help
oracle status --hours 2 --limit 10
```

The agent does not probe unknown subcommands. Positional text can become prompt text and start a model session when the CLI is authenticated.

If `oracle --version` fails, the agent reports the toolchain problem. The agent asks before changing global config or installing a package.

## Input

The agent uses the prompt file. The agent sets `ZIP_FILE` only when the chosen route built a package zip.

```sh
PROMPT="$(cat "$PROMPT_FILE")"
ORACLE_MODEL="<latest-smartest-pro-model>"

# Package routes only:
# ZIP_FILE="$ORACLE_WORK_DIR/<package>.zip"
```

The agent replaces `ORACLE_MODEL` with the latest, smartest Pro model currently available to the user before running. If the CLI cannot confirm model availability, the agent uses the Chrome route instead.

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

For package routes, the agent proceeds only when stdout says `Attachments to upload`. The agent stops if the dry run says the package zip will be pasted inline or omitted. For no-package routes, the agent proceeds only when the dry run includes the prompt and no files.

## Run

The agent checks existing sessions before starting:

```sh
oracle status --hours 2 --limit 20
```

If a matching session is running or has `promptSubmitted: true`, the agent inspects that session instead of starting another run.

The agent starts one browser run:

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
- `Command timed out after ...`: the shell timed out; the browser run may still be alive.
- `chrome-disconnected` or `Chrome window closed before oracle finished`: the agent reports browser automation failure.

The agent reads metadata:

```sh
sed -n '1,220p' "$HOME/.oracle/sessions/<slug>/meta.json"
```

## Verify

The agent treats `ANSWER_FILE` as a draft. The agent verifies paths, line references, cited sources, and claimed behavior locally before reporting.
