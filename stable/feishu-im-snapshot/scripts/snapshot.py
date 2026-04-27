# /// script
# requires-python = ">=3.12"
# dependencies = ["typer>=0.25.0", "rich>=15.0.0", "jinja2>=3.1.0"]
# ///

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import typer
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True)
console = Console()

SKILL_NAME = "feishu-im-snapshot"
RUN_PROTOCOL = "agent_corpus_run_v1"
SCHEMA_PROTOCOL = "agent_corpus_schema_v1"
SCHEMA_VERSION = "5.0"
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
SEARCH_PAGE_SIZE = 50
MAX_SEARCH_PAGES = 500
AUDIT_CHAT_LIMIT = 3
REACTION_BATCH_SIZE = 20
REACTION_PAGE_SIZE = 10
REACTION_MAX_PAGES_PER_MESSAGE = 20
IGNORED_CHAT_PATTERNS = [
    "服务器告警通知",
    "爬虫报警",
]
REQUIRED_SCOPES = [
    "search:message",
    "im:message.group_msg:get_as_user",
    "im:message.p2p_msg:get_as_user",
]
REACTION_SCOPES = [
    "im:message:readonly",
    "im:message.reactions:read",
]


def run_lark(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        ["lark-cli", *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"lark-cli failed: {' '.join(args)}\n{detail}")

    text = proc.stdout.strip()
    start = text.find("{")
    if start > 0:
        text = text[start:]
    return json.loads(text)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def default_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(tempfile.gettempdir()) / "agent-corpus-runs" / SKILL_NAME / stamp


def parse_feishu_time(value: str, tz: ZoneInfo) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=tz)


def slug(text: str, limit: int = 80) -> str:
    text = re.sub(r"[^\w-]+", "_", text.strip(), flags=re.UNICODE)
    text = text.strip("._")
    return (text or "unknown")[:limit]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def prepare_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name in ["raw", "data", "views", "chats"]:
        target = path / name
        if target.exists():
            shutil.rmtree(target)
    for name in ["AGENTS.md", "manifest.json", "schema.json"]:
        target = path / name
        if target.exists():
            target.unlink()


def chat_name(msg: dict[str, Any]) -> str:
    return (
        msg.get("chat_name")
        or (msg.get("chat_partner") or {}).get("name")
        or (msg.get("chat_partner") or {}).get("open_id")
        or msg.get("chat_id")
        or "unknown"
    )


def sender_name(msg: dict[str, Any]) -> str:
    return (msg.get("sender") or {}).get("name") or (msg.get("sender") or {}).get("id") or "unknown"


def sender_id(msg: dict[str, Any]) -> str:
    return (msg.get("sender") or {}).get("id") or ""


def sender_type(msg: dict[str, Any]) -> str:
    return (msg.get("sender") or {}).get("sender_type") or ""


def is_direct_message(msg: dict[str, Any]) -> bool:
    return msg.get("chat_type") == "p2p" or bool(msg.get("chat_partner"))


def chat_bucket(msg: dict[str, Any]) -> str:
    return "direct" if is_direct_message(msg) else "group"


def is_ignored_chat(msg: dict[str, Any]) -> bool:
    name = chat_name(msg)
    return any(pattern in name for pattern in IGNORED_CHAT_PATTERNS)


def message_text(msg: dict[str, Any]) -> str:
    return re.sub(r"\n{3,}", "\n\n", str(msg.get("content") or "")).strip()


def preview_text(text: str, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def unique_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for idx, msg in enumerate(messages):
        key = msg.get("message_id") or ":".join(
            [
                "missing-message-id",
                str(idx),
                str(msg.get("chat_id") or ""),
                str(msg.get("create_time") or ""),
                sender_id(msg),
            ]
        )
        by_key[key] = msg
    return sorted(
        by_key.values(),
        key=lambda m: (m.get("create_time", ""), m.get("message_id", "")),
    )


def message_iso(msg: dict[str, Any], tz: ZoneInfo) -> str:
    value = msg.get("create_time") or "1970-01-01 00:00"
    return iso(parse_feishu_time(value, tz))


def mentions_viewer(msg: dict[str, Any], viewer_open_id: str) -> bool:
    return any((mention.get("id") == viewer_open_id) for mention in msg.get("mentions") or [])


def direct_name(messages: list[dict[str, Any]], viewer_open_id: str) -> str:
    last = messages[-1]
    partner = last.get("chat_partner") or {}
    if partner.get("name"):
        return partner["name"]

    for msg in messages:
        name = sender_name(msg)
        sid = sender_id(msg)
        if sid != viewer_open_id and not name.startswith(("ou_", "cli_")):
            return name
    return partner.get("open_id") or chat_name(last)


def fetch_search_page(
    start: datetime,
    end: datetime,
    *,
    page_token: str | None = None,
    chat_id: str | None = None,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    args = [
        "im",
        "+messages-search",
        "--as",
        "user",
        "--query",
        "",
        "--start",
        iso(start),
        "--end",
        iso(end),
        "--page-size",
        str(SEARCH_PAGE_SIZE),
        "--format",
        "json",
    ]
    if chat_id:
        args.extend(["--chat-id", chat_id])
    if page_token:
        args.extend(["--page-token", page_token])

    payload = run_lark(args)
    data = payload.get("data") or {}
    return (
        data.get("messages") or [],
        bool(data.get("has_more")),
        data.get("page_token"),
    )


def fetch_search_full(
    start: datetime,
    end: datetime,
    *,
    chat_id: str | None = None,
    max_pages: int = MAX_SEARCH_PAGES,
    progress_label: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    page_token: str | None = None
    pages = 0
    has_more = True

    while has_more:
        if pages >= max_pages:
            raise RuntimeError(f"messages-search exceeded {max_pages} pages; refusing partial snapshot")
        batch, has_more, next_token = fetch_search_page(
            start,
            end,
            page_token=page_token,
            chat_id=chat_id,
        )
        pages += 1
        messages.extend(batch)
        if progress_label:
            console.print(f"{progress_label} page {pages}, raw messages {len(messages)}")
        if has_more:
            if not next_token:
                raise RuntimeError("messages-search returned has_more=true without page_token")
            if next_token in seen_tokens:
                raise RuntimeError("messages-search returned a repeated page_token")
            seen_tokens.add(next_token)
        page_token = next_token

    ids = [msg.get("message_id") for msg in messages if msg.get("message_id")]
    return unique_messages(messages), {
        "pages": pages,
        "raw_count": len(messages),
        "unique_message_count": len(set(ids)),
        "duplicate_message_ids": len(ids) - len(set(ids)),
        "has_more_final": has_more,
    }


def fetch_chat_messages_list(
    chat_id: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        args = [
            "im",
            "+chat-messages-list",
            "--as",
            "user",
            "--chat-id",
            chat_id,
            "--start",
            iso(start),
            "--end",
            iso(end),
            "--sort",
            "asc",
            "--page-size",
            str(SEARCH_PAGE_SIZE),
            "--format",
            "json",
        ]
        if page_token:
            args.extend(["--page-token", page_token])
        payload = run_lark(args)
        messages.extend(payload.get("data", {}).get("messages") or [])
        data = payload.get("data") or {}
        if not data.get("has_more") or not data.get("page_token"):
            break
        page_token = data["page_token"]

    return unique_messages(messages)


def normalize_reaction(
    message_id: str,
    item: dict[str, Any],
    *,
    viewer_open_id: str,
) -> dict[str, Any]:
    operator = item.get("operator") or {}
    reaction_type = item.get("emoji_type") or ((item.get("reaction_type") or {}).get("emoji_type"))
    operator_id = operator.get("operator_id") or ""
    return {
        "message_id": message_id,
        "reaction_id": item.get("reaction_id"),
        "reaction_type": reaction_type,
        "operator_type": operator.get("operator_type"),
        "operator_id": operator_id,
        "operator_is_viewer": operator_id == viewer_open_id,
        "action_time": item.get("action_time"),
    }


def fetch_reaction_batch(queries: list[dict[str, str]]) -> dict[str, Any]:
    payload = run_lark(
        [
            "im",
            "reactions",
            "batch_query",
            "--as",
            "user",
            "--params",
            json.dumps({"user_id_type": "open_id"}, ensure_ascii=False),
            "--data",
            json.dumps(
                {
                    "queries": queries,
                    "page_size_per_message": REACTION_PAGE_SIZE,
                },
                ensure_ascii=False,
            ),
            "--format",
            "json",
        ]
    )
    return payload.get("data") or {}


def fetch_reactions(
    message_ids: list[str],
    *,
    viewer_open_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    pending: list[dict[str, str]] = [{"message_id": mid} for mid in message_ids]
    initial_batches = max(
        1,
        (len(message_ids) + REACTION_BATCH_SIZE - 1) // REACTION_BATCH_SIZE,
    )
    page_counts: Counter[str] = Counter()
    batches = 0

    while pending:
        batch = pending[:REACTION_BATCH_SIZE]
        pending = pending[REACTION_BATCH_SIZE:]
        batches += 1
        data = fetch_reaction_batch(batch)

        for detail in data.get("success_msg_reaction_details") or []:
            message_id = detail.get("message_id") or ""
            for item in detail.get("message_reaction_items") or []:
                rows.append(
                    normalize_reaction(
                        message_id,
                        item,
                        viewer_open_id=viewer_open_id,
                    )
                )
            if detail.get("has_more"):
                page_counts[message_id] += 1
                if page_counts[message_id] >= REACTION_MAX_PAGES_PER_MESSAGE:
                    failures.append(
                        {
                            "message_id": message_id,
                            "fail_reason": "reaction_page_limit_exceeded",
                        }
                    )
                elif detail.get("page_token"):
                    pending.append(
                        {
                            "message_id": message_id,
                            "page_token": detail["page_token"],
                        }
                    )
                else:
                    failures.append(
                        {
                            "message_id": message_id,
                            "fail_reason": "has_more_without_page_token",
                        }
                    )

        for failure in data.get("fail_msg_reaction_details") or []:
            failures.append(
                {
                    "message_id": failure.get("message_id"),
                    "fail_reason": failure.get("fail_reason") or "unknown",
                }
            )

        console.print(f"reactions batch {batches}/{initial_batches}, rows {len(rows)}, pending {len(pending)}")

    unique_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get("reaction_id") or ":".join(
            [
                row.get("message_id") or "",
                row.get("reaction_type") or "",
                row.get("operator_id") or "",
                row.get("action_time") or "",
            ]
        )
        unique_rows[key] = row

    rows = sorted(
        unique_rows.values(),
        key=lambda row: (row.get("message_id") or "", row.get("action_time") or ""),
    )
    fail_reasons = Counter(failure.get("fail_reason") or "unknown" for failure in failures)
    return rows, {
        "enabled": True,
        "batch_size": REACTION_BATCH_SIZE,
        "page_size_per_message": REACTION_PAGE_SIZE,
        "query_batches": batches,
        "messages_queried": len(message_ids),
        "reaction_rows": len(rows),
        "messages_with_reactions": len({row["message_id"] for row in rows}),
        "messages_reacted_by_viewer": len({row["message_id"] for row in rows if row.get("operator_is_viewer")}),
        "failed_messages": len(failures),
        "fail_reasons": dict(sorted(fail_reasons.items())),
    }


def reaction_counts(reactions: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(row.get("reaction_type") or "unknown" for row in reactions).items()))


def viewer_reactions(reactions: list[dict[str, Any]]) -> list[str]:
    return sorted({row.get("reaction_type") or "unknown" for row in reactions if row.get("operator_is_viewer")})


def reaction_line(reactions: list[dict[str, Any]]) -> str:
    if not reactions:
        return ""
    counts = ", ".join(f"{reaction_type} x{count}" for reaction_type, count in reaction_counts(reactions).items())
    viewer = viewer_reactions(reactions)
    if viewer:
        return f"_Message reactions: {counts}; viewer: {', '.join(viewer)}_"
    return f"_Message reactions: {counts}_"


def write_chat_md(
    path: Path,
    title: str,
    description: list[str],
    messages: list[dict[str, Any]],
    reactions_by_message: dict[str, list[dict[str, Any]]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    for line in description:
        lines.append(f"- {line}")
    lines.append("")
    for msg in messages:
        lines.append(f"## {msg.get('create_time', '')} · {sender_name(msg)}")
        lines.append("")
        lines.append(message_text(msg) or "[empty]")
        line = reaction_line(reactions_by_message.get(msg.get("message_id") or "") or [])
        if line:
            lines.append("")
            lines.append(line)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def normalize_message(
    msg: dict[str, Any],
    *,
    tz: ZoneInfo,
    viewer_open_id: str,
    reactions: list[dict[str, Any]],
    chat_display_name: str,
    file: str,
) -> dict[str, Any]:
    text = message_text(msg)
    counts = reaction_counts(reactions)
    viewer = viewer_reactions(reactions)
    sid = sender_id(msg)
    return {
        "message_id": msg.get("message_id"),
        "chat_id": msg.get("chat_id"),
        "chat_bucket": chat_bucket(msg),
        "raw_chat_type": msg.get("chat_type"),
        "chat_name": chat_display_name,
        "created_at": message_iso(msg, tz),
        "sender_id": sid,
        "sender_name": sender_name(msg),
        "sender_type": sender_type(msg),
        "sender_is_viewer": sid == viewer_open_id,
        "msg_type": msg.get("msg_type"),
        "text": text,
        "text_preview": preview_text(text),
        "mentions": msg.get("mentions") or [],
        "mentions_viewer": mentions_viewer(msg, viewer_open_id),
        "reaction_count": sum(counts.values()),
        "reaction_counts": counts,
        "reacted_by_viewer": bool(viewer),
        "reactions_by_viewer": viewer,
        "deleted": bool(msg.get("deleted")),
        "updated": bool(msg.get("updated")),
        "thread_id": msg.get("thread_id"),
        "file": file,
    }


def chat_index_row(
    chat_id: str,
    bucket: str,
    name: str,
    rel: str,
    messages: list[dict[str, Any]],
    reactions_by_message: dict[str, list[dict[str, Any]]],
    *,
    tz: ZoneInfo,
    viewer_open_id: str,
) -> dict[str, Any]:
    rows = [
        normalize_message(
            msg,
            tz=tz,
            viewer_open_id=viewer_open_id,
            reactions=reactions_by_message.get(msg.get("message_id") or "") or [],
            chat_display_name=name,
            file=rel,
        )
        for msg in messages
    ]
    last = rows[-1]
    viewer_rows = [row for row in rows if row["sender_is_viewer"]]
    non_viewer_rows = [row for row in rows if not row["sender_is_viewer"]]
    return {
        "chat_id": chat_id,
        "chat_bucket": bucket,
        "chat_name": name,
        "file": rel,
        "message_count": len(messages),
        "viewer_message_count": len(viewer_rows),
        "non_viewer_message_count": len(non_viewer_rows),
        "first_at": message_iso(messages[0], tz),
        "last_at": last["created_at"],
        "last_message_id": last["message_id"],
        "last_sender_id": last["sender_id"],
        "last_sender_name": last["sender_name"],
        "last_sender_is_viewer": last["sender_is_viewer"],
        "raw_chat_type_counts": dict(sorted(Counter(msg.get("chat_type") or "missing" for msg in messages).items())),
        "sender_type_counts": dict(sorted(Counter(sender_type(msg) or "missing" for msg in messages).items())),
        "messages_with_reactions": sum(1 for row in rows if row["reaction_count"]),
        "messages_reacted_by_viewer": sum(1 for row in rows if row["reacted_by_viewer"]),
        "participants": sorted({sender_name(msg) for msg in messages}),
    }


def audit_message_meta(msg: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id_tail": str(msg.get("message_id") or "")[-8:],
        "create_time": msg.get("create_time"),
        "raw_chat_type": msg.get("chat_type"),
        "msg_type": msg.get("msg_type"),
        "sender_type": sender_type(msg),
        "deleted": bool(msg.get("deleted")),
        "updated": bool(msg.get("updated")),
        "has_thread_id": bool(msg.get("thread_id")),
        "has_mentions": bool(msg.get("mentions")),
    }


def run_audit(
    start: datetime,
    end: datetime,
    messages_by_chat: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    candidates = sorted(
        messages_by_chat.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    )[:AUDIT_CHAT_LIMIT]

    for chat_id, messages in candidates:
        try:
            search_messages, search_meta = fetch_search_full(
                start,
                end,
                chat_id=chat_id,
                max_pages=MAX_SEARCH_PAGES,
            )
            list_messages = fetch_chat_messages_list(chat_id, start, end)
        except (RuntimeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            results.append(
                {
                    "chat_id": chat_id,
                    "chat_tail": chat_id[-8:],
                    "chat_name": chat_name(messages[-1]),
                    "chat_bucket": chat_bucket(messages[-1]),
                    "error": str(exc),
                }
            )
            continue

        search_by_id = {msg.get("message_id"): msg for msg in search_messages if msg.get("message_id")}
        list_by_id = {msg.get("message_id"): msg for msg in list_messages if msg.get("message_id")}
        missing_ids = sorted(set(list_by_id) - set(search_by_id))
        extra_ids = sorted(set(search_by_id) - set(list_by_id))
        results.append(
            {
                "chat_id": chat_id,
                "chat_tail": chat_id[-8:],
                "chat_name": chat_name(messages[-1]),
                "chat_bucket": chat_bucket(messages[-1]),
                "search_count": len(search_by_id),
                "chat_messages_list_count": len(list_by_id),
                "missing_from_search": len(missing_ids),
                "extra_in_search": len(extra_ids),
                "search_pages": search_meta["pages"],
                "missing_from_search_meta": [audit_message_meta(list_by_id[mid]) for mid in missing_ids[:5]],
                "extra_in_search_meta": [audit_message_meta(search_by_id[mid]) for mid in extra_ids[:5]],
            }
        )

    return {
        "description": "Sample compares lark-cli im +messages-search --chat-id with +chat-messages-list; message bodies are not included.",
        "sampled_chats": len(results),
        "results": results,
    }


def build_schema() -> dict[str, Any]:
    return {
        "protocol": SCHEMA_PROTOCOL,
        "skill": SKILL_NAME,
        "schema_version": SCHEMA_VERSION,
        "files": {
            "raw/messages.jsonl": {
                "kind": "jsonl",
                "description": "Raw unique messages returned by +messages-search before ignored-chat removal.",
            },
            "data/messages.jsonl": {
                "kind": "jsonl",
                "fields": [
                    "message_id",
                    "chat_id",
                    "chat_bucket",
                    "raw_chat_type",
                    "chat_name",
                    "created_at",
                    "sender_id",
                    "sender_name",
                    "sender_type",
                    "sender_is_viewer",
                    "msg_type",
                    "text",
                    "text_preview",
                    "mentions",
                    "mentions_viewer",
                    "reaction_count",
                    "reaction_counts",
                    "reacted_by_viewer",
                    "reactions_by_viewer",
                    "deleted",
                    "updated",
                    "thread_id",
                    "file",
                ],
            },
            "data/chats.jsonl": {
                "kind": "jsonl",
                "fields": [
                    "chat_id",
                    "chat_bucket",
                    "chat_name",
                    "file",
                    "message_count",
                    "viewer_message_count",
                    "non_viewer_message_count",
                    "first_at",
                    "last_at",
                    "last_message_id",
                    "last_sender_id",
                    "last_sender_name",
                    "last_sender_is_viewer",
                    "raw_chat_type_counts",
                    "sender_type_counts",
                    "messages_with_reactions",
                    "messages_reacted_by_viewer",
                    "participants",
                ],
            },
            "data/reactions.jsonl": {
                "kind": "jsonl",
                "fields": [
                    "message_id",
                    "reaction_id",
                    "reaction_type",
                    "operator_type",
                    "operator_id",
                    "operator_is_viewer",
                    "action_time",
                ],
            },
        },
    }


def render_agents_md(out: Path, manifest: dict[str, Any]) -> None:
    env = Environment(
        loader=FileSystemLoader(SKILL_DIR / "templates"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template("AGENTS.j2")
    content = template.render(manifest=manifest)
    (out / "AGENTS.md").write_text(content, encoding="utf-8")


@app.command()
def snapshot(
    days: Annotated[int, typer.Option(help="Rolling days to snapshot.")] = 7,
    out: Annotated[Path | None, typer.Option(help="Run directory.")] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", help="stdout format: markdown or json."),
    ] = "markdown",
    schema_only: Annotated[bool, typer.Option("--schema", help="Print schema.json content after snapshot.")] = False,
) -> None:
    """Snapshot the lark-cli messages-search corpus for Feishu chats.

    Examples:

      uv run scripts/snapshot.py --days 1 --out "$RUN_DIR"

      uv run scripts/snapshot.py --days 7
    """
    tz = ZoneInfo("Asia/Shanghai")
    if days <= 0:
        raise typer.BadParameter("--days must be greater than 0")
    if output_format not in {"markdown", "json"}:
        raise typer.BadParameter("--format must be markdown or json")
    end = datetime.now(tz)
    start = end - timedelta(days=days)

    if out is None:
        out = default_output_dir()
    elif out == Path("."):
        raise typer.BadParameter('--out must not be "."; omit --out to use the default run directory')
    prepare_output_dir(out)

    raw_dir = out / "raw"
    data_dir = out / "data"
    views_dir = out / "views"

    auth = run_lark(["auth", "status", "--verify"])
    viewer_open_id = auth["userOpenId"]
    viewer_name = auth.get("userName", "viewer")

    console.print(f"Snapshotting Feishu chats for [bold]{viewer_name}[/bold]")
    console.print(f"Range: {iso(start)} -> {iso(end)}")
    console.print(f"Output: {out}")

    warnings: list[str] = []

    scope = auth.get("scope") or ""
    missing_scopes = [scope_name for scope_name in REQUIRED_SCOPES if scope_name not in scope]
    if auth.get("identity") != "user" or not auth.get("verified") or missing_scopes:
        raise RuntimeError(
            "Feishu user auth is not ready. "
            f"identity={auth.get('identity')!r}, verified={auth.get('verified')!r}, "
            f"missing_scopes={missing_scopes}"
        )

    raw_messages, fetch_meta = fetch_search_full(
        start,
        end,
        progress_label="messages-search",
    )
    raw_messages = unique_messages(raw_messages)
    write_jsonl(raw_dir / "messages.jsonl", raw_messages)

    raw_chat_type_counts = Counter(msg.get("chat_type") or "missing" for msg in raw_messages)
    sender_type_counts = Counter(sender_type(msg) or "missing" for msg in raw_messages)
    missing_field_counts = {
        field: sum(1 for msg in raw_messages if msg.get(field) in (None, "", []))
        for field in ["message_id", "chat_id", "chat_type", "chat_name", "sender", "content"]
    }

    raw_by_chat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for msg in raw_messages:
        raw_by_chat[msg.get("chat_id") or "unknown"].append(msg)

    ignored_chat_ids = {
        chat_id for chat_id, messages in raw_by_chat.items() if any(is_ignored_chat(msg) for msg in messages)
    }
    ignored_message_count = sum(len(raw_by_chat[chat_id]) for chat_id in ignored_chat_ids)

    messages_by_chat: dict[str, list[dict[str, Any]]] = {
        chat_id: unique_messages(messages)
        for chat_id, messages in raw_by_chat.items()
        if chat_id not in ignored_chat_ids
    }
    messages_after_ignored_chats = [msg for messages in messages_by_chat.values() for msg in messages]
    message_ids = [msg["message_id"] for msg in messages_after_ignored_chats if msg.get("message_id")]

    reaction_missing_scopes = [scope_name for scope_name in REACTION_SCOPES if scope_name not in scope]
    if reaction_missing_scopes:
        reaction_rows: list[dict[str, Any]] = []
        reaction_meta: dict[str, Any] = {
            "enabled": False,
            "reason": "missing_scopes",
            "missing_scopes": reaction_missing_scopes,
        }
        warnings.append(f"Message reaction snapshot skipped because scopes are missing: {reaction_missing_scopes}")
    else:
        console.print("Fetching message reactions")
        try:
            reaction_rows, reaction_meta = fetch_reactions(
                message_ids,
                viewer_open_id=viewer_open_id,
            )
        except (RuntimeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            reaction_rows = []
            reaction_meta = {
                "enabled": False,
                "reason": "fetch_failed",
                "error": str(exc),
            }
            warnings.append(f"Message reaction snapshot failed: {exc}")

    reactions_by_message: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in reaction_rows:
        if row.get("message_id"):
            reactions_by_message[row["message_id"]].append(row)

    all_message_rows: list[dict[str, Any]] = []
    chat_rows: list[dict[str, Any]] = []

    for chat_id, messages in sorted(
        messages_by_chat.items(),
        key=lambda item: item[1][-1].get("create_time", ""),
        reverse=True,
    ):
        bucket = "direct" if any(is_direct_message(msg) for msg in messages) else "group"
        name = direct_name(messages, viewer_open_id) if bucket == "direct" else chat_name(messages[-1])
        raw_types = sorted({msg.get("chat_type") or "missing" for msg in messages})
        path = views_dir / bucket / f"{slug(name)}__{chat_id[-8:]}.md"
        write_chat_md(
            path,
            f"{bucket.title()} chat: {name}",
            [
                "Truth: this file contains the messages from this chat that are present in the snapshot messages-search corpus for the time range.",
                f"Chat bucket: {bucket}",
                f"Raw chat types: {', '.join(raw_types)}",
                "Message reactions are shown when returned by im.reactions.batch_query.",
                f"Chat ID: {chat_id}",
            ],
            messages,
            reactions_by_message,
        )
        rel = str(path.relative_to(out))
        chat_rows.append(
            chat_index_row(
                chat_id,
                bucket,
                name,
                rel,
                messages,
                reactions_by_message,
                tz=tz,
                viewer_open_id=viewer_open_id,
            )
        )
        all_message_rows.extend(
            normalize_message(
                msg,
                tz=tz,
                viewer_open_id=viewer_open_id,
                reactions=reactions_by_message.get(msg.get("message_id") or "") or [],
                chat_display_name=name,
                file=rel,
            )
            for msg in messages
        )

    message_keyed: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(all_message_rows):
        key = row.get("message_id") or ":".join(
            [
                "missing-message-id",
                str(idx),
                str(row.get("chat_id") or ""),
                str(row.get("created_at") or ""),
                str(row.get("sender_id") or ""),
            ]
        )
        message_keyed[key] = row
    all_message_rows = sorted(
        message_keyed.values(),
        key=lambda r: (r.get("created_at") or "", r.get("chat_name") or ""),
    )
    chat_rows = sorted(chat_rows, key=lambda r: r.get("last_at") or "", reverse=True)
    audit = run_audit(start, end, messages_by_chat)

    write_jsonl(data_dir / "messages.jsonl", all_message_rows)
    write_jsonl(data_dir / "chats.jsonl", chat_rows)
    write_jsonl(data_dir / "reactions.jsonl", reaction_rows)

    fetch_details = {
        **fetch_meta,
        "chat_type_counts": dict(sorted(raw_chat_type_counts.items())),
        "sender_type_counts": dict(sorted(sender_type_counts.items())),
        "missing_field_counts": missing_field_counts,
        "ignored_chat_count": len(ignored_chat_ids),
        "ignored_message_count": ignored_message_count,
    }
    files = {
        "agents": "AGENTS.md",
        "manifest": "manifest.json",
        "schema": "schema.json",
        "raw_messages": "raw/messages.jsonl",
        "messages": "data/messages.jsonl",
        "chats": "data/chats.jsonl",
        "reactions": "data/reactions.jsonl",
        "direct_views": "views/direct/",
        "group_views": "views/group/",
    }
    manifest = {
        "protocol": RUN_PROTOCOL,
        "skill": SKILL_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": iso(end),
        "run": {
            "out_dir": str(out),
            "cwd": str(Path.cwd()),
            "command": " ".join(sys.argv),
        },
        "source": {
            "source": 'lark-cli im +messages-search --query "" --as user',
            "source_kind": "lark-cli shortcut",
            "viewer": {
                "name": viewer_name,
                "open_id": viewer_open_id,
            },
            "range": {
                "start": iso(start),
                "end": iso(end),
                "timezone": "Asia/Shanghai",
            },
            "method": {
                "pagination": "manual page_token loop until has_more=false",
                "page_size": SEARCH_PAGE_SIZE,
                "max_pages": MAX_SEARCH_PAGES,
                "sender_filter": "none",
                "chat_bucket_rule": "p2p/chat_partner -> direct; all other raw chat types -> group",
                "ignored_chat_patterns": IGNORED_CHAT_PATTERNS,
                "reactions": "best-effort im.reactions.batch_query for snapshot message IDs when scopes are available",
            },
            "fetch": fetch_details,
            "reactions": reaction_meta,
            "audit": audit,
        },
        "boundary": [
            "The source is lark-cli im +messages-search with an empty query and fixed time range.",
            "This is not an absolute Feishu archive across every API surface.",
            "raw/messages.jsonl contains raw unique messages returned by +messages-search before ignored-chat removal.",
            "data/messages.jsonl contains normalized records for snapshot Markdown views.",
            "views/ is the main reading corpus for downstream agents.",
            "Message reactions are best-effort records from im.reactions.batch_query.",
            "Images, files, and links are not downloaded, OCRed, or resolved to document titles.",
            "rg can only find text already snapshotted under views/.",
        ],
        "stats": {
            "messages": len(all_message_rows),
            "raw_messages_before_ignored_chats": len(raw_messages),
            "messages_after_ignored_chats": len(messages_after_ignored_chats),
            "reactions": len(reaction_rows),
            "chats": len(chat_rows),
            "direct_messages": sum(1 for row in all_message_rows if row["chat_bucket"] == "direct"),
            "direct_chats": sum(1 for row in chat_rows if row["chat_bucket"] == "direct"),
            "group_messages": sum(1 for row in all_message_rows if row["chat_bucket"] == "group"),
            "group_chats": sum(1 for row in chat_rows if row["chat_bucket"] == "group"),
        },
        "files": files,
        "warnings": warnings,
    }
    schema = build_schema()
    write_json(out / "manifest.json", manifest)
    write_json(out / "schema.json", schema)
    render_agents_md(out, manifest)

    if schema_only:
        console.print_json(data=schema)
    elif output_format == "json":
        console.print_json(
            data={
                "protocol": manifest["protocol"],
                "skill": manifest["skill"],
                "run": manifest["run"],
                "stats": manifest["stats"],
                "files": manifest["files"],
                "warnings": manifest["warnings"],
            }
        )
    else:
        table = Table(title="Feishu IM Snapshot")
        table.add_column("Item")
        table.add_column("Count", justify="right")
        for key, value in manifest["stats"].items():
            table.add_row(key, str(value))
        console.print(table)
        print(f"OUT_DIR={out}")
        console.print()
        console.print(f"[bold]Schema:[/bold] {SCHEMA_VERSION}")
        console.print("[bold]Primary corpus:[/bold] views/")
        console.print("[bold]Indexes:[/bold] data/messages.jsonl, data/chats.jsonl")
        console.print()
        console.print("[bold]Next:[/bold]")
        console.print('  cd "$OUT_DIR"')
        console.print("  sed -n '1,160p' AGENTS.md")
        console.print("  jq '.stats' manifest.json")
        if warnings:
            console.print("[yellow]Warnings:[/yellow]")
            for warning in warnings:
                console.print(f"- {warning}")


if __name__ == "__main__":
    app()
