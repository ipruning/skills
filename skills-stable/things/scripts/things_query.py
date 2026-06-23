#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "things.py==1.0.1",
# ]
# ///

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import date
from typing import Any

import things

COLLECTIONS: dict[str, str] = {
    "today": "today",
    "inbox": "inbox",
    "anytime": "anytime",
    "upcoming": "upcoming",
    "someday": "someday",
    "deadlines": "deadlines",
    "todos": "todos",
    "projects": "projects",
    "areas": "areas",
    "tags": "tags",
    "completed": "completed",
    "canceled": "canceled",
    "logbook": "logbook",
    "trash": "trash",
}

DEFAULT_FIELDS = (
    "type",
    "title",
    "project_title",
    "heading_title",
    "area_title",
    "start",
    "start_date",
    "deadline",
    "reminder_time",
    "tags",
    "today_index",
    "created",
    "modified",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read local Things data.")
    parser.add_argument(
        "--collection",
        choices=sorted(COLLECTIONS),
        default="today",
        help="Things collection to read.",
    )
    parser.add_argument("--search", help="Search query for task-like collections.")
    parser.add_argument(
        "--status",
        choices=["incomplete", "completed", "canceled", "all"],
        help="Task status filter. Most collections default to incomplete.",
    )
    parser.add_argument("--last", help="Creation window such as 1d, 1w, or 1y.")
    parser.add_argument("--limit", type=int, help="Maximum items to return.")
    parser.add_argument("--count-only", action="store_true", help="Return only count.")
    parser.add_argument("--include-items", action="store_true", help="Include nested items.")
    parser.add_argument("--include-notes", action="store_true", help="Include notes.")
    parser.add_argument("--include-uuid", action="store_true", help="Include UUIDs.")
    parser.add_argument("--db-path", help="Path to a Things SQLite database.")
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format.",
    )
    return parser.parse_args()


def build_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if args.search:
        kwargs["search_query"] = args.search
    if args.status:
        kwargs["status"] = None if args.status == "all" else args.status
    if args.last:
        kwargs["last"] = args.last
    if args.include_items:
        kwargs["include_items"] = True
    if args.db_path:
        kwargs["filepath"] = args.db_path
    return kwargs


def safe_call(func: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
    try:
        return func(**kwargs)
    except TypeError:
        reduced = {
            key: value
            for key, value in kwargs.items()
            if key not in {"search_query", "status", "last", "include_items"}
        }
        return func(**reduced)


def sanitize_item(item: Any, args: argparse.Namespace) -> Any:
    if not isinstance(item, dict):
        return item

    fields = list(DEFAULT_FIELDS)
    if args.include_notes:
        fields.append("notes")
    if args.include_uuid:
        fields.append("uuid")

    sanitized = {field: item.get(field) for field in fields if item.get(field) is not None}

    if args.include_items and item.get("items"):
        sanitized["items"] = [sanitize_item(child, args) for child in item["items"]]
    if args.include_items and item.get("checklist"):
        sanitized["checklist"] = item["checklist"]

    return sanitized


def format_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Things {payload['collection']} ({payload['count']})",
        "",
        f"- Local date: `{payload['local_date']}`",
    ]
    if payload.get("query"):
        lines.append(f"- Query: `{json.dumps(payload['query'], ensure_ascii=False)}`")
    lines.append("")

    for index, item in enumerate(payload["items"], start=1):
        if isinstance(item, dict):
            title = item.get("title") or item.get("name") or str(item)
            context_parts = []
            for key, label in (
                ("project_title", "project"),
                ("heading_title", "heading"),
                ("area_title", "area"),
                ("start_date", "start"),
                ("deadline", "deadline"),
                ("reminder_time", "reminder"),
            ):
                if item.get(key):
                    context_parts.append(f"{label}: {item[key]}")
            suffix = f" ({'; '.join(context_parts)})" if context_parts else ""
            lines.append(f"{index}. {title}{suffix}")
        else:
            lines.append(f"{index}. {item}")

    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    kwargs = build_kwargs(args)
    func = getattr(things, COLLECTIONS[args.collection])
    result = safe_call(func, kwargs)

    if args.count_only:
        count = result if isinstance(result, int) else len(result if isinstance(result, list) else [result])
        payload: dict[str, Any] = {
            "collection": args.collection,
            "local_date": date.today().isoformat(),
            "count": count,
            "query": kwargs,
        }
    else:
        items = result if isinstance(result, list) else [result]
        if args.limit is not None:
            items = items[: args.limit]
        payload = {
            "collection": args.collection,
            "local_date": date.today().isoformat(),
            "count": len(items),
            "query": kwargs,
            "items": [sanitize_item(item, args) for item in items],
        }

    if args.format == "markdown" and not args.count_only:
        print(format_markdown(payload))
    else:
        print(format_json(payload))


if __name__ == "__main__":
    main()
