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
DEFAULT_MAX_PROMPT_TIKTOKEN_COUNT = 100_000
SELECTED_MINUTES_FILE = "selected-minutes.txt"
TRANSCRIPT_INDEX_FILE = "transcript-index.json"
PROMPT_INDEX_FILE = "prompt-index.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit, export, and render Lark meeting raw STT.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    audit = subcommands.add_parser("audit", help="Discover audited minutes without reading STT full text.")
    audit.add_argument("--start", help="Start date, YYYY-MM-DD.")
    audit.add_argument("--end", help="End date, YYYY-MM-DD.")
    audit.add_argument("--days", type=int, default=2, help="Date window ending today when --start/--end are omitted.")
    audit.add_argument("--run", type=Path, required=True, help="Run directory. Writes audit.json and audit.md.")
    audit.add_argument("--page-size", type=int, default=30, help="lark-cli page size for each search request.")
    audit.add_argument("--format", choices=("json", "md"), default="json", help="Stdout format.")

    export = subcommands.add_parser("export", help="Export selected raw STT and write metadata-only transcript index.")
    export.add_argument(
        "--run",
        type=Path,
        required=True,
        help=f"Run directory. Reads {SELECTED_MINUTES_FILE} and writes {TRANSCRIPT_INDEX_FILE}.",
    )
    export.add_argument("--minute-ids", help="Comma/newline separated Lark minute IDs.")
    export.add_argument(
        "--selected-minutes",
        type=Path,
        help=f"Selected minute ID file. Defaults to RUN/{SELECTED_MINUTES_FILE}.",
    )
    export.add_argument(
        "--all-audited-minutes", action="store_true", help="Export every audited minute from audit.json."
    )
    export.add_argument("--audit", type=Path, help="Audit JSON for --all-audited-minutes. Defaults to RUN/audit.json.")
    export.add_argument("--batch-size", type=int, default=50, help="Minute IDs per lark-cli export request.")
    export.add_argument("--overwrite", action="store_true", help="Overwrite existing exported STT artifacts.")
    export.add_argument(
        "--encoding",
        default=DEFAULT_ENCODING,
        help="tiktoken encoding for transcript_tiktoken_count.",
    )
    export.add_argument("--format", choices=("json", "md"), default="json", help="Stdout format.")

    render = subcommands.add_parser("render", help="Render prompts from exported STT with a tiktoken hard gate.")
    render.add_argument(
        "--run",
        type=Path,
        required=True,
        help=f"Run directory. Defaults to RUN/{TRANSCRIPT_INDEX_FILE}, RUN/prompts, and RUN/{PROMPT_INDEX_FILE}.",
    )
    render.add_argument(
        "--transcript-index",
        type=Path,
        help=f"{TRANSCRIPT_INDEX_FILE} from export. Defaults to RUN/{TRANSCRIPT_INDEX_FILE}.",
    )
    render.add_argument("--prompt-dir", type=Path, help="Prompt output directory. Defaults to RUN/prompts.")
    render.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE, help="Jinja prompt template.")
    render.add_argument("--start", help="Start date for template metadata, YYYY-MM-DD.")
    render.add_argument("--end", help="End date for template metadata, YYYY-MM-DD.")
    render.add_argument(
        "--max-prompt-tiktoken-count",
        type=int,
        default=DEFAULT_MAX_PROMPT_TIKTOKEN_COUNT,
        help="Hard tiktoken gate for each rendered prompt.",
    )
    render.add_argument("--encoding", default=DEFAULT_ENCODING, help="tiktoken encoding.")
    render.add_argument("--format", choices=("json", "md"), default="json", help="Stdout format.")

    summarize = subcommands.add_parser("summarize", help="Run Amp for rendered prompts with progress JSONL.")
    summarize.add_argument("--run", type=Path, required=True, help=f"Run directory. Reads RUN/{PROMPT_INDEX_FILE}.")
    summarize.add_argument(
        "--prompt-index", type=Path, help=f"{PROMPT_INDEX_FILE} from render. Defaults to RUN/{PROMPT_INDEX_FILE}."
    )
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
        "duplicate_warnings",
        "errors",
        "excluded",
        "stale_exported_files",
        "unexpected_exported_files",
        "skipped_oversized_prompts",
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
        return parse_date_window(args.start, args.end, 1)
    audit_path = base / "audit.json"
    if audit_path.exists():
        audit = load_json(audit_path)
        run = audit.get("run") or {}
        if run.get("start") and run.get("end"):
            return str(run["start"]), str(run["end"])
    raise SystemExit(f"missing {audit_path}; pass --start and --end or run audit first")


def validate_date(value: str) -> None:
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def tiktoken_encoder(name: str) -> tiktoken.Encoding:
    try:
        return tiktoken.get_encoding(name)
    except ValueError as exc:
        raise SystemExit(f"unknown tiktoken encoding {name!r}") from exc


def count_tiktoken(text: str, *, encoding: tiktoken.Encoding) -> int:
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
    pagination_page_token = ""
    page = 1
    while True:
        cmd = [*base_cmd, "--format", "json"]
        if pagination_page_token:
            cmd.extend(["--page-token", pagination_page_token])
        eprint(f"page {page}: {' '.join(base_cmd)}")
        payload = run_json(cmd, cwd=cwd, log=log_dir / f"page-{page}.log")
        write_json(page_dir / f"page-{page}.json", payload)
        items.extend(payload.get("data", {}).get("items") or [])
        if payload.get("data", {}).get("has_more") is not True:
            return items
        pagination_page_token = payload.get("data", {}).get("page_token") or ""
        if not pagination_page_token:
            raise RuntimeError(f"has_more=true but pagination page_token is empty for {' '.join(base_cmd)}")
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


def audited_minute_from_lark_token(
    lark_minute_token: str,
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
        "minute_id": lark_minute_token,
        "title": title,
        "sources": [source],
        "meeting_ids": [meeting_id] if meeting_id else [],
        "start_time": start_time,
        "duration": duration,
        "metadata_unavailable": unavailable,
        "selection_status": "selectable",
    }


def merge_audited_minute(audited_minutes: dict[str, dict[str, Any]], audited_minute: dict[str, Any]) -> None:
    minute_id = audited_minute["minute_id"]
    existing = audited_minutes.setdefault(minute_id, audited_minute)
    if existing is audited_minute:
        return
    existing["sources"] = unique([*existing.get("sources", []), *audited_minute.get("sources", [])])
    existing["meeting_ids"] = unique([*existing.get("meeting_ids", []), *audited_minute.get("meeting_ids", [])])
    for key in ("title", "start_time", "duration"):
        if not existing.get(key) and audited_minute.get(key):
            existing[key] = audited_minute[key]
    existing["metadata_unavailable"] = [
        field for field in ("title", "start_time", "duration") if not existing.get(field)
    ]


def build_audit_duplicate_warnings(audited_minutes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_signature: dict[str, list[str]] = {}
    for audited_minute in audited_minutes:
        title = normalize_title(audited_minute.get("title") or "")
        start = audited_minute.get("start_time") or ""
        duration = audited_minute.get("duration") or ""
        signature = "|".join(str(part) for part in (title, start, duration) if part)
        if signature:
            by_signature.setdefault(signature, []).append(audited_minute["minute_id"])
    return [
        {"kind": "same_title_time_duration", "signature": signature, "minute_ids": minute_ids}
        for signature, minute_ids in by_signature.items()
        if len(minute_ids) > 1
    ]


def apply_audit_selection_status(
    audited_minutes: list[dict[str, Any]], duplicate_warnings: list[dict[str, Any]]
) -> None:
    duplicate_minute_ids = {minute_id for warning in duplicate_warnings for minute_id in warning.get("minute_ids", [])}
    for audited_minute in audited_minutes:
        audited_minute["selection_status"] = (
            "needs_duplicate_review" if audited_minute["minute_id"] in duplicate_minute_ids else "selectable"
        )


def audit_markdown(report: dict[str, Any]) -> str:
    run = report["run"]
    summary = report["summary"]
    lines = [
        "# Lark Meeting STT Audit",
        "",
        "Select minute IDs from this audit only. Do not open `stt/**/transcript.txt` during audit.",
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
            "## Audited Minutes",
            "",
            "| selection_status | minute_id | title | sources | start_time | duration | missing_metadata |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for audited_minute in report["audited_minutes"]:
        lines.append(
            "| {selection_status} | `{minute_id}` | {title} | {sources} | {start_time} | {duration} | {missing} |".format(
                selection_status=audited_minute.get("selection_status") or "",
                minute_id=audited_minute.get("minute_id") or "",
                title=(audited_minute.get("title") or "metadata unavailable").replace("|", "\\|"),
                sources=", ".join(audited_minute.get("sources") or []),
                start_time=audited_minute.get("start_time") or "metadata unavailable",
                duration=audited_minute.get("duration") or "metadata unavailable",
                missing=", ".join(audited_minute.get("metadata_unavailable") or []),
            )
        )
    if report["duplicate_warnings"]:
        lines.extend(["", "## Duplicate Warnings", ""])
        lines.extend(f"- `{json.dumps(warning, ensure_ascii=False)}`" for warning in report["duplicate_warnings"])
    lines.extend(
        [
            "",
            "## Selection",
            "",
            f"Write one selected `minute_id` per line to `{SELECTED_MINUTES_FILE}`, then run export.",
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

    vc_note_links: list[dict[str, Any]] = []
    for index, batch in enumerate(chunks(meeting_ids, 50), start=1):
        if not batch:
            continue
        payload = run_json(
            ["lark-cli", "vc", "+notes", "--meeting-ids", ",".join(batch), "--format", "json"],
            cwd=base,
            log=raw / "vc-minute-link-batches" / f"meeting-ids-{index:03d}.log",
        )
        write_json(raw / "vc-minute-link-batches" / f"meeting-ids-{index:03d}.json", payload)
        vc_note_links.extend(payload.get("data", {}).get("notes") or [])
    write_json(raw / "vc-minute-links.json", {"ok": True, "data": {"minute_links": vc_note_links}})

    audited_minutes: dict[str, dict[str, Any]] = {}
    for item in owner_items:
        if item.get("token"):
            merge_audited_minute(
                audited_minutes,
                audited_minute_from_lark_token(str(item["token"]), source="minutes_owner_search", item=item),
            )
    for item in participant_items:
        if item.get("token"):
            merge_audited_minute(
                audited_minutes,
                audited_minute_from_lark_token(str(item["token"]), source="minutes_participant_search", item=item),
            )
    for minute_link in vc_note_links:
        lark_minute_token = str(minute_link.get("minute_token") or "")
        if lark_minute_token:
            merge_audited_minute(
                audited_minutes,
                audited_minute_from_lark_token(
                    lark_minute_token,
                    source="vc_minute_lookup",
                    item=minute_link,
                    meeting_id=str(minute_link.get("meeting_id") or ""),
                ),
            )

    audited_minute_list = sorted(
        audited_minutes.values(), key=lambda item: (item.get("title") or "", item["minute_id"])
    )
    duplicate_warnings = build_audit_duplicate_warnings(audited_minute_list)
    apply_audit_selection_status(audited_minute_list, duplicate_warnings)
    report = {
        "ok": True,
        "run": {"start": start, "end": end, "dir": str(base)},
        "summary": {
            "vc_meetings": len(meeting_ids),
            "minutes_owned": len(owner_items),
            "minutes_participated": len(participant_items),
            "audited_minutes": len(audited_minute_list),
            "duplicate_warning_groups": len(duplicate_warnings),
        },
        "audited_minutes": audited_minute_list,
        "duplicate_warnings": duplicate_warnings,
        "stop_points": [
            "Read audit.md/audit.json only; do not open stt/**/transcript.txt during audit.",
            f"Write selected minute IDs to {SELECTED_MINUTES_FILE} before export.",
        ],
    }
    write_json(base / "audit.json", report)
    write_text(base / "audit.md", audit_markdown(report))
    emit(report, fmt=args.format)
    return 0


def selected_minute_file_values(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def parse_selected_minute_ids(args: argparse.Namespace, base: Path) -> list[str]:
    minute_ids: list[str] = []
    if args.minute_ids:
        minute_ids.extend(part.strip() for part in args.minute_ids.replace("\n", ",").split(","))
    if minute_ids:
        return unique([minute_id for minute_id in minute_ids if minute_id and not minute_id.startswith("#")])

    if args.all_audited_minutes:
        audit_path = args.audit or (base / "audit.json")
        data = load_json(audit_path)
        return unique([str(item.get("minute_id")) for item in data.get("audited_minutes", []) if item.get("minute_id")])

    selected_minutes = args.selected_minutes or (base / SELECTED_MINUTES_FILE)
    if selected_minutes.exists():
        return unique(selected_minute_file_values(selected_minutes))
    raise SystemExit(
        f"provide --minute-ids, create RUN/{SELECTED_MINUTES_FILE}, pass --selected-minutes, "
        "or use --all-audited-minutes"
    )


def load_audited_minutes(base: Path) -> dict[str, dict[str, Any]]:
    audit_path = base / "audit.json"
    if not audit_path.exists():
        return {}
    audit = load_json(audit_path)
    return {
        str(audited_minute.get("minute_id")): audited_minute
        for audited_minute in audit.get("audited_minutes", [])
        if audited_minute.get("minute_id")
    }


def build_transcript_duplicate_warnings(transcripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_sha: dict[str, list[str]] = {}
    by_first_line: dict[str, list[str]] = {}
    by_prefix: dict[str, list[str]] = {}
    for transcript in transcripts:
        by_sha.setdefault(transcript["sha256"], []).append(transcript["rel_path"])
        if transcript["first_line"]:
            by_first_line.setdefault(transcript["first_line"], []).append(transcript["rel_path"])
        by_prefix.setdefault(transcript["prefix_sha256"], []).append(transcript["rel_path"])
    duplicate_warnings = [
        {"kind": "same_transcript_sha256", "files": files} for files in by_sha.values() if len(files) > 1
    ]
    duplicate_warnings += [
        {"kind": "same_transcript_first_line", "first_line": first_line, "files": files}
        for first_line, files in by_first_line.items()
        if len(files) > 1
    ]
    duplicate_warnings += [
        {"kind": "same_transcript_prefix", "files": files} for files in by_prefix.values() if len(files) > 1
    ]
    return duplicate_warnings


def duplicate_recommendation(files: list[str], transcripts: list[dict[str, Any]]) -> dict[str, Any]:
    by_file = {item["rel_path"]: item for item in transcripts}

    def score(rel_path: str) -> tuple[int, int, int]:
        item = by_file.get(rel_path) or {}
        sources = item.get("sources") or []
        return (
            1 if "vc_minute_lookup" in sources else 0,
            len(sources),
            1 if item.get("title") else 0,
        )

    keep = sorted(files, key=score, reverse=True)[0]
    return {
        "recommended_keep": keep,
        "recommended_exclude": [file for file in files if file != keep],
        "reason": "rank vc_minute_lookup source first, then richer source coverage, then titled transcript",
    }


def decisions_markdown(
    *,
    selected_minute_ids: list[str],
    errors: list[dict[str, Any]],
    duplicate_warnings: list[dict[str, Any]],
    transcripts: list[dict[str, Any]],
    stale_exported_files: list[str],
    unexpected_exported_files: list[dict[str, Any]],
) -> str:
    lines = [
        "# Lark Meeting STT Decisions",
        "",
        "Export metadata supplies these decisions. Do not open `stt/**/transcript.txt` for selection decisions.",
        "",
        "## Coverage",
        "",
        f"- selected_minutes: {len(selected_minute_ids)}",
        f"- exported_transcripts: {len(transcripts)}",
        f"- errors: {len(errors)}",
        f"- duplicate_warning_groups: {len(duplicate_warnings)}",
        f"- stale_exported_files: {len(stale_exported_files)}",
        f"- unexpected_exported_files: {len(unexpected_exported_files)}",
        "",
    ]
    if errors:
        lines.extend(["## Excluded", ""])
        for error in errors:
            minute_id = error.get("minute_id") or ""
            reason = error.get("error") or error.get("recovery_hint") or "unknown"
            lines.append(f"- `{minute_id}`: {reason}")
        lines.append("")
    if duplicate_warnings:
        lines.extend(["## Duplicate Warnings", ""])
        for warning in duplicate_warnings:
            recommendation = warning.get("recommendation") or {}
            lines.append(f"- `{warning.get('kind')}`: `{json.dumps(warning, ensure_ascii=False)}`")
            if recommendation:
                lines.append(f"  - keep: `{recommendation.get('recommended_keep')}`")
        lines.append("")
    if stale_exported_files:
        lines.extend(["## Stale Exported Files", ""])
        lines.extend(f"- `{path}`" for path in stale_exported_files)
        lines.append("")
    if unexpected_exported_files:
        lines.extend(["## Unexpected Exported Files", ""])
        for exported_file in unexpected_exported_files:
            lines.append(f"- `{json.dumps(exported_file, ensure_ascii=False)}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_error_from_lark_result(result: dict[str, Any]) -> dict[str, Any]:
    minute_id = str(result.get("minute_token") or "")
    return {
        "minute_id": minute_id,
        "error": result.get("error") or "unknown",
        "recovery_hint": result.get("hint") or "",
    }


def handle_export(args: argparse.Namespace) -> int:
    require_commands(["lark-cli"])
    base = args.run.expanduser().resolve()
    selected_minute_ids = parse_selected_minute_ids(args, base)
    if not selected_minute_ids:
        raise SystemExit("no minute IDs selected")
    selected_set = set(selected_minute_ids)
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    encoding = tiktoken_encoder(args.encoding)
    audited_minutes = load_audited_minutes(base)

    raw = base / "raw"
    logs = base / "logs"
    stt = base / "stt"
    raw.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    stt.mkdir(parents=True, exist_ok=True)
    write_text(base / SELECTED_MINUTES_FILE, "".join(f"{minute_id}\n" for minute_id in selected_minute_ids))

    minute_artifacts: list[dict[str, Any]] = []
    for index, batch in enumerate(chunks(selected_minute_ids, args.batch_size), start=1):
        eprint(f"export batch {index}: {len(batch)} minute ID(s)")
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
        write_json(raw / "minute-artifact-batches" / f"minute-ids-{index:03d}.json", payload)
        minute_artifacts.extend(payload.get("data", {}).get("notes") or [])
    write_json(raw / "minute-artifacts.json", {"ok": True, "data": {"minute_artifacts": minute_artifacts}})

    artifact_meta: dict[str, dict[str, str]] = {}
    errors: list[dict[str, Any]] = []
    unexpected_exported_files: list[dict[str, Any]] = []
    for artifact in minute_artifacts:
        if artifact.get("error"):
            minute_id = str(artifact.get("minute_token") or "")
            if not minute_id or minute_id in selected_set:
                errors.append(export_error_from_lark_result(artifact))
            continue
        minute_id = str(artifact.get("minute_token") or "")
        transcript_file = (artifact.get("artifacts") or {}).get("transcript_file")
        if transcript_file:
            if minute_id not in selected_set:
                unexpected_exported_files.append(
                    {
                        "minute_id": minute_id,
                        "transcript_file": str(transcript_file),
                        "reason": "file_not_requested_by_current_selection",
                    }
                )
                continue
            artifact_meta[str(transcript_file)] = {
                "title": str(artifact.get("title") or ""),
                "minute_id": minute_id,
            }

    current_transcript_rels = sorted(artifact_meta)
    stale_exported_files = sorted(
        path.relative_to(base).as_posix()
        for path in stt.glob("**/transcript.txt")
        if path.relative_to(base).as_posix() not in current_transcript_rels
    )

    transcripts: list[dict[str, Any]] = []
    for rel in current_transcript_rels:
        path = base / rel
        meta = artifact_meta.get(rel, {})
        minute_id = meta.get("minute_id") or ""
        if not path.exists():
            errors.append(
                {
                    "minute_id": minute_id,
                    "transcript_file": rel,
                    "error": "transcript_file_missing_after_export",
                }
            )
            continue
        rel = path.relative_to(base).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        slug = path.parent.name
        if minute_id not in selected_set:
            unexpected_exported_files.append(
                {
                    "minute_id": minute_id,
                    "transcript_file": rel,
                    "reason": "transcript_file_not_requested_by_current_selection",
                }
            )
            continue
        audited_minute = audited_minutes.get(minute_id, {})
        transcripts.append(
            {
                "minute_id": minute_id,
                "title": meta.get("title") or audited_minute.get("title") or "",
                "rel_path": rel,
                "slug": slug,
                "sources": audited_minute.get("sources") or [],
                "meeting_ids": audited_minute.get("meeting_ids") or [],
                "bytes": path.stat().st_size,
                "line_count": len(lines),
                "first_line": lines[0] if lines else "",
                "sha256": sha256_file(path),
                "prefix_sha256": transcript_prefix_hash(text),
                "transcript_tiktoken_count": count_tiktoken(text, encoding=encoding),
            }
        )

    exported_minute_ids = {transcript["minute_id"] for transcript in transcripts}
    failed_minute_ids = {str(error.get("minute_id") or "") for error in errors}
    for minute_id in selected_minute_ids:
        if minute_id not in exported_minute_ids and minute_id not in failed_minute_ids:
            errors.append({"minute_id": minute_id, "error": "selected_minute_missing_transcript_after_export"})

    duplicate_warnings = build_transcript_duplicate_warnings(transcripts)
    for warning in duplicate_warnings:
        files = warning.get("files") or []
        if files:
            warning["recommendation"] = duplicate_recommendation(files, transcripts)
    excluded = [
        {
            "minute_id": error.get("minute_id") or "",
            "reason": error.get("error") or error.get("recovery_hint") or "unknown",
        }
        for error in errors
    ]
    report = {
        "ok": True,
        "summary": {
            "selected_minutes": len(selected_minute_ids),
            "exported_transcripts": len(transcripts),
            "errors": len(errors),
            "duplicate_warning_groups": len(duplicate_warnings),
            "stale_exported_files": len(stale_exported_files),
            "unexpected_exported_files": len(unexpected_exported_files),
        },
        "run": {"dir": str(base)},
        "encoding": args.encoding,
        "transcripts": transcripts,
        "duplicate_warnings": duplicate_warnings,
        "errors": errors,
        "excluded": excluded,
        "stale_exported_files": stale_exported_files,
        "unexpected_exported_files": unexpected_exported_files,
        "stop_points": [
            f"Inspect {TRANSCRIPT_INDEX_FILE} metadata only; do not open stt/**/transcript.txt.",
            "Render prompts only after duplicate and error decisions are made.",
        ],
    }
    write_json(base / TRANSCRIPT_INDEX_FILE, report)
    write_text(
        base / "excluded-minutes.txt",
        "".join(f"{item['minute_id']}\t{item['reason']}\n" for item in excluded),
    )
    write_text(
        base / "duplicate-decisions.md",
        decisions_markdown(
            selected_minute_ids=selected_minute_ids,
            errors=[],
            duplicate_warnings=duplicate_warnings,
            transcripts=transcripts,
            stale_exported_files=[],
            unexpected_exported_files=[],
        ),
    )
    write_text(
        base / "export-decisions.md",
        decisions_markdown(
            selected_minute_ids=selected_minute_ids,
            errors=errors,
            duplicate_warnings=duplicate_warnings,
            transcripts=transcripts,
            stale_exported_files=stale_exported_files,
            unexpected_exported_files=unexpected_exported_files,
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
    if args.max_prompt_tiktoken_count < 1:
        raise SystemExit("--max-prompt-tiktoken-count must be >= 1")
    base = args.run.expanduser().resolve()
    transcript_index_path = (args.transcript_index or (base / TRANSCRIPT_INDEX_FILE)).expanduser().resolve()
    prompt_dir = (args.prompt_dir or (base / "prompts")).expanduser().resolve()
    prompt_index_path = base / PROMPT_INDEX_FILE
    start, end = render_date_window(args, base)
    encoding = tiktoken_encoder(args.encoding)
    data = load_json(transcript_index_path)
    prompt_dir.mkdir(parents=True, exist_ok=True)

    prompts: list[dict[str, Any]] = []
    skipped_oversized_prompts: list[dict[str, Any]] = []
    transcripts = data["transcripts"]
    for transcript in transcripts:
        transcript_path = transcript_index_path.parent / transcript["rel_path"]
        transcript_text = transcript_path.read_text(encoding="utf-8", errors="replace")
        rendered = render_prompt(
            template_path=args.template,
            transcript=transcript,
            transcript_text=transcript_text,
            start=start,
            end=end,
        )
        prompt_tiktoken_count = count_tiktoken(rendered, encoding=encoding)
        prompt_path = prompt_dir / f"{transcript['slug']}.prompt.md"
        row = {
            "minute_id": transcript["minute_id"],
            "title": transcript["title"],
            "source_transcript": transcript["rel_path"],
            "prompt_tiktoken_count": prompt_tiktoken_count,
            "max_prompt_tiktoken_count": args.max_prompt_tiktoken_count,
        }
        if prompt_tiktoken_count > args.max_prompt_tiktoken_count:
            skipped_oversized_prompts.append({**row, "reason": "rendered_prompt_exceeds_max_prompt_tiktoken_count"})
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
        "ok": not skipped_oversized_prompts,
        "summary": {
            "source_transcripts": len(transcripts),
            "rendered_prompts": len(prompts),
            "skipped_oversized_prompts": len(skipped_oversized_prompts),
        },
        "template": str(args.template),
        "encoding": args.encoding,
        "max_prompt_tiktoken_count": args.max_prompt_tiktoken_count,
        "index": str(prompt_index_path),
        "prompts": prompts,
        "skipped_oversized_prompts": skipped_oversized_prompts,
        "stop_points": [
            "Use rendered prompt files under the tiktoken budget for Amp.",
            f"If skipped_oversized_prompts is non-empty, do not open transcript text; reduce {SELECTED_MINUTES_FILE} or split that meeting.",
        ],
    }
    write_json(prompt_index_path, report)
    emit(report, fmt=args.format)
    if skipped_oversized_prompts:
        eprint(
            "render failed: at least one prompt exceeds --max-prompt-tiktoken-count. "
            f"Do not open transcript text; reduce {SELECTED_MINUTES_FILE} or split the oversized meeting."
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
    prompt_index_path = (args.prompt_index or (base / PROMPT_INDEX_FILE)).expanduser().resolve()
    summaries_dir = (args.summaries or (base / "summaries")).expanduser().resolve()
    prompts_data = load_json(prompt_index_path)
    summaries_dir.mkdir(parents=True, exist_ok=True)
    index_path = summaries_dir / "index.jsonl"

    prompts = prompts_data["prompts"]
    if not isinstance(prompts, list):
        raise SystemExit(f"invalid prompt index file: {prompt_index_path}: prompts must be a list")
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
            "minute_id": prompt["minute_id"],
            "title": prompt["title"],
            "prompt_tiktoken_count": prompt["prompt_tiktoken_count"],
        }
        append_event(start_event)
        eprint(f"summarizing {prompt_path.name} prompt_tiktoken_count={prompt['prompt_tiktoken_count']}")
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
