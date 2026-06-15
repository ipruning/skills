---
name: lark-meeting-amp-summary
description: >-
  Accessible Feishu/Lark meeting STT needs metadata-only audit, selection, and
  export; optionally render tiktoken-gated prompts and run Amp summaries.
---

# Lark Meeting Amp Summary

## Contract

The workflow handles raw STT audit, export, prompt rendering, and optional Amp summaries. If the user asks for historical meeting products without this raw STT workflow, use `lark-vc`. If the user asks to create, update, upload, or manage Minutes, use `lark-minutes`. If the user asks about future calendar events, use `lark-calendar`.

The workflow audits before export. During audit minute selection, the workflow reads only `audit.md` and `audit.json`. During post-export review, the workflow reads `initial-export.json`, `export-decisions.md`, `duplicate-decisions.md`, and metadata from `transcript-index.json`. The workflow does not open `stt/**/transcript.txt`. Rendered prompt files are the first files that contain full STT text. `render` scans every transcript, skips oversized prompts, writes under-budget prompts, and exits non-zero if any prompt exceeds the tiktoken budget.

Raw STT supplies summary evidence. Feishu AI minutes supply metadata only. The default template receives only raw STT text and the best-known meeting title.

The workflow uses these names:

- `minute_id`: identifies one Feishu/Lark Minute. Generated metadata uses this name. The script maps current Lark search `token` fields and current `vc +notes` `minute_token` fields into it.
- `pagination_page_token`: a Lark pagination cursor, not a meeting or model-budget value.
- `transcript_tiktoken_count`: tiktoken count for one exported STT transcript.
- `prompt_tiktoken_count`: tiktoken count for one rendered prompt sent to Amp.
- `audited_minutes`: lists minute records that audit found and exposes for selection.
- `duplicate_warnings`: holds duplicate evidence that needs a keep/exclude decision.

## Workflow

Run commands from this Skill directory. Keep the run directory outside the repo:

```bash
run="$HOME/Downloads/lark-meeting-$(date +%Y%m%d-%H%M%S)"
```

Use only this run's files listed in Output Files. Ignore legacy artifacts from older runs.

Resolve relative date words before audit. If the user says "last Sunday", "last week", or a similar phrase, write the exact local dates into `--start` and `--end` before running the command.

### 1. Audit Minutes

The audit command does not download or read transcript full text.

```bash
uv run --script scripts/lark_meeting_stt.py audit \
  --days 2 \
  --run "$run" \
  --format json

sed -n '1,200p' "$run/audit.md"
```

Pass explicit dates when the user names a date range:

```bash
uv run --script scripts/lark_meeting_stt.py audit --start "$start" --end "$end" --run "$run"
```

`audit.json` contains:

- `summary.vc_meetings`
- `summary.minutes_owned`
- `summary.minutes_participated`
- `summary.audited_minutes`
- `summary.duplicate_warning_groups`
- `audited_minutes[]`: `minute_id`, `title`, `sources`, `meeting_ids`, `start_time`, `duration`, `selection_status`
- `duplicate_warnings[]`

Select minute IDs only from the audit surface:

```bash
jq -r '.audited_minutes[] | select(.selection_status=="selectable") | .minute_id' "$run/audit.json" > "$run/selected-minutes.txt"
```

If the count is surprising, `metadata_unavailable` is broad, or `duplicate_warnings` is non-empty, edit `selected-minutes.txt` before export.

### 2. Export Selected STT Metadata

The export command writes `stt/`, `raw/`, `logs/`, `selected-minutes.txt`, `initial-export.json`, `transcript-index.json`, `excluded-minutes.txt`, `duplicate-decisions.md`, and `export-decisions.md`. The command reads STT internally for hash and tiktoken counts, but JSON/stdout never include transcript body. The first export writes `initial-export.json`; later export reruns never overwrite it. A rerun indexes only files whose `minute_id` is in the current selection. The export metadata reports stale or unexpected files and keeps them out of `transcript-index.json`.

`transcripts[]` must match the current `selected-minutes.txt`. If `lark-cli` returns or leaves files for minute IDs not present in `selected-minutes.txt`, the export metadata records them under `unexpected_exported_files` or `stale_exported_files` and excludes them from transcript counts, duplicate warnings, render, and title inference.

```bash
uv run --script scripts/lark_meeting_stt.py export \
  --run "$run" \
  --overwrite \
  --format json
```

Export all audited minutes only when the user asks for the full audited set:

```bash
uv run --script scripts/lark_meeting_stt.py export \
  --run "$run" \
  --all-audited-minutes \
  --overwrite
```

Inspect metadata only:

```bash
jq '.summary, .duplicate_warnings, .transcripts[] | {minute_id,title,bytes,line_count,transcript_tiktoken_count}' "$run/transcript-index.json"
```

`transcript-index.json` contains:

- `summary.selected_minutes`
- `summary.exported_transcripts`
- `summary.errors`
- `summary.duplicate_warning_groups`
- `summary.stale_exported_files`
- `summary.unexpected_exported_files`
- `transcripts[]`: `minute_id`, `title`, `rel_path`, `bytes`, `line_count`, `first_line`, `sha256`, `prefix_sha256`, `transcript_tiktoken_count`
- `duplicate_warnings[]`: same SHA, same first line, same prefix, plus a recommendation that ranks `vc_minute_lookup`, richer source coverage, then titled transcripts
- `errors[]`
- `excluded[]`
- `stale_exported_files[]`
- `unexpected_exported_files[]`

`initial-export.json` preserves the first export evidence for this run. Use it when a later clean export overwrote `transcript-index.json`, `export-decisions.md`, or `duplicate-decisions.md`.

Stop after export when:

- `summary.exported_transcripts` is lower than `summary.selected_minutes`.
- `errors` is non-empty.
- `duplicate_warnings` is non-empty.
- `summary.stale_exported_files` is non-zero.
- `summary.unexpected_exported_files` is non-zero.
- `transcript_tiktoken_count` is too large for one prompt.

### 3. Render Tiktoken-Budgeted Prompts

The render command writes prompt Markdown files under budget and `prompt-index.json`. Default `--max-prompt-tiktoken-count` is `100000`; default tiktoken encoding is `o200k_base`.

```bash
uv run --script scripts/lark_meeting_stt.py render \
  --run "$run" \
  --max-prompt-tiktoken-count 100000
```

If any rendered prompt exceeds the budget, `render` exits non-zero after processing all transcripts. It writes under-budget prompts, writes no prompt for oversized transcripts, and records oversized transcripts in `prompt-index.json` field `skipped_oversized_prompts[]`. Do not open transcript text to debug this. Change `selected-minutes.txt`, rerun export, and rerun render, or split the oversized meeting.

### 4. Summarize With Amp

Rendered prompt files contain meeting STT and go to Amp. Run Amp only when the user asks for summaries, rollups, or Amp output, and only after transcript selection and the tiktoken gate pass. If the user asks only for audit, export, or an index, stop after the requested stage and report output paths. The bundled runner records progress, timeout, and exit codes:

```bash
uv run --script scripts/lark_meeting_stt.py summarize \
  --run "$run" \
  --concurrency 4 \
  --timeout-seconds 900 \
  --format json
```

`summarize` runs Amp prompts concurrently by default (`--concurrency 4`). `summaries/index.jsonl` records per-prompt started/completed events, exit code, duration, output bytes, timeout status, and stderr.

If one long prompt fails while the rest pass, rerun that prompt by `minute_id`:

```bash
uv run --script scripts/lark_meeting_stt.py summarize \
  --run "$run" \
  --minute-id "$minute_id" \
  --concurrency 1 \
  --timeout-seconds 1800
```

If one prompt repeatedly times out, increase `--timeout-seconds` or split that meeting.

### 5. Final Rollup

The final Markdown report uses `audit.json`, `initial-export.json`, `export-decisions.md`, `duplicate-decisions.md`, `transcript-index.json`, `prompt-index.json`, `summaries/index.json`, `summaries/index.jsonl`, and `summaries/*.summary.md`. Do not read `stt/**/transcript.txt` or command logs. If `summaries/index.json.ok` is false or `summary.failures` is non-zero, handle failed prompts before the final rollup. The report includes:

- coverage range and counts
- excluded meetings and reasons
- duplicate decisions
- coverage-window overview
- merged themes
- action items
- open questions
- per-meeting summary index

## Output Files

- `audit.json`: audited minute counts, source coverage, duplicate warnings.
- `audit.md`: compact audit surface for choosing minute IDs.
- `selected-minutes.txt`: one selected `minute_id` per line.
- `initial-export.json`: first export report, preserved across later export reruns.
- `transcript-index.json`: metadata-only transcript index, tiktoken counts, errors, duplicate warnings.
- `excluded-minutes.txt`: inaccessible or failed minute IDs.
- `duplicate-decisions.md`: duplicate groups and recommended keep/exclude decisions.
- `export-decisions.md`: coverage, exclusions, duplicate warnings, stale files, and unexpected files.
- `prompt-index.json`: rendered prompt file index.
- `summaries/index.json`: Amp summary result index, failure count, and per-prompt results.
- `summaries/index.jsonl`: Amp progress events.
- `raw/`: lark-cli page JSON and upstream minute-artifact batch JSON.
- `logs/`: command metadata and stderr. Logs omit stdout and are not final-report evidence.

## Template Model

Templates receive these variables:

- `transcript`: raw STT text.
- `meeting.title`: best-known meeting title.

Rendered prompts ask the model to summarize the provided transcript according to the template instructions. Rendered prompts do not include audit metadata, transcript file paths, or source indexes.

## Failure Signals And Guards

- A non-zero script exit means the current stage failed. Inspect terminal stderr and the stage JSON first. Logs contain command metadata and stderr only.
- `render` exits non-zero when any rendered prompt exceeds `--max-prompt-tiktoken-count`.
- Access failures are reported in `transcript-index.json.errors`; never replace missing raw STT with Feishu AI minutes.
- Duplicate warnings require a keep/exclude decision before render. The CLI does not delete likely duplicates automatically.
