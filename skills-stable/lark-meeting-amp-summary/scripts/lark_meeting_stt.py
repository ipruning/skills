#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "jinja2>=3.1.6",
#   "tiktoken>=0.13.0",
# ]
# ///
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import tiktoken
from jinja2 import Environment, FileSystemLoader, StrictUndefined

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = SKILL_ROOT / "templates" / "meeting-summary.md.j2"
DEFAULT_ENCODING = "o200k_base"
DEFAULT_MAX_INPUT_TOKENS = 100_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit, export, and render Lark meeting raw STT.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    audit = subcommands.add_parser("audit", help="Discover meeting candidates without reading STT full text.")
    audit.add_argument("--start", help="Start date, YYYY-MM-DD.")
    audit.add_argument("--end", help="End date, YYYY-MM-DD.")
    audit.add_argument("--days", type=int, default=2, help="Date window ending today when --start/--end are omitted.")
    audit.add_argument("--run", type=Path, required=True, help="Run directory. Writes audit.json and audit.md.")
    audit.add_argument("--page-size", type=int, default=30, help="lark-cli page size for each search request.")
    audit.add_argument("--format", choices=("json", "md"), default="json", help="Stdout format.")

    export = subcommands.add_parser("export", help="Export selected raw STT and write metadata-only transcript index.")
    export.add_argument(
        "--run", type=Path, required=True, help="Run directory. Reads selected.txt and writes transcripts.json."
    )
    export.add_argument("--tokens", help="Comma/newline separated minute tokens.")
    export.add_argument("--selected", type=Path, help="Selected token file. Defaults to RUN/selected.txt.")
    export.add_argument("--all-audited", action="store_true", help="Export every candidate from audit.json.")
    export.add_argument("--audit", type=Path, help="Audit JSON for --all-audited. Defaults to RUN/audit.json.")
    export.add_argument("--batch-size", type=int, default=50, help="Minute tokens per lark-cli export request.")
    export.add_argument("--overwrite", action="store_true", help="Overwrite existing exported STT artifacts.")
    export.add_argument("--encoding", default=DEFAULT_ENCODING, help="tiktoken encoding for transcript token counts.")
    export.add_argument("--format", choices=("json", "md"), default="json", help="Stdout format.")

    render = subcommands.add_parser("render", help="Render prompts from exported STT with a tiktoken hard gate.")
    render.add_argument(
        "--run", type=Path, required=True, help="Run directory. Defaults to RUN/transcripts.json and RUN/prompts."
    )
    render.add_argument(
        "--transcripts", type=Path, help="transcripts.json from export. Defaults to RUN/transcripts.json."
    )
    render.add_argument("--prompts", type=Path, help="Prompt output directory. Defaults to RUN/prompts.")
    render.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE, help="Jinja prompt template.")
    render.add_argument("--start", help="Start date for template metadata, YYYY-MM-DD.")
    render.add_argument("--end", help="End date for template metadata, YYYY-MM-DD.")
    render.add_argument("--days", type=int, default=2, help="Fallback date window when no audit.json is available.")
    render.add_argument("--max-input-tokens", type=int, default=DEFAULT_MAX_INPUT_TOKENS, help="Hard tiktoken gate.")
    render.add_argument("--encoding", default=DEFAULT_ENCODING, help="tiktoken encoding.")
    render.add_argument("--format", choices=("json", "md"), default="json", help="Stdout format.")

    summarize = subcommands.add_parser("summarize", help="Run Amp for rendered prompts with progress JSONL.")
    summarize.add_argument("--run", type=Path, required=True, help="Run directory. Reads RUN/prompts.json.")
    summarize.add_argument("--prompts", type=Path, help="prompts.json from render. Defaults to RUN/prompts.json.")
    summarize.add_argument("--summaries", type=Path, help="Summary output directory. Defaults to RUN/summaries.")
    summarize.add_argument("--timeout-seconds", type=int, default=900, help="Per-prompt Amp timeout.")
    summarize.add_argument("--concurrency", type=int, default=8, help="Maximum concurrent Amp processes.")
    summarize.add_argument("--amp-mode", default="deep")
    summarize.add_argument("--amp-effort", default="xhigh")
    summarize.add_argument("--amp-visibility", default="private")
    summarize.add_argument("--format", choices=("json", "md"), default="json", help="Stdout format.")
    return parser.parse_args()


def eprint(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON file: {path}: {exc}") from exc


def emit(payload: dict[str, Any], *, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif fmt == "md":
        print(report_markdown(payload))
    else:
        raise ValueError(f"unknown format: {fmt}")


def report_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Lark Meeting Report", ""]
    summary = payload.get("summary")
    if isinstance(summary, dict):
        lines.extend(["## Summary", ""])
        lines.extend(f"- {key}: {value}" for key, value in summary.items())
        lines.append("")
    for key in (
        "duplicate_hints",
        "errors",
        "excluded",
        "stale_transcript_artifacts",
        "unselected_transcript_artifacts",
        "skipped_oversized",
        "stop_points",
    ):
        items = payload.get(key)
        if items:
            lines.extend([f"## {key.replace('_', ' ').title()}", ""])
            lines.extend(f"- `{json.dumps(item, ensure_ascii=False)}`" for item in items)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def require_commands(commands: list[str]) -> None:
    missing = [command for command in commands if shutil.which(command) is None]
    if missing:
        raise SystemExit("Missing required command(s): " + ", ".join(missing))


def parse_date_window(start: str | None, end: str | None, days: int) -> tuple[str, str]:
    if start and end:
        validate_date(start)
        validate_date(end)
        return start, end
    if start or end:
        raise SystemExit("--start and --end must be provided together.")
    if days < 1:
        raise SystemExit("--days must be >= 1.")
    today = dt.date.today()
    first = today - dt.timedelta(days=days - 1)
    return first.isoformat(), today.isoformat()


def render_date_window(args: argparse.Namespace, base: Path) -> tuple[str, str]:
    if args.start or args.end:
        return parse_date_window(args.start, args.end, args.days)
    audit_path = base / "audit.json"
    if audit_path.exists():
        audit = load_json(audit_path)
        run = audit.get("run") or {}
        if run.get("start") and run.get("end"):
            return str(run["start"]), str(run["end"])
    return parse_date_window(None, None, args.days)


def validate_date(value: str) -> None:
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def token_encoder(name: str) -> tiktoken.Encoding:
    try:
        return tiktoken.get_encoding(name)
    except ValueError as exc:
        raise SystemExit(f"unknown tiktoken encoding {name!r}") from exc


def token_count(text: str, *, encoding: tiktoken.Encoding) -> int:
    return len(encoding.encode(text))


def run_cmd(cmd: list[str], *, cwd: Path, log: Path | None = None) -> subprocess.CompletedProcess[str]:
    started = time.time()
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if log:
        write_text(
            log,
            "\n".join(
                [
                    "START " + dt.datetime.now().isoformat(timespec="seconds"),
                    "CWD " + str(cwd),
                    "CMD " + " ".join(cmd),
                    f"EXIT {proc.returncode}",
                    f"DURATION_SECONDS {time.time() - started:.3f}",
                    "",
                    "STDERR",
                    proc.stderr,
                    "",
                    "STDOUT",
                    proc.stdout,
                ]
            ),
        )
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr}")
    return proc


def run_json(cmd: list[str], *, cwd: Path, log: Path | None = None) -> Any:
    proc = run_cmd(cmd, cwd=cwd, log=log)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"command did not return JSON: {' '.join(cmd)}") from exc
    if payload.get("ok") is not True:
        raise RuntimeError(f"lark-cli returned ok=false: {payload.get('error', payload)}")
    return payload


def run_paginated(base_cmd: list[str], *, cwd: Path, page_dir: Path, log_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token = ""
    page = 1
    while True:
        cmd = [*base_cmd, "--format", "json"]
        if page_token:
            cmd.extend(["--page-token", page_token])
        eprint(f"page {page}: {' '.join(base_cmd)}")
        payload = run_json(cmd, cwd=cwd, log=log_dir / f"page-{page}.log")
        write_json(page_dir / f"page-{page}.json", payload)
        items.extend(payload.get("data", {}).get("items") or [])
        if payload.get("data", {}).get("has_more") is not True:
            return items
        page_token = payload.get("data", {}).get("page_token") or ""
        if not page_token:
            raise RuntimeError(f"has_more=true but page_token is empty for {' '.join(base_cmd)}")
        page += 1


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def best_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        if value is not None and not isinstance(value, (dict, list)):
            return str(value)
    return ""


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def token_from_slug(slug: str) -> str:
    match = re.search(r"(obcn[a-z0-9]+)$", slug)
    return match.group(1) if match else ""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def transcript_prefix_hash(text: str) -> str:
    prefix = "".join(text.splitlines()[:80])
    return sha256_text(re.sub(r"\s+", "", prefix))


def candidate_from_token(
    token: str,
    *,
    source: str,
    item: dict[str, Any] | None = None,
    meeting_id: str = "",
) -> dict[str, Any]:
    item = item or {}
    title = best_string(item, ("title", "topic", "name", "subject"))
    start_time = best_string(item, ("start_time", "start", "start_at", "meeting_start_time"))
    duration = best_string(item, ("duration", "duration_seconds", "meeting_duration"))
    unavailable = [
        field for field, value in (("title", title), ("start_time", start_time), ("duration", duration)) if not value
    ]
    return {
        "minute_token": token,
        "title": title,
        "sources": [source],
        "meeting_ids": [meeting_id] if meeting_id else [],
        "start_time": start_time,
        "duration": duration,
        "metadata_unavailable": unavailable,
        "decision_hint": "candidate",
    }


def merge_candidate(candidates: dict[str, dict[str, Any]], candidate: dict[str, Any]) -> None:
    token = candidate["minute_token"]
    existing = candidates.setdefault(token, candidate)
    if existing is candidate:
        return
    existing["sources"] = unique([*existing.get("sources", []), *candidate.get("sources", [])])
    existing["meeting_ids"] = unique([*existing.get("meeting_ids", []), *candidate.get("meeting_ids", [])])
    for key in ("title", "start_time", "duration"):
        if not existing.get(key) and candidate.get(key):
            existing[key] = candidate[key]
    existing["metadata_unavailable"] = [
        field for field in ("title", "start_time", "duration") if not existing.get(field)
    ]


def build_candidate_duplicate_hints(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_signature: dict[str, list[str]] = {}
    for candidate in candidates:
        title = normalize_title(candidate.get("title") or "")
        start = candidate.get("start_time") or ""
        duration = candidate.get("duration") or ""
        signature = "|".join(str(part) for part in (title, start, duration) if part)
        if signature:
            by_signature.setdefault(signature, []).append(candidate["minute_token"])
    return [
        {"kind": "same_title_time_duration", "signature": signature, "minute_tokens": tokens}
        for signature, tokens in by_signature.items()
        if len(tokens) > 1
    ]


def apply_candidate_decision_hints(candidates: list[dict[str, Any]], duplicate_hints: list[dict[str, Any]]) -> None:
    duplicate_tokens = {token for hint in duplicate_hints for token in hint.get("minute_tokens", [])}
    for candidate in candidates:
        candidate["decision_hint"] = (
            "likely_duplicate" if candidate["minute_token"] in duplicate_tokens else "candidate"
        )


def audit_markdown(report: dict[str, Any]) -> str:
    run = report["run"]
    summary = report["summary"]
    lines = [
        "# Lark Meeting STT Audit",
        "",
        "Select meetings from this audit only. Do not open `stt/**/transcript.txt` during audit.",
        "",
        "## Range",
        "",
        f"- start: {run['start']}",
        f"- end: {run['end']}",
        f"- run: `{run['dir']}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in summary.items())
    lines.extend(
        [
            "",
            "## Candidates",
            "",
            "| decision | minute_token | title | sources | start_time | duration | missing_metadata |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for candidate in report["candidates"]:
        lines.append(
            "| {decision_hint} | `{minute_token}` | {title} | {sources} | {start_time} | {duration} | {missing} |".format(
                decision_hint=candidate.get("decision_hint") or "",
                minute_token=candidate.get("minute_token") or "",
                title=(candidate.get("title") or "metadata unavailable").replace("|", "\\|"),
                sources=", ".join(candidate.get("sources") or []),
                start_time=candidate.get("start_time") or "metadata unavailable",
                duration=candidate.get("duration") or "metadata unavailable",
                missing=", ".join(candidate.get("metadata_unavailable") or []),
            )
        )
    if report["duplicate_hints"]:
        lines.extend(["", "## Duplicate Hints", ""])
        lines.extend(f"- `{json.dumps(hint, ensure_ascii=False)}`" for hint in report["duplicate_hints"])
    lines.extend(
        [
            "",
            "## Selection",
            "",
            "Write one selected `minute_token` per line to `selected.txt`, then run export.",
        ]
    )
    return "\n".join(lines) + "\n"


def handle_audit(args: argparse.Namespace) -> int:
    require_commands(["lark-cli"])
    start, end = parse_date_window(args.start, args.end, args.days)
    base = args.run.expanduser().resolve()
    raw = base / "raw"
    logs = base / "logs"
    raw.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    eprint(f"audit range: {start}..{end}")
    vc_items = run_paginated(
        ["lark-cli", "vc", "+search", "--start", start, "--end", end, "--page-size", str(args.page_size)],
        cwd=base,
        page_dir=raw / "vc-search-pages",
        log_dir=logs / "vc-search-pages",
    )
    write_json(raw / "vc-search.json", {"ok": True, "data": {"items": vc_items, "has_more": False}})
    meeting_ids = [str(item.get("id")) for item in vc_items if item.get("id")]
    write_text(raw / "meeting-ids.txt", "".join(f"{value}\n" for value in meeting_ids))

    owner_items = run_paginated(
        [
            "lark-cli",
            "minutes",
            "+search",
            "--owner-ids",
            "me",
            "--start",
            start,
            "--end",
            end,
            "--page-size",
            str(args.page_size),
        ],
        cwd=base,
        page_dir=raw / "minutes-owner-pages",
        log_dir=logs / "minutes-owner-pages",
    )
    write_json(raw / "minutes-owner.json", {"ok": True, "data": {"items": owner_items, "has_more": False}})

    participant_items = run_paginated(
        [
            "lark-cli",
            "minutes",
            "+search",
            "--participant-ids",
            "me",
            "--start",
            start,
            "--end",
            end,
            "--page-size",
            str(args.page_size),
        ],
        cwd=base,
        page_dir=raw / "minutes-participant-pages",
        log_dir=logs / "minutes-participant-pages",
    )
    write_json(raw / "minutes-participant.json", {"ok": True, "data": {"items": participant_items, "has_more": False}})

    vc_notes: list[dict[str, Any]] = []
    for index, batch in enumerate(chunks(meeting_ids, 50), start=1):
        if not batch:
            continue
        payload = run_json(
            ["lark-cli", "vc", "+notes", "--meeting-ids", ",".join(batch), "--format", "json"],
            cwd=base,
            log=raw / "vc-note-batches" / f"ids-{index:03d}.log",
        )
        write_json(raw / "vc-note-batches" / f"ids-{index:03d}.json", payload)
        vc_notes.extend(payload.get("data", {}).get("notes") or [])
    write_json(raw / "vc-notes.json", {"ok": True, "data": {"notes": vc_notes}})

    candidates: dict[str, dict[str, Any]] = {}
    for item in owner_items:
        if item.get("token"):
            merge_candidate(candidates, candidate_from_token(str(item["token"]), source="minutes_owner", item=item))
    for item in participant_items:
        if item.get("token"):
            merge_candidate(
                candidates, candidate_from_token(str(item["token"]), source="minutes_participant", item=item)
            )
    for note in vc_notes:
        token = str(note.get("minute_token") or "")
        if token:
            merge_candidate(
                candidates,
                candidate_from_token(
                    token,
                    source="vc_notes",
                    item=note,
                    meeting_id=str(note.get("meeting_id") or ""),
                ),
            )

    candidate_list = sorted(candidates.values(), key=lambda item: (item.get("title") or "", item["minute_token"]))
    duplicate_hints = build_candidate_duplicate_hints(candidate_list)
    apply_candidate_decision_hints(candidate_list, duplicate_hints)
    report = {
        "ok": True,
        "run": {"start": start, "end": end, "dir": str(base)},
        "summary": {
            "vc_meetings": len(meeting_ids),
            "minutes_owned": len(owner_items),
            "minutes_participated": len(participant_items),
            "minute_candidates": len(candidate_list),
            "duplicate_hint_groups": len(duplicate_hints),
        },
        "candidates": candidate_list,
        "duplicate_hints": duplicate_hints,
        "stop_points": [
            "Read audit.md/audit.json only; do not open stt/**/transcript.txt during audit.",
            "Write selected minute tokens to selected.txt before export.",
        ],
    }
    write_json(base / "audit.json", report)
    write_text(base / "audit.md", audit_markdown(report))
    emit(report, fmt=args.format)
    return 0


def token_file_values(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def parse_tokens(args: argparse.Namespace, base: Path) -> list[str]:
    tokens: list[str] = []
    if args.tokens:
        tokens.extend(part.strip() for part in args.tokens.replace("\n", ",").split(","))
    if tokens:
        return unique([token for token in tokens if token and not token.startswith("#")])

    if args.all_audited:
        audit_path = args.audit or (base / "audit.json")
        data = load_json(audit_path)
        return unique(
            [str(item.get("minute_token")) for item in data.get("candidates", []) if item.get("minute_token")]
        )

    selected = args.selected or (base / "selected.txt")
    if selected.exists():
        return unique(token_file_values(selected))
    raise SystemExit("provide --tokens, create RUN/selected.txt, pass --selected, or use --all-audited")


def load_audit_candidates(base: Path) -> dict[str, dict[str, Any]]:
    audit_path = base / "audit.json"
    if not audit_path.exists():
        return {}
    audit = load_json(audit_path)
    return {
        str(candidate.get("minute_token")): candidate
        for candidate in audit.get("candidates", [])
        if candidate.get("minute_token")
    }


def build_transcript_duplicate_hints(transcripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_sha: dict[str, list[str]] = {}
    by_first_line: dict[str, list[str]] = {}
    by_prefix: dict[str, list[str]] = {}
    for transcript in transcripts:
        by_sha.setdefault(transcript["sha256"], []).append(transcript["rel_path"])
        if transcript["first_line"]:
            by_first_line.setdefault(transcript["first_line"], []).append(transcript["rel_path"])
        by_prefix.setdefault(transcript["prefix_sha256"], []).append(transcript["rel_path"])
    duplicate_hints = [
        {"kind": "same_transcript_sha256", "files": files} for files in by_sha.values() if len(files) > 1
    ]
    duplicate_hints += [
        {"kind": "same_transcript_first_line", "first_line": first_line, "files": files}
        for first_line, files in by_first_line.items()
        if len(files) > 1
    ]
    duplicate_hints += [
        {"kind": "same_transcript_prefix", "files": files} for files in by_prefix.values() if len(files) > 1
    ]
    return duplicate_hints


def duplicate_recommendation(files: list[str], transcripts: list[dict[str, Any]]) -> dict[str, Any]:
    by_file = {item["rel_path"]: item for item in transcripts}

    def score(rel_path: str) -> tuple[int, int, int]:
        item = by_file.get(rel_path) or {}
        sources = item.get("sources") or []
        return (
            1 if "vc_notes" in sources else 0,
            len(sources),
            1 if item.get("title") else 0,
        )

    keep = sorted(files, key=score, reverse=True)[0]
    return {
        "recommended_keep": keep,
        "recommended_exclude": [file for file in files if file != keep],
        "reason": "prefer vc_notes source, then richer source coverage, then titled transcript",
    }


def decisions_markdown(
    *,
    selected_tokens: list[str],
    errors: list[dict[str, Any]],
    duplicate_hints: list[dict[str, Any]],
    transcripts: list[dict[str, Any]],
    stale: list[str],
    unselected_artifacts: list[dict[str, Any]],
) -> str:
    lines = [
        "# Lark Meeting STT Decisions",
        "",
        "Generated from export metadata only. Do not open `stt/**/transcript.txt` for selection decisions.",
        "",
        "## Coverage",
        "",
        f"- selected_minute_tokens: {len(selected_tokens)}",
        f"- exported_transcripts: {len(transcripts)}",
        f"- errors: {len(errors)}",
        f"- duplicate_hint_groups: {len(duplicate_hints)}",
        f"- stale_transcript_artifacts: {len(stale)}",
        f"- unselected_transcript_artifacts: {len(unselected_artifacts)}",
        "",
    ]
    if errors:
        lines.extend(["## Excluded", ""])
        for error in errors:
            token = error.get("minute_token") or error.get("token") or ""
            reason = error.get("error") or error.get("hint") or "unknown"
            lines.append(f"- `{token}`: {reason}")
        lines.append("")
    if duplicate_hints:
        lines.extend(["## Duplicate Hints", ""])
        for hint in duplicate_hints:
            recommendation = hint.get("recommendation") or {}
            lines.append(f"- `{hint.get('kind')}`: `{json.dumps(hint, ensure_ascii=False)}`")
            if recommendation:
                lines.append(f"  - keep: `{recommendation.get('recommended_keep')}`")
        lines.append("")
    if stale:
        lines.extend(["## Stale Transcript Artifacts", ""])
        lines.extend(f"- `{path}`" for path in stale)
        lines.append("")
    if unselected_artifacts:
        lines.extend(["## Unselected Transcript Artifacts", ""])
        for artifact in unselected_artifacts:
            lines.append(f"- `{json.dumps(artifact, ensure_ascii=False)}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def handle_export(args: argparse.Namespace) -> int:
    require_commands(["lark-cli"])
    base = args.run.expanduser().resolve()
    tokens = parse_tokens(args, base)
    if not tokens:
        raise SystemExit("no minute tokens selected")
    selected_set = set(tokens)
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    encoding = token_encoder(args.encoding)
    audit_candidates = load_audit_candidates(base)

    raw = base / "raw"
    logs = base / "logs"
    stt = base / "stt"
    raw.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    stt.mkdir(parents=True, exist_ok=True)
    write_text(base / "selected.txt", "".join(f"{token}\n" for token in tokens))

    notes: list[dict[str, Any]] = []
    for index, batch in enumerate(chunks(tokens, args.batch_size), start=1):
        eprint(f"export batch {index}: {len(batch)} token(s)")
        cmd = [
            "lark-cli",
            "vc",
            "+notes",
            "--minute-tokens",
            ",".join(batch),
            "--output-dir",
            "./stt",
            "--format",
            "json",
        ]
        if args.overwrite:
            cmd.append("--overwrite")
        payload = run_json(cmd, cwd=base, log=logs / f"export-stt-{index:03d}.log")
        write_json(raw / "minute-note-batches" / f"tokens-{index:03d}.json", payload)
        notes.extend(payload.get("data", {}).get("notes") or [])
    write_json(raw / "minute-notes.json", {"ok": True, "data": {"notes": notes}})

    note_meta: dict[str, dict[str, str]] = {}
    errors: list[dict[str, Any]] = []
    unselected_artifacts: list[dict[str, Any]] = []
    for note in notes:
        if note.get("error"):
            note_token = str(note.get("minute_token") or note.get("token") or "")
            if not note_token or note_token in selected_set:
                errors.append(note)
            continue
        note_token = str(note.get("minute_token") or "")
        transcript_file = (note.get("artifacts") or {}).get("transcript_file")
        if transcript_file:
            if note_token not in selected_set:
                unselected_artifacts.append(
                    {
                        "minute_token": note_token,
                        "transcript_file": str(transcript_file),
                        "reason": "artifact_not_in_current_selection",
                    }
                )
                continue
            note_meta[str(transcript_file)] = {
                "title": str(note.get("title") or ""),
                "minute_token": note_token,
            }

    current_transcript_rels = sorted(note_meta)
    stale = sorted(
        path.relative_to(base).as_posix()
        for path in stt.glob("**/transcript.txt")
        if path.relative_to(base).as_posix() not in current_transcript_rels
    )

    transcripts: list[dict[str, Any]] = []
    for rel in current_transcript_rels:
        path = base / rel
        if not path.exists():
            errors.append({"transcript_file": rel, "error": "transcript_file_missing_after_export"})
            continue
        rel = path.relative_to(base).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        slug = path.parent.name
        meta = note_meta.get(rel, {})
        minute_token = meta.get("minute_token") or ""
        if minute_token not in selected_set:
            unselected_artifacts.append(
                {
                    "minute_token": minute_token or token_from_slug(slug),
                    "transcript_file": rel,
                    "reason": "transcript_not_in_current_selection",
                }
            )
            continue
        audit_candidate = audit_candidates.get(minute_token, {})
        transcripts.append(
            {
                "minute_token": minute_token,
                "title": meta.get("title") or audit_candidate.get("title") or "",
                "rel_path": rel,
                "slug": slug,
                "sources": audit_candidate.get("sources") or [],
                "meeting_ids": audit_candidate.get("meeting_ids") or [],
                "bytes": path.stat().st_size,
                "line_count": len(lines),
                "first_line": lines[0] if lines else "",
                "sha256": sha256_file(path),
                "prefix_sha256": transcript_prefix_hash(text),
                "token_count": token_count(text, encoding=encoding),
            }
        )

    exported_tokens = {transcript["minute_token"] for transcript in transcripts}
    errored_tokens = {str(error.get("minute_token") or error.get("token") or "") for error in errors}
    for token in tokens:
        if token not in exported_tokens and token not in errored_tokens:
            errors.append({"minute_token": token, "error": "selected_token_missing_transcript_after_export"})

    duplicate_hints = build_transcript_duplicate_hints(transcripts)
    for hint in duplicate_hints:
        files = hint.get("files") or []
        if files:
            hint["recommendation"] = duplicate_recommendation(files, transcripts)
    excluded = [
        {
            "minute_token": error.get("minute_token") or error.get("token") or "",
            "reason": error.get("error") or error.get("hint") or "unknown",
        }
        for error in errors
    ]
    report = {
        "ok": True,
        "summary": {
            "selected_minute_tokens": len(tokens),
            "exported_transcripts": len(transcripts),
            "errors": len(errors),
            "duplicate_hint_groups": len(duplicate_hints),
            "stale_transcript_artifacts": len(stale),
            "unselected_transcript_artifacts": len(unselected_artifacts),
        },
        "run": {"dir": str(base)},
        "encoding": args.encoding,
        "transcripts": transcripts,
        "duplicate_hints": duplicate_hints,
        "errors": errors,
        "excluded": excluded,
        "stale_transcript_artifacts": stale,
        "unselected_transcript_artifacts": unselected_artifacts,
        "stop_points": [
            "Inspect transcripts.json metadata only; do not open stt/**/transcript.txt.",
            "Render prompts only after duplicate and error decisions are made.",
        ],
    }
    write_json(base / "transcripts.json", report)
    write_text(base / "excluded.txt", "".join(f"{item['minute_token']}\t{item['reason']}\n" for item in excluded))
    write_text(
        base / "dedupe.md",
        decisions_markdown(
            selected_tokens=tokens,
            errors=[],
            duplicate_hints=duplicate_hints,
            transcripts=transcripts,
            stale=[],
            unselected_artifacts=[],
        ),
    )
    write_text(
        base / "decisions.md",
        decisions_markdown(
            selected_tokens=tokens,
            errors=errors,
            duplicate_hints=duplicate_hints,
            transcripts=transcripts,
            stale=stale,
            unselected_artifacts=unselected_artifacts,
        ),
    )
    emit(report, fmt=args.format)
    return 0


def render_prompt(
    *,
    template_path: Path,
    transcript: dict[str, Any],
    transcript_text: str,
    start: str,
    end: str,
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)
    return template.render(
        transcript=transcript_text,
        run={"start": start, "end": end},
        meeting={
            "title": transcript.get("title") or "",
        },
    )


def handle_render(args: argparse.Namespace) -> int:
    if not args.template.exists():
        raise SystemExit(f"template not found: {args.template}")
    if args.max_input_tokens < 1:
        raise SystemExit("--max-input-tokens must be >= 1")
    base = args.run.expanduser().resolve()
    transcripts_path = (args.transcripts or (base / "transcripts.json")).expanduser().resolve()
    prompts_dir = (args.prompts or (base / "prompts")).expanduser().resolve()
    prompts_index = prompts_dir.parent / f"{prompts_dir.name}.json"
    start, end = render_date_window(args, base)
    encoding = token_encoder(args.encoding)
    data = load_json(transcripts_path)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    prompts: list[dict[str, Any]] = []
    skipped_oversized: list[dict[str, Any]] = []
    for transcript in data.get("transcripts", []):
        transcript_path = transcripts_path.parent / transcript["rel_path"]
        transcript_text = transcript_path.read_text(encoding="utf-8", errors="replace")
        rendered = render_prompt(
            template_path=args.template,
            transcript=transcript,
            transcript_text=transcript_text,
            start=start,
            end=end,
        )
        prompt_token_count = token_count(rendered, encoding=encoding)
        prompt_path = prompts_dir / f"{transcript['slug']}.prompt.md"
        row = {
            "minute_token": transcript.get("minute_token") or "",
            "title": transcript.get("title") or "",
            "source_transcript": transcript.get("rel_path") or str(transcript_path),
            "token_count": prompt_token_count,
            "max_input_tokens": args.max_input_tokens,
        }
        if prompt_token_count > args.max_input_tokens:
            skipped_oversized.append({**row, "reason": "rendered_prompt_exceeds_max_input_tokens"})
            continue
        write_text(prompt_path, rendered)
        prompts.append(
            {
                **row,
                "path": str(prompt_path),
                "rel_path": prompt_path.relative_to(base).as_posix()
                if prompt_path.is_relative_to(base)
                else str(prompt_path),
                "bytes": prompt_path.stat().st_size,
            }
        )

    report = {
        "ok": not skipped_oversized,
        "summary": {
            "source_transcripts": len(data.get("transcripts", [])),
            "rendered_prompts": len(prompts),
            "skipped_oversized": len(skipped_oversized),
        },
        "template": str(args.template),
        "encoding": args.encoding,
        "max_input_tokens": args.max_input_tokens,
        "index": str(prompts_index),
        "prompts": prompts,
        "skipped_oversized": skipped_oversized,
        "stop_points": [
            "Run Amp outside this CLI using prompt files under the token budget.",
            "If skipped_oversized is non-empty, do not open transcript text; reduce selected.txt or split that meeting.",
        ],
    }
    write_json(prompts_index, report)
    emit(report, fmt=args.format)
    if skipped_oversized:
        eprint(
            "render failed: at least one prompt exceeds --max-input-tokens. "
            "Do not open transcript text; reduce selected.txt or split the oversized meeting."
        )
        return 1
    return 0


def handle_summarize(args: argparse.Namespace) -> int:
    require_commands(["amp"])
    if args.timeout_seconds < 1:
        raise SystemExit("--timeout-seconds must be >= 1")
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    base = args.run.expanduser().resolve()
    prompts_path = (args.prompts or (base / "prompts.json")).expanduser().resolve()
    summaries_dir = (args.summaries or (base / "summaries")).expanduser().resolve()
    prompts_data = load_json(prompts_path)
    summaries_dir.mkdir(parents=True, exist_ok=True)
    index_path = summaries_dir / "index.jsonl"

    prompts = prompts_data.get("prompts", [])
    if not isinstance(prompts, list):
        raise SystemExit(f"invalid prompts file: {prompts_path}: prompts must be a list")
    jsonl_lock = threading.Lock()

    def append_event(payload: dict[str, Any]) -> None:
        with jsonl_lock:
            append_jsonl(index_path, payload)

    def summarize_one(prompt: dict[str, Any]) -> dict[str, Any]:
        prompt_path = Path(prompt["path"])
        summary_path = summaries_dir / (prompt_path.name.removesuffix(".prompt.md") + ".summary.md")
        started_at = dt.datetime.now().isoformat(timespec="seconds")
        started = time.time()
        start_event = {
            "event": "started",
            "started_at": started_at,
            "prompt": str(prompt_path),
            "summary": str(summary_path),
            "minute_token": prompt.get("minute_token") or "",
            "title": prompt.get("title") or "",
            "token_count": prompt.get("token_count"),
        }
        append_event(start_event)
        eprint(f"summarizing {prompt_path.name} tokens={prompt.get('token_count')}")
        cmd = [
            "amp",
            "--execute",
            "--visibility",
            args.amp_visibility,
            "--mode",
            args.amp_mode,
            "--effort",
            args.amp_effort,
            "--no-ide",
            "--no-color",
        ]
        try:
            proc = subprocess.run(
                cmd,
                input=prompt_path.read_text(encoding="utf-8"),
                text=True,
                capture_output=True,
                timeout=args.timeout_seconds,
                check=False,
                cwd=base,
            )
            exit_code = proc.returncode
            timed_out = False
            stderr = proc.stderr
            if exit_code == 0:
                tmp = summary_path.with_suffix(summary_path.suffix + ".tmp")
                write_text(tmp, proc.stdout)
                tmp.replace(summary_path)
            elif summary_path.exists():
                summary_path.unlink()
        except subprocess.TimeoutExpired:
            exit_code = 124
            timed_out = True
            stderr = f"amp timed out after {args.timeout_seconds}s"
            if summary_path.exists():
                summary_path.unlink()
        completed = {
            **start_event,
            "event": "completed",
            "completed_at": dt.datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": round(time.time() - started, 3),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "output_bytes": summary_path.stat().st_size if summary_path.exists() else 0,
            "stderr": stderr.strip(),
        }
        append_event(completed)
        return completed

    workers = min(args.concurrency, len(prompts)) if prompts else 0
    results: list[dict[str, Any]] = []
    if workers:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_prompt = {executor.submit(summarize_one, prompt): prompt for prompt in prompts}
            for future in concurrent.futures.as_completed(future_to_prompt):
                results.append(future.result())

    failures = [result for result in results if result["exit_code"] != 0]
    report = {
        "ok": not failures,
        "summary": {
            "prompts": len(results),
            "summaries": len(results) - len(failures),
            "failures": len(failures),
            "concurrency": args.concurrency,
        },
        "index": str(index_path),
        "results": results,
    }
    write_json(summaries_dir / "index.json", report)
    emit(report, fmt=args.format)
    return 1 if failures else 0


def main() -> int:
    args = parse_args()
    if args.command == "audit":
        return handle_audit(args)
    if args.command == "export":
        return handle_export(args)
    if args.command == "render":
        return handle_render(args)
    if args.command == "summarize":
        return handle_summarize(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
