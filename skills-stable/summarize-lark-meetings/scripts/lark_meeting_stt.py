#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "jinja2>=3.1.6",
#   "pydantic>=2.13.0",
#   "tiktoken>=0.13.0",
#   "typer>=0.16.0",
# ]
# ///
from __future__ import annotations

import concurrent.futures
import datetime as dt
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import tiktoken
import typer
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = SKILL_ROOT / "templates" / "meeting-summary.md.j2"
DEFAULT_ENCODING = "o200k_base"
DEFAULT_MAX_PROMPT_TIKTOKEN_COUNT = 100_000

MINUTES_FOUND = "minutes-found.json"
SELECTED = "selected.txt"
PROMPT_INDEX = "prompt-index.json"

app = typer.Typer(
    help="列出飞书妙记、拉取文字记录、检查重复、生成提示词并调用 Amp 生成会议总结。",
    no_args_is_help=True,
    add_completion=False,
)


class OutputFormat(StrEnum):
    json = "json"
    md = "md"


class CommandOptions(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    run: Path
    format: OutputFormat = OutputFormat.md


class ListOptions(CommandOptions):
    start: str
    end: str
    page_size: int = Field(default=30, ge=1)


class PullOptions(CommandOptions):
    batch_size: int = Field(default=50, ge=1)
    encoding: str = DEFAULT_ENCODING


class CheckOptions(CommandOptions):
    format: OutputFormat = OutputFormat.md


class PromptsOptions(CommandOptions):
    template: Path = DEFAULT_TEMPLATE
    encoding: str = DEFAULT_ENCODING
    max_prompt_tiktoken_count: int = Field(default=DEFAULT_MAX_PROMPT_TIKTOKEN_COUNT, ge=1)


class SummarizeOptions(CommandOptions):
    timeout_seconds: int = Field(default=900, ge=1)
    concurrency: int = Field(default=2, ge=1)
    amp_attempts: int = Field(default=3, ge=1)
    amp_mode: str | None = None
    amp_effort: str | None = None
    amp_visibility: str = "private"


def eprint(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def text_snippet(value: str, *, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n... truncated {len(value) - limit} chars ..."


def require_commands(command_names: list[str]) -> None:
    missing = [command_name for command_name in command_names if shutil.which(command_name) is None]
    if missing:
        raise SystemExit("缺少命令：" + ", ".join(missing))


def validate_date(value: str) -> None:
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"日期无效：{value!r}，需要 YYYY-MM-DD") from exc


def ensure_run_dirs(base: Path) -> None:
    for dirname in ("raw", "minutes", "prompts", "summaries"):
        (base / dirname).mkdir(parents=True, exist_ok=True)


def write_text(file_path: Path, text: str) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(text, encoding="utf-8")


def write_json(file_path: Path, payload: Any) -> None:
    write_text(file_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def load_json(file_path: Path) -> Any:
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"缺少文件：{file_path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON 无效：{file_path}: {exc}") from exc


def append_jsonl(file_path: Path, payload: dict[str, Any]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def emit(payload: dict[str, Any], *, fmt: OutputFormat | str, md: str | None = None) -> None:
    output_format = fmt.value if isinstance(fmt, OutputFormat) else fmt
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if md is not None:
        print(md)
        return
    print(status_markdown(payload))


def emit_error(message: str, *, fmt: OutputFormat | str, code: int = 1) -> None:
    output_format = fmt.value if isinstance(fmt, OutputFormat) else fmt
    if output_format == "json":
        emit({"ok": False, "error": message, "exit_code": code}, fmt=OutputFormat.json)
        return
    eprint(message)


COUNT_LABELS = {
    "selected": "已选择",
    "pulled": "成功拉取",
    "failed": "拉取失败",
    "prompts": "生成提示词",
    "oversized": "超出上限",
    "summaries": "会议总结",
    "failures": "失败",
    "concurrency": "并发数",
    "concurrency_effective": "实际并发数",
    "retries": "重试次数",
    "reused": "复用已有总结",
    "duplicate_groups": "可疑重复组",
}


def status_markdown(payload: dict[str, Any]) -> str:
    lines = ["# 结果", ""]
    counts = payload.get("counts")
    if isinstance(counts, dict):
        for key, value in counts.items():
            lines.append(f"- {COUNT_LABELS.get(key, key)}: {value}")
    return "\n".join(lines).rstrip() + "\n"


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
                    text_snippet(proc.stderr),
                    "",
                    "STDOUT",
                    text_snippet(proc.stdout),
                ]
            ),
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"命令失败 ({proc.returncode}): {' '.join(cmd)}\n"
            f"stderr:\n{text_snippet(proc.stderr)}\n"
            f"stdout:\n{text_snippet(proc.stdout)}"
        )
    return proc


def run_json(cmd: list[str], *, cwd: Path, log: Path | None = None, require_ok: bool = True) -> Any:
    proc = run_cmd(cmd, cwd=cwd, log=log)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"命令没有返回 JSON: {' '.join(cmd)}\n"
            f"stdout:\n{text_snippet(proc.stdout)}\n"
            f"stderr:\n{text_snippet(proc.stderr)}"
        ) from exc
    if require_ok and payload.get("ok") is not True:
        raise RuntimeError(f"lark-cli ok=false: {payload.get('error', payload)}")
    return payload


def run_paginated(base_cmd: list[str], *, cwd: Path, page_dir: Path, log_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token = ""
    page_num = 1
    while True:
        cmd = [*base_cmd, "--format", "json"]
        if page_token:
            cmd.extend(["--page-token", page_token])
        eprint(f"page {page_num}: {' '.join(base_cmd)}")
        payload = run_json(cmd, cwd=cwd, log=log_dir / f"page-{page_num}.log")
        write_json(page_dir / f"page-{page_num}.json", payload)
        data = payload.get("data") or {}
        page_items = data.get("items") or []
        if not isinstance(page_items, list):
            raise RuntimeError(f"分页返回 items 不是数组：{' '.join(base_cmd)}")
        items.extend(page_items)
        if data.get("has_more") is not True:
            return items
        page_token = str(data.get("page_token") or "")
        if not page_token:
            raise RuntimeError(f"has_more=true 但 page_token 为空：{' '.join(base_cmd)}")
        page_num += 1


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


def selected_file_values(file_path: Path) -> list[str]:
    return [
        line.strip()
        for line in file_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


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


def title_similarity(left: str, right: str) -> float:
    left_norm = normalize_title(left)
    right_norm = normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    return difflib.SequenceMatcher(None, left_norm, right_norm).ratio()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(file_path: Path) -> str:
    h = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalized_prefix_hash(text: str) -> str:
    prefix = "".join(text.splitlines()[:80])
    return sha256_text(re.sub(r"\s+", "", prefix))


def tiktoken_encoder(name: str) -> tiktoken.Encoding:
    try:
        return tiktoken.get_encoding(name)
    except ValueError as exc:
        raise SystemExit(f"未知 tiktoken encoding: {name!r}") from exc


def count_tiktoken(text: str, *, encoding: tiktoken.Encoding) -> int:
    return len(encoding.encode(text))


def minute_record(minute_token: str) -> dict[str, Any]:
    return {
        "minute_token": minute_token,
        "title": "",
        "sources": [],
        "meeting_ids": [],
        "calendar_event_ids": [],
        "app_links": [],
        "raw": {},
    }


def merge_minute(
    minutes: dict[str, dict[str, Any]],
    minute_token: str,
    *,
    source: str,
    item: dict[str, Any] | None = None,
    meeting_id: str = "",
    calendar_event_id: str = "",
) -> None:
    if not minute_token:
        return
    item = item or {}
    record = minutes.setdefault(minute_token, minute_record(minute_token))
    if source not in record["sources"]:
        record["sources"].append(source)
    if meeting_id and meeting_id not in record["meeting_ids"]:
        record["meeting_ids"].append(meeting_id)
    if calendar_event_id and calendar_event_id not in record["calendar_event_ids"]:
        record["calendar_event_ids"].append(calendar_event_id)
    title = best_string(item, ("title", "topic", "name", "subject"))
    if title and not record["title"]:
        record["title"] = title
    app_link = best_string(item, ("app_link", "url", "recording_url"))
    if app_link and app_link not in record["app_links"]:
        record["app_links"].append(app_link)
    record["raw"][source] = item


def auth_summary(payload: dict[str, Any]) -> dict[str, Any]:
    user = (payload.get("identities") or {}).get("user") or {}
    return {
        "identity": payload.get("identity") or "",
        "verified": bool(payload.get("verified")),
        "userName": user.get("userName") or "",
        "openId": user.get("openId") or "",
        "tokenStatus": user.get("tokenStatus") or "",
    }


def list_minutes(options: ListOptions) -> int:
    require_commands(["lark-cli"])
    validate_date(options.start)
    validate_date(options.end)
    base = options.run.expanduser().resolve()
    ensure_run_dirs(base)
    raw = base / "raw"
    logs = raw / "logs"

    auth = run_json(
        ["lark-cli", "auth", "status", "--json", "--verify"],
        cwd=base,
        log=logs / "auth-status.log",
        require_ok=False,
    )
    write_json(raw / "auth-status.json", auth)

    vc_items = run_paginated(
        [
            "lark-cli",
            "vc",
            "+search",
            "--start",
            options.start,
            "--end",
            options.end,
            "--page-size",
            str(options.page_size),
        ],
        cwd=base,
        page_dir=raw / "vc-search",
        log_dir=logs / "vc-search",
    )
    write_json(raw / "vc-search.json", {"ok": True, "data": {"items": vc_items}})
    vc_meeting_ids = unique([str(item.get("id") or "") for item in vc_items if item.get("id")])

    owner_items = run_paginated(
        [
            "lark-cli",
            "minutes",
            "+search",
            "--owner-ids",
            "me",
            "--start",
            options.start,
            "--end",
            options.end,
            "--page-size",
            str(options.page_size),
        ],
        cwd=base,
        page_dir=raw / "minutes-owner",
        log_dir=logs / "minutes-owner",
    )
    write_json(raw / "minutes-owner.json", {"ok": True, "data": {"items": owner_items}})

    participant_items = run_paginated(
        [
            "lark-cli",
            "minutes",
            "+search",
            "--participant-ids",
            "me",
            "--start",
            options.start,
            "--end",
            options.end,
            "--page-size",
            str(options.page_size),
        ],
        cwd=base,
        page_dir=raw / "minutes-participant",
        log_dir=logs / "minutes-participant",
    )
    write_json(raw / "minutes-participant.json", {"ok": True, "data": {"items": participant_items}})

    time_items = run_paginated(
        [
            "lark-cli",
            "minutes",
            "+search",
            "--start",
            options.start,
            "--end",
            options.end,
            "--page-size",
            str(options.page_size),
        ],
        cwd=base,
        page_dir=raw / "minutes-time",
        log_dir=logs / "minutes-time",
    )
    write_json(raw / "minutes-time.json", {"ok": True, "data": {"items": time_items}})

    calendar_payload = run_json(
        ["lark-cli", "calendar", "+agenda", "--start", options.start, "--end", options.end, "--format", "json"],
        cwd=base,
        log=logs / "calendar-agenda.log",
    )
    write_json(raw / "calendar-agenda.json", calendar_payload)
    calendar_items = calendar_payload.get("data") or []
    if not isinstance(calendar_items, list):
        calendar_items = []
    calendar_vc_events = [
        item for item in calendar_items if ((item.get("vchat") or {}).get("vc_type") == "vc") and item.get("event_id")
    ]
    calendar_event_ids = [str(item["event_id"]) for item in calendar_vc_events]
    calendar_event_by_id = {str(item.get("event_id") or ""): item for item in calendar_vc_events}

    calendar_meetings: list[dict[str, Any]] = []
    for index, batch in enumerate(chunks(calendar_event_ids, 50), start=1):
        payload = run_json(
            ["lark-cli", "calendar", "+meeting", "--event-ids", ",".join(batch), "--format", "json"],
            cwd=base,
            log=logs / "calendar-meeting" / f"batch-{index:03d}.log",
        )
        write_json(raw / "calendar-meeting" / f"batch-{index:03d}.json", payload)
        calendar_meetings.extend((payload.get("data") or {}).get("meetings") or [])
    write_json(raw / "calendar-meeting.json", {"ok": True, "data": {"meetings": calendar_meetings}})

    calendar_meeting_ids = unique(
        [str(item.get("meeting_id") or "") for item in calendar_meetings if item.get("meeting_id")]
    )
    meeting_ids_for_notes = unique([*vc_meeting_ids, *calendar_meeting_ids])
    vc_note_links: list[dict[str, Any]] = []
    for index, batch in enumerate(chunks(meeting_ids_for_notes, 50), start=1):
        payload = run_json(
            ["lark-cli", "vc", "+notes", "--meeting-ids", ",".join(batch), "--format", "json"],
            cwd=base,
            log=logs / "vc-notes" / f"batch-{index:03d}.log",
        )
        write_json(raw / "vc-notes" / f"batch-{index:03d}.json", payload)
        vc_note_links.extend((payload.get("data") or {}).get("notes") or [])
    write_json(raw / "vc-notes.json", {"ok": True, "data": {"notes": vc_note_links}})

    calendar_meeting_to_events: dict[str, list[str]] = {}
    for item in calendar_meetings:
        meeting_id = str(item.get("meeting_id") or "")
        event_id = str(item.get("event_id") or "")
        if meeting_id and event_id:
            calendar_meeting_to_events.setdefault(meeting_id, []).append(event_id)

    minutes: dict[str, dict[str, Any]] = {}
    for item in owner_items:
        merge_minute(minutes, str(item.get("token") or ""), source="minutes_owner_search", item=item)
    for item in participant_items:
        merge_minute(minutes, str(item.get("token") or ""), source="minutes_participant_search", item=item)
    for item in time_items:
        merge_minute(minutes, str(item.get("token") or ""), source="minutes_time_search", item=item)
    for item in vc_note_links:
        minute_token = str(item.get("minute_token") or "")
        meeting_id = str(item.get("meeting_id") or "")
        source = "vc_minute_lookup" if meeting_id in vc_meeting_ids else "calendar_meeting_lookup"
        for event_id in calendar_meeting_to_events.get(meeting_id) or [""]:
            merge_minute(
                minutes,
                minute_token,
                source=source,
                item=item,
                meeting_id=meeting_id,
                calendar_event_id=event_id,
            )

    minute_list = sorted(minutes.values(), key=lambda item: (item.get("title") or "", item["minute_token"]))
    owner_participant_tokens = {
        str(item.get("token") or "") for item in [*owner_items, *participant_items] if item.get("token")
    }
    time_tokens = {str(item.get("token") or "") for item in time_items if item.get("token")}
    found_tokens = {item["minute_token"] for item in minute_list}
    calendar_without_meeting_id = []
    for item in calendar_meetings:
        if item.get("meeting_id"):
            continue
        event_id = str(item.get("event_id") or "")
        event = calendar_event_by_id.get(event_id) or {}
        calendar_without_meeting_id.append(
            {
                "event_id": event_id,
                "event_title": event.get("summary") or "",
                "start_time": event.get("start_time") or {},
                "end_time": event.get("end_time") or {},
                "self_rsvp_status": event.get("self_rsvp_status") or "",
                "hint": item.get("hint") or "",
            }
        )
    calendar_not_in_vc_search = sorted(set(calendar_meeting_ids) - set(vc_meeting_ids))
    vc_not_in_calendar = sorted(set(vc_meeting_ids) - set(calendar_meeting_ids))
    time_only_extra = sorted(time_tokens - owner_participant_tokens)

    report = {
        "ok": True,
        "run": {
            "start": options.start,
            "end": options.end,
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "dir": str(base),
        },
        "identity": auth_summary(auth),
        "counts": {
            "vc_meetings": len(vc_meeting_ids),
            "minutes_owned": len(owner_items),
            "minutes_participated": len(participant_items),
            "minutes_time_search": len(time_items),
            "calendar_events": len(calendar_items),
            "calendar_vc_events": len(calendar_vc_events),
            "calendar_meetings_with_id": len(calendar_meeting_ids),
            "minutes_found": len(found_tokens),
        },
        "minutes": minute_list,
        "coverage": {
            "calendar_without_meeting_id": calendar_without_meeting_id,
            "calendar_meeting_ids_not_in_vc_search": calendar_not_in_vc_search,
            "vc_search_meeting_ids_not_in_calendar": vc_not_in_calendar,
            "time_search_not_owner_or_participant": time_only_extra,
        },
    }
    write_json(base / MINUTES_FOUND, report)
    coverage_md = coverage_markdown(report)
    write_text(base / "coverage.md", coverage_md)
    emit(report, fmt=options.format, md=coverage_md)
    return 0


def coverage_markdown(report: dict[str, Any]) -> str:
    run = report["run"]
    identity = report.get("identity") or {}
    counts = report.get("counts") or {}
    coverage = report.get("coverage") or {}
    lines = [
        "# 覆盖报告",
        "",
        "## 查询",
        "",
        f"- 时间范围：{run.get('start')} 到 {run.get('end')}",
        f"- 查询时间：{run.get('created_at')}",
        f"- 登录用户：{identity.get('userName') or 'unknown'} ({identity.get('openId') or 'unknown'})",
        f"- 用户令牌状态：{identity.get('tokenStatus') or 'unknown'}, verified: {identity.get('verified')}",
        "",
        "## 来源数量",
        "",
    ]
    count_labels = {
        "vc_meetings": "VC 搜索会议数",
        "minutes_owned": "登录用户拥有的妙记",
        "minutes_participated": "登录用户参与的妙记",
        "minutes_time_search": "按时间找到的妙记",
        "calendar_events": "日历事件",
        "calendar_vc_events": "含视频会议的日历事件",
        "calendar_meetings_with_id": "有视频会议 meeting_id 的日历事件",
        "minutes_found": "候选妙记",
    }
    for key, label in count_labels.items():
        lines.append(f"- {label}: {counts.get(key, 0)}")
    lines.extend(["", "## 日历校验", ""])
    calendar_without = coverage.get("calendar_without_meeting_id") or []
    if calendar_without:
        lines.append("### 含视频会议的日历事件缺少 meeting_id")
        lines.append("")
        for item in calendar_without:
            hint = item.get("hint") or "没有返回 meeting_id"
            lines.append(
                "- `{event_id}` {event_title} {start} - {end}: {hint}".format(
                    event_id=item.get("event_id") or "",
                    event_title=item.get("event_title") or "",
                    start=((item.get("start_time") or {}).get("datetime") or ""),
                    end=((item.get("end_time") or {}).get("datetime") or ""),
                    hint=hint,
                )
            )
        lines.append("")
    else:
        lines.append("- 含视频会议的日历事件都能映射到 meeting_id。")
        lines.append("")
    calendar_not_vc = coverage.get("calendar_meeting_ids_not_in_vc_search") or []
    if calendar_not_vc:
        lines.append("### 日历 meeting_id 不在 vc +search 里")
        lines.append("")
        lines.extend(f"- `{meeting_id}`" for meeting_id in calendar_not_vc)
        lines.append("")
    else:
        lines.append("- 日历可映射 meeting_id 都被 vc +search 覆盖。")
        lines.append("")
    vc_not_calendar = coverage.get("vc_search_meeting_ids_not_in_calendar") or []
    if vc_not_calendar:
        lines.append("### vc +search 里有但日历没有的 meeting_id")
        lines.append("")
        lines.extend(f"- `{meeting_id}`" for meeting_id in vc_not_calendar)
        lines.append("")
    else:
        lines.append("- vc +search 没有发现日历外 meeting_id。")
        lines.append("")
    time_extra = coverage.get("time_search_not_owner_or_participant") or []
    lines.extend(["## 按时间搜索", ""])
    if time_extra:
        lines.append("按时间搜索找到了登录用户拥有/参与之外的 minute_token:")
        lines.append("")
        lines.extend(f"- `{minute_token}`" for minute_token in time_extra)
    else:
        lines.append("- 按时间搜索没有发现登录用户拥有/参与之外的新 minute_token。")
    lines.extend(
        [
            "",
            "## 下一步",
            "",
            "- 运行 `pull --run <run>` 拉取全部妙记，再 `check --run <run>` 看重复证据。",
            f"- 读完证据后编辑 `{SELECTED}` 跳掉重复，再 `prompts --run <run>`。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def minute_lookup(base: Path) -> dict[str, dict[str, Any]]:
    data = load_json(base / MINUTES_FOUND)
    return {str(item["minute_token"]): item for item in data.get("minutes", []) if item.get("minute_token")}


def pull_minutes(options: PullOptions) -> int:
    require_commands(["lark-cli"])
    base = options.run.expanduser().resolve()
    ensure_run_dirs(base)
    lookup = minute_lookup(base)
    selected_tokens = unique(list(lookup.keys()))
    if not selected_tokens:
        raise SystemExit(f"{base / MINUTES_FOUND} 里没有 minute_token；先运行 list。")
    encoding = tiktoken_encoder(options.encoding)
    raw = base / "raw"
    logs = raw / "logs"
    pull_output_root = raw / "pull-output"
    if pull_output_root.exists():
        shutil.rmtree(pull_output_root)
    pull_output_root.mkdir(parents=True, exist_ok=True)

    artifacts: list[dict[str, Any]] = []
    for index, batch in enumerate(chunks(selected_tokens, options.batch_size), start=1):
        eprint(f"pull batch {index}: {len(batch)} minute_token")
        batch_output_dir = pull_output_root / f"batch-{index:03d}"
        batch_output_dir.mkdir(parents=True, exist_ok=True)
        payload = run_json(
            [
                "lark-cli",
                "vc",
                "+notes",
                "--minute-tokens",
                ",".join(batch),
                "--output-dir",
                batch_output_dir.relative_to(base).as_posix(),
                "--format",
                "json",
                "--overwrite",
            ],
            cwd=base,
            log=logs / "pull" / f"batch-{index:03d}.log",
        )
        write_json(raw / "pull" / f"batch-{index:03d}.json", payload)
        artifacts.extend((payload.get("data") or {}).get("notes") or [])
    write_json(raw / "pull.json", {"ok": True, "data": {"notes": artifacts}})

    successes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_success: set[str] = set()
    seen_failure: set[str] = set()
    for artifact in artifacts:
        minute_token = str(artifact.get("minute_token") or "")
        if not minute_token:
            continue
        if artifact.get("error"):
            if minute_token not in seen_failure:
                failures.append(
                    {
                        "minute_token": minute_token,
                        "error": artifact.get("error") or "unknown",
                        "hint": artifact.get("hint") or "",
                    }
                )
                seen_failure.add(minute_token)
            continue
        transcript_rel = (artifact.get("artifacts") or {}).get("transcript_file")
        if not transcript_rel:
            failures.append(
                {
                    "minute_token": minute_token,
                    "error": "lark-cli 返回缺少 `transcript_file`（妙记文字记录文件）",
                    "hint": "",
                }
            )
            seen_failure.add(minute_token)
            continue
        source_path = Path(str(transcript_rel))
        if not source_path.is_absolute():
            source_path = base / source_path
        if not source_path.exists():
            failures.append(
                {
                    "minute_token": minute_token,
                    "error": "`transcript_file` 指向的妙记文字记录文件不存在",
                    "hint": "",
                }
            )
            seen_failure.add(minute_token)
            continue
        minute_dir = base / "minutes" / minute_token
        minute_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = minute_dir / "transcript.txt"
        shutil.copyfile(source_path, transcript_path)
        text = transcript_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        found = lookup.get(minute_token) or {}
        meta = {
            "minute_token": minute_token,
            "title": str(artifact.get("title") or found.get("title") or ""),
            "sources": found.get("sources") or [],
            "meeting_ids": found.get("meeting_ids") or [],
            "calendar_event_ids": found.get("calendar_event_ids") or [],
            "note_id": artifact.get("note_id") or "",
            "note_doc_token": artifact.get("note_doc_token") or "",
            "verbatim_doc_token": artifact.get("verbatim_doc_token") or "",
            "transcript_file": "transcript.txt",
            "bytes": transcript_path.stat().st_size,
            "line_count": len(lines),
            "first_line": lines[0] if lines else "",
            "sha256": sha256_file(transcript_path),
            "prefix_sha256": normalized_prefix_hash(text),
            "transcript_tiktoken_count": count_tiktoken(text, encoding=encoding),
            "pulled_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
        write_json(minute_dir / "meta.json", meta)
        successes.append(meta)
        seen_success.add(minute_token)

    for minute_token in selected_tokens:
        if minute_token not in seen_success and minute_token not in seen_failure:
            failures.append(
                {
                    "minute_token": minute_token,
                    "error": "lark-cli 返回结果里缺少这条已选妙记",
                    "hint": "",
                }
            )

    if pull_output_root.exists():
        shutil.rmtree(pull_output_root)

    selected_path = base / SELECTED
    selected_content = "".join(f"{item['minute_token']}\n" for item in successes)
    # A previous pull may have written selected.txt and the model may have
    # edited it to skip duplicates; a re-run must not clobber those edits.
    selected_preserved = selected_path.exists() and selected_path.read_text(encoding="utf-8") != selected_content
    if selected_preserved:
        write_text(base / f"{SELECTED}.new", selected_content)
    else:
        write_text(selected_path, selected_content)

    report = {
        "ok": not failures,
        "counts": {
            "selected": len(selected_tokens),
            "pulled": len(successes),
            "failed": len(failures),
        },
        "selected_preserved": selected_preserved,
        "pulled": successes,
        "failed": failures,
    }
    if failures:
        report["error"] = f"{len(failures)} minute(s) failed to pull; see 'failed' entries and pulled.md"
        report["exit_code"] = 1
    write_json(base / "pulled.json", report)
    pulled_md = pulled_markdown(report)
    write_text(base / "pulled.md", pulled_md)
    emit(report, fmt=options.format, md=pulled_md)
    return 1 if failures else 0


def pulled_markdown(report: dict[str, Any]) -> str:
    counts = report.get("counts") or {}
    lines = [
        "# 拉取结果",
        "",
        f"- 已选妙记：{counts.get('selected', 0)}",
        f"- 成功拉取：{counts.get('pulled', 0)}",
        f"- 拉取失败：{counts.get('failed', 0)}",
    ]
    if report.get("selected_preserved"):
        lines.append(f"- `{SELECTED}` 带有先前的编辑，已保留原样；本次全量清单写在 `{SELECTED}.new`。")
    lines += [
        "",
        "## 成功",
        "",
    ]
    for item in report.get("pulled") or []:
        lines.append(
            f"- `{item['minute_token']}` {item.get('title') or ''} "
            f"行数={item.get('line_count')} 妙记文字记录 tiktoken 数={item.get('transcript_tiktoken_count')}"
        )
    failures = report.get("failed") or []
    if failures:
        lines.extend(["", "## 失败", ""])
        for item in failures:
            hint = f" ({item.get('hint')})" if item.get("hint") else ""
            lines.append(f"- `{item.get('minute_token')}`: {item.get('error')}{hint}")
    lines.extend(["", "## 下一步", "", "- 运行 `check --run <run>`，再读 `duplicates.md`。"])
    return "\n".join(lines).rstrip() + "\n"


def load_pulled_meta(base: Path) -> list[dict[str, Any]]:
    metas: list[dict[str, Any]] = []
    minutes_dir = base / "minutes"
    if not minutes_dir.exists():
        return metas
    for meta_path in sorted(minutes_dir.glob("*/meta.json")):
        meta = load_json(meta_path)
        transcript_path = meta_path.parent / "transcript.txt"
        if transcript_path.exists():
            meta["abs_transcript_path"] = str(transcript_path)
            meta["rel_transcript_path"] = transcript_path.relative_to(base).as_posix()
            metas.append(meta)
    return metas


def duration_from_first_line(first_line: str) -> str:
    if "|" not in first_line:
        return ""
    return first_line.split("|", 1)[1].strip()


def line_count_close(left: int, right: int) -> bool:
    return abs(left - right) <= max(3, int(max(left, right) * 0.05))


def add_group(groups: list[dict[str, Any]], kind: str, evidence: str, items: list[dict[str, Any]]) -> None:
    tokens = [str(item["minute_token"]) for item in items]
    if len(set(tokens)) < 2:
        return
    existing = {(group["kind"], tuple(group["minute_tokens"])) for group in groups}
    key = (kind, tuple(tokens))
    if key in existing:
        return
    groups.append(
        {
            "kind": kind,
            "evidence": evidence,
            "minute_tokens": tokens,
            "items": [
                {
                    "minute_token": item["minute_token"],
                    "title": item.get("title") or "",
                    "line_count": item.get("line_count", 0),
                    "transcript_tiktoken_count": item.get("transcript_tiktoken_count", 0),
                    "first_line": item.get("first_line") or "",
                    "sources": item.get("sources") or [],
                    "transcript_path": item.get("rel_transcript_path") or "",
                }
                for item in items
            ],
        }
    )


def group_by_value(metas: list[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for meta in metas:
        value = str(meta.get(field) or "")
        if value:
            grouped.setdefault(value, []).append(meta)
    return grouped


def build_duplicate_groups(metas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for sha, items in group_by_value(metas, "sha256").items():
        if len(items) > 1:
            add_group(groups, "强重复", f"全文 hash 相同：{sha}", items)
    for prefix_sha, items in group_by_value(metas, "prefix_sha256").items():
        if len(items) > 1:
            add_group(groups, "高度可疑", f"前 80 行规范化 hash 相同：{prefix_sha}", items)
    for first_line, items in group_by_value(metas, "first_line").items():
        if len(items) > 1:
            add_group(groups, "弱可疑", f"首行相同：{first_line}", items)

    pair_keys = {
        tuple(sorted(group["minute_tokens"])) for group in groups if len(group.get("minute_tokens") or []) == 2
    }
    for left_index, left in enumerate(metas):
        for right in metas[left_index + 1 :]:
            pair = tuple(sorted([left["minute_token"], right["minute_token"]]))
            if pair in pair_keys:
                continue
            left_lines = int(left.get("line_count") or 0)
            right_lines = int(right.get("line_count") or 0)
            if not line_count_close(left_lines, right_lines):
                continue
            left_duration = duration_from_first_line(left.get("first_line") or "")
            right_duration = duration_from_first_line(right.get("first_line") or "")
            same_duration = bool(left_duration) and left_duration == right_duration
            similar_title = title_similarity(left.get("title") or "", right.get("title") or "") >= 0.78
            if same_duration or similar_title:
                evidence_bits = []
                if same_duration:
                    evidence_bits.append("时长相同")
                if similar_title:
                    evidence_bits.append("标题相似")
                evidence_bits.append("行数接近")
                add_group(groups, "弱可疑", "，".join(evidence_bits), [left, right])
                pair_keys.add(pair)
    return groups


def check_minutes(options: CheckOptions) -> int:
    base = options.run.expanduser().resolve()
    if not (base / "pulled.json").exists():
        raise SystemExit("缺少 pulled.json；先运行 pull。")
    metas = load_pulled_meta(base)
    if not metas:
        raise SystemExit("没有成功拉取的妙记文字记录；先运行 pull，并确认 pulled.md 里有成功项。")
    groups = build_duplicate_groups(metas)
    report = {
        "ok": True,
        "counts": {
            "pulled": len(metas),
            "duplicate_groups": len(groups),
        },
        "duplicates": groups,
    }
    write_json(base / "duplicates.json", report)
    duplicates_md = duplicates_markdown(report)
    write_text(base / "duplicates.md", duplicates_md)
    emit(report, fmt=options.format, md=duplicates_md)
    return 0


def duplicates_markdown(report: dict[str, Any]) -> str:
    groups = report.get("duplicates") or []
    lines = [
        "# 重复检查报告",
        "",
        f"不要根据本页证据物理删除或合并妙记。跳过妙记前，先读相关 `transcript.txt`，再编辑 `{SELECTED}`。",
        "",
        f"- 已拉取妙记文字记录：{(report.get('counts') or {}).get('pulled', 0)}",
        f"- 可疑重复组：{len(groups)}",
        "",
    ]
    if not groups:
        lines.append("没有发现可疑重复。")
        return "\n".join(lines).rstrip() + "\n"
    for index, group in enumerate(groups, start=1):
        lines.extend([f"## {index}. {group.get('kind')}", "", f"- 证据：{group.get('evidence')}", ""])
        for item in group.get("items") or []:
            lines.append(
                "- `{minute_token}` {title} 行数={line_count} 妙记文字记录 tiktoken 数={tokens} 来源={sources}".format(
                    minute_token=item.get("minute_token"),
                    title=item.get("title") or "",
                    line_count=item.get("line_count"),
                    tokens=item.get("transcript_tiktoken_count"),
                    sources=",".join(item.get("sources") or []),
                )
            )
            lines.append(f"  - 妙记文字记录路径：`{item.get('transcript_path')}`")
            if item.get("first_line"):
                lines.append(f"  - 首行：`{item.get('first_line')}`")
        lines.append("")
    lines.extend(
        [
            "## 下一步",
            "",
            "- 强重复也不要物理删除妙记文字记录。",
            f"- 如需跳过某条，只从 `{SELECTED}` 删除对应 minute_token。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_prompt(*, template_path: Path, transcript_text: str, meta: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_path.name)
    return template.render(
        transcript=transcript_text,
        meeting={"title": meta.get("title") or ""},
        minute=meta,
    )


def prompt_file_name(meta: dict[str, Any]) -> str:
    title = str(meta.get("title") or "").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", title).strip("-")
    if slug:
        return f"{meta['minute_token']}-{slug}.prompt.md"
    return f"{meta['minute_token']}.prompt.md"


def build_prompts(options: PromptsOptions) -> int:
    base = options.run.expanduser().resolve()
    prompt_index_path = base / PROMPT_INDEX
    if prompt_index_path.exists():
        prompt_index_path.unlink()
    prompt_dir = base / "prompts"
    if prompt_dir.exists():
        shutil.rmtree(prompt_dir)
    if not options.template.exists():
        raise SystemExit(f"模板不存在：{options.template}")
    selected_file = base / SELECTED
    if not selected_file.exists():
        raise SystemExit(f"缺少 {selected_file}；先运行 pull，或创建总结清单。")
    selected_tokens = unique(selected_file_values(selected_file))
    if not selected_tokens:
        raise SystemExit(f"{selected_file} 为空。")

    selected_rows: list[tuple[str, dict[str, Any], Path]] = []
    missing: list[str] = []
    for minute_token in selected_tokens:
        minute_dir = base / "minutes" / minute_token
        meta_path = minute_dir / "meta.json"
        transcript_path = minute_dir / "transcript.txt"
        if not meta_path.exists() or not transcript_path.exists():
            missing.append(minute_token)
            continue
        meta = load_json(meta_path)
        selected_rows.append((minute_token, meta, transcript_path))

    if missing:
        raise SystemExit(f"{SELECTED} 中有 minute_token 缺少 transcript.txt；请回到 pull: " + ", ".join(missing))

    encoding = tiktoken_encoder(options.encoding)
    prompt_dir.mkdir(parents=True, exist_ok=True)

    prompts: list[dict[str, Any]] = []
    oversized: list[dict[str, Any]] = []
    for minute_token, meta, transcript_path in selected_rows:
        transcript_text = transcript_path.read_text(encoding="utf-8", errors="replace")
        meta["rel_transcript_path"] = transcript_path.relative_to(base).as_posix()
        rendered = render_prompt(template_path=options.template, transcript_text=transcript_text, meta=meta)
        token_count = count_tiktoken(rendered, encoding=encoding)
        row = {
            "minute_token": minute_token,
            "title": meta.get("title") or "",
            "source_transcript_path": transcript_path.relative_to(base).as_posix(),
            "prompt_tiktoken_count": token_count,
            "prompt_sha256": sha256_text(rendered),
            "max_prompt_tiktoken_count": options.max_prompt_tiktoken_count,
        }
        if token_count > options.max_prompt_tiktoken_count:
            oversized.append({**row, "reason": "prompt_tiktoken_count exceeds max"})
            continue
        prompt_path = prompt_dir / prompt_file_name(meta)
        write_text(prompt_path, rendered)
        prompts.append(
            {
                **row,
                "prompt_path": prompt_path.relative_to(base).as_posix(),
                "bytes": prompt_path.stat().st_size,
            }
        )

    report = {
        "ok": not oversized,
        "counts": {
            "selected": len(selected_tokens),
            "prompts": len(prompts),
            "oversized": len(oversized),
        },
        "template": str(options.template),
        "encoding": options.encoding,
        "prompts": prompts,
        "oversized": oversized,
    }
    if oversized:
        report["error"] = f"{len(oversized)} prompt(s) exceed the size limit; see 'oversized' entries"
        report["exit_code"] = 1
    write_json(prompt_index_path, report)
    emit(report, fmt=options.format)
    return 1 if oversized else 0


def write_summaries_error(base: Path, message: str) -> None:
    summaries_dir = base / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    index_path = summaries_dir / "index.json"
    if index_path.exists():
        try:
            previous_report = json.loads(index_path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            previous_report = {}
        if previous_report.get("results"):
            write_json(summaries_dir / "resume-index.json", previous_report)
    report = {
        "ok": False,
        "error": message,
        "exit_code": 1,
        "counts": {
            "prompts": 0,
            "summaries": 0,
            "failures": 0,
        },
        "results": [],
    }
    write_json(summaries_dir / "last-error.json", report)
    write_json(index_path, report)


def build_amp_command(options: SummarizeOptions) -> list[str]:
    cmd = [
        "amp",
        "--execute",
        "--visibility",
        options.amp_visibility,
    ]
    if options.amp_mode:
        cmd.extend(["--mode", options.amp_mode])
    if options.amp_effort:
        cmd.extend(["--effort", options.amp_effort])
    cmd.extend(["--no-ide", "--no-color"])
    return cmd


def is_retryable_amp_failure(stderr: str) -> bool:
    # Bun keyring native-module load flake; the platform suffix varies by machine.
    return "ERR_DLOPEN_FAILED" in stderr and "keyring." in stderr


def summarize_prompts(options: SummarizeOptions) -> int:
    base = options.run.expanduser().resolve()
    try:
        require_commands(["amp"])
    except SystemExit as exc:
        write_summaries_error(base, str(exc))
        raise
    prompt_index_path = base / PROMPT_INDEX
    try:
        data = load_json(prompt_index_path)
    except SystemExit as exc:
        write_summaries_error(base, str(exc))
        raise
    if data.get("ok") is not True:
        message = "prompt-index.json ok=false；先处理 oversized 后重新运行 prompts。"
        write_summaries_error(base, message)
        raise SystemExit(message)
    prompts = data.get("prompts") or []
    if not isinstance(prompts, list):
        message = f"{prompt_index_path} 中 prompts 不是数组。"
        write_summaries_error(base, message)
        raise SystemExit(message)
    prompt_dir = base / "prompts"
    for prompt in prompts:
        prompt_rel = str(prompt.get("prompt_path") or "")
        prompt_path = base / prompt_rel
        if not prompt_path.exists() or prompt_path.parent.resolve() != prompt_dir.resolve():
            message = f"prompt-index.json 指向不存在或非当前 prompts/ 的提示词文件：{prompt_rel}"
            write_summaries_error(base, message)
            raise SystemExit(message)

    summaries_dir = base / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    previous_results: dict[str, dict[str, Any]] = {}
    for previous_index_path in (summaries_dir / "index.json", summaries_dir / "resume-index.json"):
        if not previous_index_path.exists():
            continue
        try:
            previous_report = json.loads(previous_index_path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        if previous_report.get("results"):
            previous_results = {
                str(result.get("prompt_path") or ""): result
                for result in previous_report["results"]
                if isinstance(result, dict) and result.get("prompt_path")
            }
            break
    expected_summary_paths = {
        "summaries/" + Path(str(prompt["prompt_path"])).name.removesuffix(".prompt.md") + ".summary.md"
        for prompt in prompts
    }
    for summary_path in summaries_dir.glob("*.summary.md"):
        if summary_path.relative_to(base).as_posix() not in expected_summary_paths:
            summary_path.unlink()
    index_path = summaries_dir / "index.jsonl"
    if index_path.exists():
        index_path.unlink()
    jsonl_lock = threading.Lock()

    def append_event(payload: dict[str, Any]) -> None:
        with jsonl_lock:
            append_jsonl(index_path, payload)

    def summarize_one(prompt: dict[str, Any]) -> dict[str, Any]:
        prompt_path = base / str(prompt["prompt_path"])
        summary_path = summaries_dir / (prompt_path.name.removesuffix(".prompt.md") + ".summary.md")
        started_at = dt.datetime.now().isoformat(timespec="seconds")
        started = time.time()
        try:
            prompt_text = prompt_path.read_text(encoding="utf-8")
        except OSError as exc:
            completed = {
                "event": "completed",
                "started_at": started_at,
                "completed_at": dt.datetime.now().isoformat(timespec="seconds"),
                "duration_seconds": round(time.time() - started, 3),
                "prompt_path": prompt_path.relative_to(base).as_posix(),
                "summary_path": summary_path.relative_to(base).as_posix(),
                "minute_token": prompt["minute_token"],
                "title": prompt.get("title") or "",
                "prompt_tiktoken_count": prompt["prompt_tiktoken_count"],
                "prompt_sha256": "",
                "exit_code": 1,
                "timed_out": False,
                "output_bytes": 0,
                "stderr": f"读取 prompt 失败：{exc}",
                "attempts": 0,
                "retry_failures": [],
                "reused": False,
            }
            append_event(completed)
            return completed
        prompt_sha256 = sha256_text(prompt_text)
        start_event = {
            "event": "started",
            "started_at": started_at,
            "prompt_path": prompt_path.relative_to(base).as_posix(),
            "summary_path": summary_path.relative_to(base).as_posix(),
            "minute_token": prompt["minute_token"],
            "title": prompt.get("title") or "",
            "prompt_tiktoken_count": prompt["prompt_tiktoken_count"],
            "prompt_sha256": prompt_sha256,
        }
        previous = previous_results.get(start_event["prompt_path"]) or {}
        if (
            previous.get("exit_code") == 0
            and previous.get("prompt_sha256") == prompt_sha256
            and summary_path.exists()
            and summary_path.stat().st_size > 0
        ):
            reused = {
                **start_event,
                "event": "reused",
                "completed_at": dt.datetime.now().isoformat(timespec="seconds"),
                "duration_seconds": round(time.time() - started, 3),
                "exit_code": 0,
                "timed_out": False,
                "output_bytes": summary_path.stat().st_size,
                "stderr": "",
                "attempts": 0,
                "retry_failures": [],
                "reused": True,
            }
            append_event(reused)
            eprint(f"Amp 复用 {summary_path.name}")
            return reused
        if summary_path.exists():
            summary_path.unlink()
        append_event(start_event)
        eprint(f"Amp 处理 {prompt_path.name} prompt_tiktoken_count={prompt['prompt_tiktoken_count']}")
        cmd = build_amp_command(options)
        exit_code = 1
        timed_out = False
        stderr = ""
        retry_failures: list[dict[str, Any]] = []
        attempt = 0
        for attempt in range(1, options.amp_attempts + 1):
            try:
                proc = subprocess.run(
                    cmd,
                    input=prompt_text,
                    text=True,
                    capture_output=True,
                    timeout=options.timeout_seconds,
                    check=False,
                    cwd=base,
                )
                exit_code = proc.returncode
                stderr = proc.stderr
                if exit_code == 0 and not proc.stdout.strip():
                    exit_code = 1
                    stderr = (stderr.strip() + "\n" if stderr.strip() else "") + "amp returned empty output"
                elif exit_code == 0:
                    try:
                        write_text(summary_path, proc.stdout)
                    except OSError as exc:
                        exit_code = 1
                        stderr = f"写入总结失败：{exc}"
                    else:
                        break
            except subprocess.TimeoutExpired:
                exit_code = 124
                timed_out = True
                stderr = f"amp timed out after {options.timeout_seconds}s"
            except OSError as exc:
                exit_code = 1
                stderr = f"启动 Amp 失败：{exc}"

            if attempt >= options.amp_attempts or not is_retryable_amp_failure(stderr):
                break
            retry_failure = {
                "attempt": attempt,
                "exit_code": exit_code,
                "stderr": text_snippet(stderr),
            }
            retry_failures.append(retry_failure)
            append_event(
                {
                    **start_event,
                    "event": "retrying",
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "exit_code": exit_code,
                    "stderr": text_snippet(stderr),
                }
            )
            eprint(f"Amp 重试 {prompt_path.name} attempt={attempt + 1}/{options.amp_attempts}")
            time.sleep(attempt)
        completed = {
            **start_event,
            "event": "completed",
            "completed_at": dt.datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": round(time.time() - started, 3),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "output_bytes": summary_path.stat().st_size if summary_path.exists() else 0,
            "stderr": stderr.strip(),
            "attempts": attempt,
            "retry_failures": retry_failures,
            "reused": False,
        }
        append_event(completed)
        return completed

    workers = min(options.concurrency, len(prompts)) if prompts else 0
    results: list[dict[str, Any]] = []
    if workers:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_prompt = {executor.submit(summarize_one, prompt): prompt for prompt in prompts}
            for future in concurrent.futures.as_completed(future_to_prompt):
                results.append(future.result())

    prompt_order = {str(prompt["prompt_path"]): index for index, prompt in enumerate(prompts)}
    results.sort(key=lambda result: prompt_order.get(str(result.get("prompt_path") or ""), len(prompts)))
    failures = [result for result in results if result["exit_code"] != 0]
    report = {
        "ok": not failures,
        "counts": {
            "prompts": len(results),
            "summaries": len(results) - len(failures),
            "failures": len(failures),
            "concurrency": options.concurrency,
            "concurrency_effective": workers,
            "retries": sum(max(0, int(result["attempts"]) - 1) for result in results),
            "reused": sum(bool(result.get("reused")) for result in results),
        },
        "results": results,
    }
    if failures:
        report["error"] = f"{len(failures)} 个 Amp 总结失败；详见 results。"
        report["exit_code"] = 1
    write_json(summaries_dir / "index.json", report)
    emit(report, fmt=options.format)
    return 1 if failures else 0


def exit_with(code: int) -> None:
    if code:
        raise typer.Exit(code)


def run_command(action: Any, *, fmt: OutputFormat) -> None:
    try:
        code = action()
    except RuntimeError as exc:
        emit_error(str(exc), fmt=fmt)
        raise typer.Exit(1) from exc
    except SystemExit as exc:
        if isinstance(exc.code, int):
            raise
        emit_error(str(exc), fmt=fmt)
        raise typer.Exit(1) from exc
    exit_with(code)


@app.command("list", help="按日期范围找妙记，不下载妙记文字记录。")
def list_cmd(
    start: Annotated[str, typer.Option("--start", help="开始日期 YYYY-MM-DD。")],
    end: Annotated[str, typer.Option("--end", help="结束日期 YYYY-MM-DD。")],
    run: Annotated[Path, typer.Option("--run", help="运行目录。")],
    page_size: Annotated[int, typer.Option("--page-size", min=1, help="lark-cli 分页大小。")] = 30,
    output_format: Annotated[OutputFormat, typer.Option("--format", help="输出格式。")] = OutputFormat.md,
) -> None:
    run_command(
        lambda: list_minutes(
            ListOptions(
                start=start,
                end=end,
                run=run,
                page_size=page_size,
                format=output_format,
            )
        ),
        fmt=output_format,
    )


@app.command("pull", help="拉取 minutes-found.json 里的全部妙记文字记录。")
def pull_cmd(
    run: Annotated[Path, typer.Option("--run", help="运行目录。")],
    batch_size: Annotated[int, typer.Option("--batch-size", min=1, help="每批 minute_token 数量。")] = 50,
    encoding: Annotated[str, typer.Option("--encoding", help="tiktoken encoding.")] = DEFAULT_ENCODING,
    output_format: Annotated[OutputFormat, typer.Option("--format", help="输出格式。")] = OutputFormat.md,
) -> None:
    run_command(
        lambda: pull_minutes(
            PullOptions(
                run=run,
                batch_size=batch_size,
                encoding=encoding,
                format=output_format,
            )
        ),
        fmt=output_format,
    )


@app.command("check", help="检查成功拉到的妙记文字记录并写 duplicates.md。")
def check_cmd(
    run: Annotated[Path, typer.Option("--run", help="运行目录。")],
    output_format: Annotated[OutputFormat, typer.Option("--format", help="输出格式。")] = OutputFormat.md,
) -> None:
    run_command(lambda: check_minutes(CheckOptions(run=run, format=output_format)), fmt=output_format)


@app.command("prompts", help=f"按 {SELECTED} 生成提示词。")
def prompts_cmd(
    run: Annotated[Path, typer.Option("--run", help="运行目录。")],
    template: Annotated[Path, typer.Option("--template", help="Jinja2 提示词模板。")] = DEFAULT_TEMPLATE,
    encoding: Annotated[str, typer.Option("--encoding", help="tiktoken encoding.")] = DEFAULT_ENCODING,
    max_prompt_tiktoken_count: Annotated[
        int,
        typer.Option("--max-prompt-tiktoken-count", min=1, help="单个提示词 tiktoken 上限。"),
    ] = DEFAULT_MAX_PROMPT_TIKTOKEN_COUNT,
    output_format: Annotated[OutputFormat, typer.Option("--format", help="输出格式。")] = OutputFormat.md,
) -> None:
    run_command(
        lambda: build_prompts(
            PromptsOptions(
                run=run,
                template=template,
                encoding=encoding,
                max_prompt_tiktoken_count=max_prompt_tiktoken_count,
                format=output_format,
            )
        ),
        fmt=output_format,
    )


@app.command("summarize", help="并发调用 Amp 生成会议总结。")
def summarize_cmd(
    run: Annotated[Path, typer.Option("--run", help="运行目录。")],
    timeout_seconds: Annotated[int, typer.Option("--timeout-seconds", min=1, help="单个 Amp 超时。")] = 900,
    concurrency: Annotated[int, typer.Option("--concurrency", min=1, help="Amp 并发数。")] = 2,
    amp_attempts: Annotated[
        int,
        typer.Option("--amp-attempts", min=1, help="已知 Bun keyring 瞬时加载失败的最多尝试次数。"),
    ] = 3,
    amp_mode: Annotated[
        str | None,
        typer.Option("--amp-mode", help="Amp mode；默认不传，由当前 Amp 决定。"),
    ] = None,
    amp_effort: Annotated[
        str | None,
        typer.Option("--amp-effort", help="Amp reasoning effort；默认不传，由当前 Amp 决定。"),
    ] = None,
    amp_visibility: Annotated[str, typer.Option("--amp-visibility")] = "private",
    output_format: Annotated[OutputFormat, typer.Option("--format", help="输出格式。")] = OutputFormat.md,
) -> None:
    run_command(
        lambda: summarize_prompts(
            SummarizeOptions(
                run=run,
                timeout_seconds=timeout_seconds,
                concurrency=concurrency,
                amp_attempts=amp_attempts,
                amp_mode=amp_mode,
                amp_effort=amp_effort,
                amp_visibility=amp_visibility,
                format=output_format,
            )
        ),
        fmt=output_format,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
