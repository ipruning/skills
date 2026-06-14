# Oracle CLI

Use the CLI only when Chrome control is unavailable, the environment is shell-only, or the user asks for it.

Non-dry-run commands start model work and write session state under `~/.oracle`. Treat them as persistent and possibly billable.

## Safe Probes

Run only documented probes before a real run:

```sh
oracle --version
oracle --help
oracle status --hours 2 --limit 10
```

Do not probe unknown subcommands. Positional text can become prompt text and start a model session when the CLI is authenticated.

If `oracle --version` fails with a mise shim error:

```sh
mise exec -- oracle --version
```

If the shim still fails or the binary is missing, report the toolchain problem. Ask before changing global mise config or installing a package.

## Input

Use the prompt file. Set `ZIP_FILE` only when the chosen route built a package zip.

```sh
PROMPT="$(cat "$PROMPT_FILE")"
ORACLE_MODEL="<latest-smartest-pro-model>"

# Package routes only:
# ZIP_FILE="$ORACLE_WORK_DIR/<package>.zip"
```

Replace `ORACLE_MODEL` with the latest, smartest Pro model currently available to the user before running. If the CLI cannot confirm model availability, use the Chrome route instead.

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

For package routes, proceed only when stdout says `Attachments to upload`. Stop if the dry run says the package zip will be pasted inline or omitted. For no-package routes, proceed only when the dry run includes the prompt and no files.

## Run

Check existing sessions before starting:

```sh
oracle status --hours 2 --limit 20
```

If a matching session is running or has `promptSubmitted: true`, inspect that session instead of starting another run.

Start one browser run:

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

Use the printed `Session: ...` value for later commands.

## Reattach

If the shell times out, inspect the existing session. Do not rerun.

```sh
oracle session <slug> --harvest --write-output "$ANSWER_FILE"
```

If the browser tab is still generating, wait or use:

```sh
oracle session <slug> --live --write-output "$ANSWER_FILE"
```

When the conversation URL is known, bind harvest to that tab:

```sh
oracle session <slug> --harvest \
  --browser-tab 'https://chatgpt.com/c/<conversation-id>' \
  --write-output "$ANSWER_FILE"
```

## Signals

- `promptSubmitted: false`: prompt never reached ChatGPT. Fix the browser, login, or upload error before retrying.
- `promptSubmitted: true` plus no `ANSWER_FILE`: do not rerun. Harvest or wait.
- `browser.harvest.state: completed`: the model completed even if top-level status says `running`.
- `Command timed out after ...`: the shell timed out; the browser run may still be alive.
- `chrome-disconnected` or `Chrome window closed before oracle finished`: report browser automation failure.

Read metadata:

```sh
sed -n '1,220p' "$HOME/.oracle/sessions/<slug>/meta.json"
```

## Verify

Treat `ANSWER_FILE` as a draft. Verify paths, line references, cited sources, and claimed behavior locally before reporting.
