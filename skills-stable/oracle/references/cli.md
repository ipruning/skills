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

Do not probe unknown subcommands. Positional text can become prompt text and start a model session when API credentials are present.

If `oracle --version` fails with a mise shim error:

```sh
mise use -g node@24
mise exec -- oracle --version
```

If the binary is missing, ask before installing a package. Installing or uninstalling global npm packages changes the machine.

## Input

Use the package zip and prompt file:

```sh
ZIP_FILE="$ORACLE_WORK_DIR/<package>.zip"
PROMPT="$(cat "$PROMPT_FILE")"
```

## Dry Run

```sh
oracle --engine browser --model gpt-5.5-pro \
  --browser-attachments always \
  --max-file-size-bytes 104857600 \
  --dry-run summary --files-report \
  --file "$ZIP_FILE" \
  --prompt "$PROMPT"
```

Proceed only when stdout says `Attachments to upload`. Stop if the dry run says the package zip will be pasted inline or omitted.

## Run

Check existing sessions before starting:

```sh
oracle status --hours 2 --limit 20
```

If a matching session is running or has `promptSubmitted: true`, inspect that session instead of starting another run.

Start one browser run:

```sh
oracle --engine browser --model gpt-5.5-pro \
  --browser-attachments always \
  --max-file-size-bytes 104857600 \
  --file "$ZIP_FILE" \
  --prompt "$PROMPT" \
  --slug short-descriptive-slug \
  --write-output "$ANSWER_FILE"
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
