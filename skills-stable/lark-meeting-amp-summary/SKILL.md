---
name: lark-meeting-amp-summary
description: "Use when a user asks for a date-range Feishu/Lark Minutes collection: find minute_tokens, pull transcript files, inspect coverage and duplicate evidence, build Chinese prompts, or run Amp summaries. Do not use for a single minute_token lookup."
---

# Lark Meeting Amp Summary

Use this skill to collect Feishu/Lark Minutes for a date range, export local transcript files, inspect coverage and duplicate evidence, generate Chinese prompts, and run Amp summaries.

For one known historical video meeting, use `lark-vc`. For one known `minute_token`, use `lark-minutes`. For future calendar events, use `lark-calendar`.

## Files

The script is `scripts/lark_meeting_stt.py`.

Each run directory has four generated directories:

- `raw/`: raw `lark-cli` JSON and command logs.
- `minutes/`: one directory per `minute_token`, with `transcript.txt` and `meta.json`.
- `prompts/`: prompts generated from transcripts.
- `summaries/`: Amp outputs and summary indexes.

The run root has readable or editable files:

- `minutes-found.json`: all found `minute_token` values and their sources.
- `coverage.md`: login user, date range, source counts, and calendar/VC coverage evidence.
- `selected-minutes.txt`: `pull` reads this file. Edit it to skip candidates before export.
- `pulled.md` and `pulled.json`: export results and failures.
- `duplicates.md` and `duplicates.json`: duplicate evidence. The script never edits selections here.
- `selected-for-summary.txt`: `prompts` reads this file. Edit it after reading duplicate evidence.
- `prompt-index.json`: current prompt list. `summarize` reads this file.

Do not delete `minutes/<minute_token>/transcript.txt` to skip a meeting. Remove the token from `selected-for-summary.txt`.

## Workflow

Run commands from this skill directory. Resolve relative dates before calling the script; pass `YYYY-MM-DD`.

```bash
run="$HOME/Downloads/lark-meeting-$(date +%Y%m%d-%H%M%S)"
start_date="YYYY-MM-DD"
end_date="YYYY-MM-DD"
uv run --script scripts/lark_meeting_stt.py list --start "$start_date" --end "$end_date" --run "$run"
```

Read coverage before exporting transcripts.

```bash
sed -n '1,220p' "$run/coverage.md"
```

If a candidate should not be exported, edit `selected-minutes.txt`. Then export transcripts.

```bash
uv run --script scripts/lark_meeting_stt.py pull --run "$run"
sed -n '1,220p' "$run/pulled.md"
```

Check duplicate evidence.

```bash
uv run --script scripts/lark_meeting_stt.py check --run "$run"
sed -n '1,220p' "$run/duplicates.md"
```

Read `duplicates.md`. When a group needs judgment, open the related `minutes/<minute_token>/transcript.txt` files. Edit `selected-for-summary.txt` only after reading the evidence.

Generate prompts.

```bash
uv run --script scripts/lark_meeting_stt.py prompts --run "$run"
```

Run Amp only when `prompt-index.json` has `"ok": true`.

```bash
uv run --script scripts/lark_meeting_stt.py summarize --run "$run" --concurrency 4 --timeout-seconds 900
```

## Commands

### `list --start --end --run`

Find accessible Minutes. This command does not export transcripts.

It queries:

- `lark-cli vc +search`
- `lark-cli minutes +search --owner-ids me`
- `lark-cli minutes +search --participant-ids me`
- `lark-cli minutes +search --start ... --end ...`
- `lark-cli calendar +agenda`, then `lark-cli calendar +meeting`
- `lark-cli vc +notes` for meeting IDs found from VC search and calendar meetings

It writes `minutes-found.json`, `coverage.md`, `selected-minutes.txt`, and `raw/`.

`coverage.md` must be read before `pull`. It shows the login user, date range, source counts, calendar events without `meeting_id`, calendar meeting IDs not found by VC search, VC meetings not found in calendar, and tokens found only by time search.

### `pull --run`

Read `selected-minutes.txt` and export transcript files.

It writes:

- `minutes/<minute_token>/transcript.txt`
- `minutes/<minute_token>/meta.json`
- `pulled.md`
- `pulled.json`
- `selected-for-summary.txt`

Failed exports stay in `pulled.md` and `pulled.json`. Do not replace a failed transcript with meeting notes or an Amp summary.

If any selected token fails to export, `pull` still writes successful transcripts and `selected-for-summary.txt`, but exits with code `1` and sets `"ok": false`. Read `pulled.md` before continuing.

### `check --run`

Read pulled transcripts and write duplicate evidence to `duplicates.md` and `duplicates.json`.

Run `check` only after `pull`. The command fails if `pulled.json` is missing or no transcript was successfully exported.

Evidence types:

- `强重复`: full transcript SHA-256 is the same.
- `高度可疑`: normalized hash of the first 80 lines is the same.
- `弱可疑`: first line is the same, or line counts are close and duration/title evidence matches.

The command never edits `selected-for-summary.txt`.

### `prompts --run`

Read `selected-for-summary.txt` and generate `prompts/` plus `prompt-index.json`.

On every run, old `prompts/` and old `prompt-index.json` are removed before writing the current prompt set. If a selected token has no `transcript.txt`, the command fails and reports the missing token; run `pull` again or edit `selected-for-summary.txt`. Do not run `summarize` until `prompt-index.json` exists and has `"ok": true`.

Default prompt limit is `100000` tiktoken. Change it with `--max-prompt-tiktoken-count`.

### `summarize --run`

Read the current `prompt-index.json` and current `prompts/`. Rebuild `summaries/`.

If `summarize` cannot start because Amp, `prompt-index.json`, or prompt files are missing or invalid, it rebuilds `summaries/index.json` with `"ok": false` so old summaries are not mistaken for current output.

Use a lower `--concurrency` if Amp is slow or rate-limited. Use a higher `--timeout-seconds` for long meetings.

## Output Contract

Use `--format json` for automation. When the command reaches its own business logic, stdout contains one JSON object. Progress and dependency command details go to stderr. Syntax errors from Typer, such as missing required options or unknown commands, exit with code `2` and write help text to stderr.

Business errors exit with code `1`. With `--format json`, stdout contains `{"ok": false, "error": "...", "exit_code": 1}`.

Cold `uv run --script` may install Python dependencies and write those install logs to stderr. Do not parse stderr as the command result.

## Rules

- Keep all raw transcripts.
- Treat duplicate groups as evidence, not deletion instructions.
- Decide skipped meetings by editing `selected-for-summary.txt`.
- Regenerate prompts after editing `selected-for-summary.txt`.
- Do not run `summarize` when `prompt-index.json` is missing or has `"ok": false`.
