---
name: lark-meeting-amp-summary
description: >-
  Use when a user wants to find recent accessible Feishu/Lark meetings or Minutes,
  audit which raw STT transcripts should be exported without reading full meeting
  text, export metadata-only transcript indexes, and render token-budgeted prompts
  for downstream Amp summaries.
---

# Lark Meeting Amp Summary

## Rule

Audit first. During audit and selection, read only `audit.md`, `audit.json`, and metadata from `transcripts.json`. Do not open `stt/**/transcript.txt`; full STT text only enters the rendered prompt, and `render` blocks prompts over the tiktoken budget.

Raw STT is the summarization source. Feishu AI minutes are metadata only.

## Workflow

Run from this Skill directory. Use a run directory outside the repo:

```bash
run="$HOME/Downloads/lark-meeting-$(date +%Y%m%d-%H%M%S)"
```

### 1. Audit Candidates

This stage does not download or read transcript full text.

```bash
uv run --script scripts/lark_meeting_stt.py audit \
  --days 2 \
  --run "$run" \
  --format json

sed -n '1,200p' "$run/audit.md"
```

Use explicit dates when needed:

```bash
uv run --script scripts/lark_meeting_stt.py audit --start "$start" --end "$end" --run "$run"
```

`audit.json` contains:

- `summary.vc_meetings`
- `summary.minutes_owned`
- `summary.minutes_participated`
- `summary.minute_candidates`
- `summary.duplicate_hint_groups`
- `candidates[]`: `minute_token`, `title`, `sources`, `meeting_ids`, `start_time`, `duration`, `decision_hint`
- `duplicate_hints[]`

Select meetings only from the audit surface:

```bash
jq -r '.candidates[] | select(.decision_hint=="candidate") | .minute_token' "$run/audit.json" > "$run/selected.txt"
```

If the count is surprising, `metadata_unavailable` is broad, or `duplicate_hints` is non-empty, edit `selected.txt` before export.

### 2. Export Selected STT Metadata

Persistent: writes `stt/`, `raw/`, `logs/`, `selected.txt`, `transcripts.json`, `excluded.txt`, `dedupe.md`, and `decisions.md`. The tool reads STT internally for hash and token counts, but JSON/stdout never include transcript body. Re-running export only indexes artifacts whose minute tokens are in the current selection; stale `stt/` files and unselected artifacts are reported as metadata and do not enter `transcripts.json`.

`transcripts[]` must match the current `selected.txt`. If `lark-cli` returns or leaves artifacts for tokens not present in `selected.txt`, they are recorded under `unselected_transcript_artifacts` / `stale_transcript_artifacts` and excluded from transcript counts, duplicate hints, render, and title inference.

```bash
uv run --script scripts/lark_meeting_stt.py export \
  --run "$run" \
  --overwrite \
  --format json
```

To export all audited candidates without manual selection:

```bash
uv run --script scripts/lark_meeting_stt.py export \
  --run "$run" \
  --all-audited \
  --overwrite
```

Inspect metadata only:

```bash
jq '.summary, .duplicate_hints, .transcripts[] | {minute_token,title,bytes,line_count,token_count}' "$run/transcripts.json"
```

`transcripts.json` contains:

- `summary.selected_minute_tokens`
- `summary.exported_transcripts`
- `summary.errors`
- `summary.duplicate_hint_groups`
- `summary.stale_transcript_artifacts`
- `summary.unselected_transcript_artifacts`
- `transcripts[]`: `minute_token`, `title`, `rel_path`, `bytes`, `line_count`, `first_line`, `sha256`, `prefix_sha256`, `token_count`
- `duplicate_hints[]`: same SHA, same first line, same prefix, plus a recommendation that prefers `vc_notes`, richer source coverage, then titled transcripts
- `errors[]`
- `excluded[]`
- `unselected_transcript_artifacts[]`

Stop here when:

- `summary.exported_transcripts` is lower than `summary.selected_minute_tokens`.
- `errors` is non-empty.
- `duplicate_hints` is non-empty.
- `summary.stale_transcript_artifacts` is non-zero.
- `summary.unselected_transcript_artifacts` is non-zero.
- `token_count` is too large for one prompt.

### 3. Render Token-Budgeted Prompts

Persistent: writes prompt Markdown files under budget and `prompts.json`. Default `--max-input-tokens` is `100000`; default tiktoken encoding is `o200k_base`.

```bash
uv run --script scripts/lark_meeting_stt.py render \
  --run "$run" \
  --max-input-tokens 100000
```

If any rendered prompt exceeds the budget, `render` exits non-zero, writes no prompt for that transcript, and records it in `prompts.json.skipped_oversized`. Do not open transcript text to debug this; reduce `selected.txt` or split the oversized meeting.

### 4. Summarize With Amp

External model call: rendered prompt files contain meeting STT and are sent to Amp. Run this only after transcript selection and token gate pass. Use the bundled runner when progress, timeout, and exit-code records matter:

```bash
uv run --script scripts/lark_meeting_stt.py summarize \
  --run "$run" \
  --concurrency 8 \
  --timeout-seconds 900 \
  --format json
```

`summarize` runs Amp prompts concurrently by default (`--concurrency 8`). `summaries/index.jsonl` records per-prompt started/completed events, exit code, duration, output bytes, timeout status, and stderr. If Amp rate limits or local resources become noisy, lower `--concurrency`; if one prompt repeatedly times out, split that meeting or lower `--timeout-seconds`.

### 5. Final Rollup

Create a final Markdown report from `audit.json`, `decisions.md`, `transcripts.json`, `prompts.json`, `summaries/index.jsonl`, and `summaries/*.summary.md`. Do not read `stt/**/transcript.txt`. Include:

- coverage range and counts
- excluded meetings and reasons
- duplicate decisions
- two-day overview
- merged themes
- action items
- open questions
- per-meeting summary index

## Output Files

- `audit.json`: candidate counts, tokens, source coverage, duplicate hints.
- `audit.md`: compact audit surface for AI selection.
- `selected.txt`: one selected `minute_token` per line.
- `transcripts.json`: metadata-only transcript index, token counts, errors, duplicate hints.
- `excluded.txt`: inaccessible or failed minute tokens.
- `dedupe.md`: duplicate groups and recommended keep/exclude decisions.
- `decisions.md`: coverage, exclusions, duplicate hints, stale and unselected artifacts.
- `prompts.json`: rendered prompt file index.
- `summaries/index.jsonl`: Amp progress events.
- `raw/`: lark-cli page JSON and note batch JSON.
- `logs/`: command logs.

## Template Model

Templates receive:

- `transcript`: raw STT text.
- `meeting.title`: best-known meeting title.

Keep rendered prompts focused on the downstream execution task: summarize the provided transcript according to the template instructions. Do not include audit metadata, transcript file paths, or source indexes in prompts sent to external models.

## Failure Signals And Guards

- Non-zero script exit means the current stage failed; inspect stderr and the matching file under `logs/`.
- `render` exits non-zero when any rendered prompt exceeds `--max-input-tokens`.
- Access failures are reported in `transcripts.json.errors`; never replace missing raw STT with Feishu AI minutes.
- Duplicate hints require a human or Agent decision; the CLI does not delete likely duplicates automatically.
