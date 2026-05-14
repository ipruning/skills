# /// script
# requires-python = ">=3.12"
# dependencies = ["typer>=0.25.0", "rich>=15.0.0", "jinja2>=3.1.0"]
# ///

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from rich.console import Console
from rich.table import Table

SKILL_NAME = "codex-trace-inspect"
RUN_PROTOCOL = "agent_corpus_run_v1"
SCHEMA_PROTOCOL = "agent_corpus_schema_v1"
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
SESSION_ROOT = CODEX_HOME / "sessions"
ARCHIVED_SESSION_ROOT = CODEX_HOME / "archived_sessions"
SESSION_INDEX = CODEX_HOME / "session_index.jsonl"

STRUCTURED_RESULT_TYPES = {
    "exec_command_end",
    "write_stdin_end",
    "patch_apply_end",
    "collab_agent_spawn_end",
    "collab_waiting_end",
    "collab_close_end",
}

app = typer.Typer(no_args_is_help=True)
console = Console()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def default_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(tempfile.gettempdir()) / "agent-corpus-runs" / SKILL_NAME / stamp


def thread_id(value: str) -> str:
    if value.startswith("codex://threads/"):
        return value.rsplit("/", 1)[-1]
    return value


def index_entry(tid: str) -> dict[str, Any] | None:
    if not SESSION_INDEX.exists():
        return None

    with SESSION_INDEX.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("id") == tid:
                return row
    return None


def resolve_trace(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.exists():
        return candidate

    tid = thread_id(value)
    matches = sorted(
        [
            *SESSION_ROOT.glob(f"**/*{tid}*.jsonl"),
            *ARCHIVED_SESSION_ROOT.glob(f"**/*{tid}*.jsonl"),
        ]
    )
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise typer.BadParameter("multiple traces matched:\n" + "\n".join(str(p) for p in matches))

    entry = index_entry(tid)
    if entry:
        detail = json.dumps(entry, ensure_ascii=False)
        raise typer.BadParameter(
            "trace JSONL not found in sessions or archived_sessions, but session_index has metadata:\n"
            f"{detail}\n"
            "The full trace body may have been removed or stored outside Codex's local rollout directories."
        )

    raise typer.BadParameter(f"trace not found in sessions, archived_sessions, or session_index: {value}")


def prepare_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name in ["raw", "data", "views"]:
        target = path / name
        if target.exists():
            shutil.rmtree(target)
    for name in ["AGENTS.md", "manifest.json", "schema.json"]:
        target = path / name
        if target.exists():
            target.unlink()


def load_entries(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append({"line": line_no, "row": json.loads(line)})
            except json.JSONDecodeError as exc:
                raise typer.BadParameter(f"invalid JSONL at line {line_no}: {exc}") from exc
    return rows


def compact(value: Any, limit: int = 240) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def parse_json_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def payload_type(row: dict[str, Any]) -> str:
    payload = row.get("payload") or {}
    value = payload.get("type")
    return value if isinstance(value, str) else ""


def text_from_message_payload(payload: dict[str, Any]) -> str:
    parts = payload.get("content") or []
    if isinstance(parts, list):
        return "\n".join(part.get("text") or part.get("input_text") or "" for part in parts if isinstance(part, dict))
    return ""


def command_from_args(args: Any) -> Any:
    if isinstance(args, dict):
        for key in ("cmd", "command", "chars", "message"):
            if key in args:
                return args[key]
    return ""


def build_commands(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for entry in entries:
        row = entry["row"]
        payload = row.get("payload") or {}
        ptype = payload.get("type")
        if row.get("type") == "response_item" and ptype == "function_call":
            raw_args = payload.get("arguments") or ""
            args = parse_json_text(raw_args)
            commands.append(
                {
                    "line": entry["line"],
                    "timestamp": row.get("timestamp"),
                    "call_id": payload.get("call_id"),
                    "record_type": "function_call",
                    "tool": payload.get("name"),
                    "cwd": (args.get("workdir") or args.get("cwd")) if isinstance(args, dict) else None,
                    "argument_bytes": len(raw_args) if isinstance(raw_args, str) else len(compact(raw_args, 100000)),
                    "command_preview": compact(command_from_args(args), 320),
                    "arguments_preview": compact(args, 500),
                }
            )
        elif row.get("type") == "response_item" and ptype == "custom_tool_call":
            raw_input = payload.get("input")
            commands.append(
                {
                    "line": entry["line"],
                    "timestamp": row.get("timestamp"),
                    "call_id": payload.get("call_id"),
                    "record_type": "custom_tool_call",
                    "tool": payload.get("name"),
                    "cwd": None,
                    "argument_bytes": len(compact(raw_input, 100000)),
                    "command_preview": compact(raw_input, 320),
                    "arguments_preview": compact(raw_input, 500),
                }
            )
    return commands


def output_text(payload: dict[str, Any]) -> str:
    for key in ("aggregated_output", "stdout", "stderr", "output", "message", "status"):
        value = payload.get(key)
        if value:
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return ""


def parse_exit_code(payload: dict[str, Any]) -> int | None:
    value = payload.get("exit_code")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None

    text = output_text(payload)
    match = re.search(r"Process exited with code (-?\d+)", text)
    return int(match.group(1)) if match else None


def build_results(
    entries: list[dict[str, Any]],
    command_by_call_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    structured_call_ids = {
        (entry["row"].get("payload") or {}).get("call_id")
        for entry in entries
        if entry["row"].get("type") == "event_msg"
        and payload_type(entry["row"]) in STRUCTURED_RESULT_TYPES
        and (entry["row"].get("payload") or {}).get("call_id")
    }

    results: list[dict[str, Any]] = []
    for entry in entries:
        row = entry["row"]
        payload = row.get("payload") or {}
        ptype = payload.get("type")
        source = row.get("type")
        call_id = payload.get("call_id")

        include = (source == "event_msg" and ptype in STRUCTURED_RESULT_TYPES) or (
            source == "response_item"
            and ptype in {"function_call_output", "custom_tool_call_output"}
            and call_id not in structured_call_ids
        )
        if not include:
            continue

        text = output_text(payload)
        command = command_by_call_id.get(call_id or "", {})
        results.append(
            {
                "line": entry["line"],
                "timestamp": row.get("timestamp"),
                "call_id": call_id,
                "source": source,
                "payload_type": ptype,
                "tool": command.get("tool"),
                "command_preview": command.get("command_preview") or compact(payload.get("command"), 320),
                "exit_code": parse_exit_code(payload),
                "success": payload.get("success"),
                "status": payload.get("status"),
                "duration": payload.get("duration"),
                "output_bytes": len(text),
                "output_preview": compact(text, 500),
            }
        )
    return results


def build_messages(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for entry in entries:
        row = entry["row"]
        payload = row.get("payload") or {}
        source = row.get("type")
        ptype = payload.get("type")
        role = None
        text = ""

        if source == "response_item" and ptype == "message":
            role = payload.get("role")
            text = text_from_message_payload(payload)
        elif source == "event_msg" and ptype == "agent_message":
            role = "assistant"
            text = payload.get("message") or ""
        elif source == "event_msg" and ptype == "user_message":
            role = "user"
            text = payload.get("message") or ""
        else:
            continue

        messages.append(
            {
                "line": entry["line"],
                "timestamp": row.get("timestamp"),
                "source": source,
                "payload_type": ptype,
                "role": role,
                "text_bytes": len(text),
                "text_preview": compact(text, 1000),
            }
        )
    return messages


def count_values(values: list[Any]) -> list[dict[str, Any]]:
    counts = Counter("null" if value is None else str(value) for value in values)
    return [{"key": key, "count": count} for key, count in counts.most_common()]


def trace_snapshot(path: Path, entries: list[dict[str, Any]], *, display_path: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": display_path,
        "line_count": len(entries),
        "size_bytes": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    }


def build_schema(entries: list[dict[str, Any]], snapshot: dict[str, Any]) -> dict[str, Any]:
    top_sets = Counter()
    payload_sets = Counter()
    for entry in entries:
        row = entry["row"]
        top_sets[tuple(row.keys())] += 1
        payload = row.get("payload") or {}
        payload_sets[(payload_type(row), tuple(payload.keys()))] += 1

    return {
        "protocol": SCHEMA_PROTOCOL,
        "skill": SKILL_NAME,
        "generated_at": utc_now(),
        "files": {
            "raw/trace.jsonl": {
                "kind": "jsonl",
                "description": "Snapshot copy of the resolved Codex rollout trace.",
            },
            "data/commands.jsonl": {
                "kind": "jsonl",
                "fields": [
                    "line",
                    "timestamp",
                    "call_id",
                    "record_type",
                    "tool",
                    "cwd",
                    "argument_bytes",
                    "command_preview",
                    "arguments_preview",
                ],
            },
            "data/results.jsonl": {
                "kind": "jsonl",
                "fields": [
                    "line",
                    "timestamp",
                    "call_id",
                    "source",
                    "payload_type",
                    "tool",
                    "command_preview",
                    "exit_code",
                    "success",
                    "status",
                    "duration",
                    "output_bytes",
                    "output_preview",
                ],
            },
            "data/messages.jsonl": {
                "kind": "jsonl",
                "fields": [
                    "line",
                    "timestamp",
                    "source",
                    "payload_type",
                    "role",
                    "text_bytes",
                    "text_preview",
                ],
            },
        },
        "trace": {
            "snapshot": snapshot,
            "top_level_key_sets": [{"count": count, "keys": list(keys)} for keys, count in top_sets.most_common()],
            "payload_key_sets": [
                {"payload_type": ptype, "count": count, "keys": list(keys)}
                for (ptype, keys), count in payload_sets.most_common()
            ],
        },
        "notes": [
            "Trace files are JSONL event streams.",
            "Most rows have timestamp, type, and payload.",
            "payload is polymorphic; inspect payload.type before assuming fields.",
            "response_item.function_call_output often duplicates structured event_msg result rows for shell commands.",
        ],
    }


def final_answer_preview(messages: list[dict[str, Any]], limit: int = 1200) -> str:
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return compact(message.get("text_preview") or "", limit)
    return ""


def compact_summary(
    snapshot: dict[str, Any],
    entries: list[dict[str, Any]],
    commands: list[dict[str, Any]],
    results: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = [entry["row"] for entry in entries]
    nonzero = [
        result for result in results if isinstance(result.get("exit_code"), int) and result.get("exit_code") != 0
    ]
    longest = sorted(commands, key=lambda item: item.get("argument_bytes") or 0, reverse=True)
    return {
        "snapshot": snapshot,
        "time_range": {
            "start": rows[0].get("timestamp") if rows else None,
            "end": rows[-1].get("timestamp") if rows else None,
        },
        "counts": {
            "events": len(entries),
            "by_type": count_values([row.get("type") for row in rows]),
            "by_payload_type": count_values([payload_type(row) for row in rows]),
            "by_tool": count_values([command.get("tool") for command in commands]),
            "by_exit_code": count_values(
                [result.get("exit_code") for result in results if result.get("exit_code") is not None]
            ),
            "commands": len(commands),
            "results": len(results),
            "nonzero_results": len(nonzero),
            "messages": len(messages),
        },
        "nonzero_results_preview": [
            {
                "line": item.get("line"),
                "timestamp": item.get("timestamp"),
                "tool": item.get("tool"),
                "exit_code": item.get("exit_code"),
                "command_preview": item.get("command_preview"),
                "output_preview": item.get("output_preview"),
            }
            for item in nonzero[:20]
        ],
        "longest_commands_preview": [
            {
                "line": item.get("line"),
                "timestamp": item.get("timestamp"),
                "tool": item.get("tool"),
                "argument_bytes": item.get("argument_bytes"),
                "command_preview": item.get("command_preview"),
            }
            for item in longest[:10]
        ],
        "final_answer_preview": final_answer_preview(messages),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def summary_markdown(manifest: dict[str, Any], summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    trace_arg = str(manifest["source"]["trace_arg"])
    trace_label = trace_arg if trace_arg.startswith("codex://threads/") else "[local JSONL path]"
    lines = [
        "# Codex Trace Summary",
        "",
        f"- Trace argument: `{trace_label}`",
        f"- Snapshot: `{manifest['files']['raw_trace']}`",
        f"- Events: {counts['events']}",
        f"- Commands: {counts['commands']}",
        f"- Results: {counts['results']}",
        f"- Nonzero results: {counts['nonzero_results']}",
        f"- Messages: {counts['messages']}",
        "",
        "## Tools",
        "",
    ]
    lines.extend(f"- `{item['key']}`: {item['count']}" for item in counts["by_tool"][:12])
    lines.extend(["", "## Nonzero Result Preview", ""])
    if summary["nonzero_results_preview"]:
        lines.extend(
            (
                f"- line {item['line']} `{item['tool']}` exit {item['exit_code']}: "
                f"{item['command_preview']} | {item['output_preview']}"
            )
            for item in summary["nonzero_results_preview"][:20]
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Final Answer Preview", "", summary["final_answer_preview"] or "[empty]", ""])
    return "\n".join(lines)


def timeline_markdown(
    messages: list[dict[str, Any]],
    commands: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> str:
    nonzero = [item for item in results if isinstance(item.get("exit_code"), int) and item.get("exit_code") != 0]
    seen_messages: set[tuple[Any, str]] = set()
    message_lines = []
    for item in messages:
        if item.get("role") not in {"user", "assistant"}:
            continue
        text = compact(item.get("text_preview") or "", 240)
        key = (item.get("role"), text)
        if key in seen_messages:
            continue
        seen_messages.add(key)
        message_lines.append(
            f"- line {item.get('line')} · {item.get('timestamp')} · {item.get('role')}: {text or '[empty]'}"
        )

    command_lines = []
    for item in commands:
        if item.get("tool") == "write_stdin" and '"chars": ""' in (item.get("arguments_preview") or ""):
            continue
        text = compact(item.get("command_preview") or item.get("arguments_preview") or "", 240)
        command_lines.append(
            f"- line {item.get('line')} · {item.get('timestamp')} · `{item.get('tool')}`: {text or '[empty]'}"
        )

    lines = [
        "# Codex Trace Timeline",
        "",
        "This is a reading view derived from `data/*.jsonl`. Use the JSONL files for exact filtering.",
        "",
        "## Messages",
        "",
    ]
    lines.extend(message_lines or ["- None."])
    lines.extend(["", "## Commands", ""])
    lines.extend(command_lines or ["- None."])
    lines.extend(["", "## Nonzero Results", ""])
    if nonzero:
        lines.extend(
            f"- line {item.get('line')} · `{item.get('tool')}` exit {item.get('exit_code')}: "
            f"{item.get('command_preview') or '[command unavailable]'} | {item.get('output_preview') or '[empty]'}"
            for item in nonzero
        )
    else:
        lines.append("- None.")
    lines.append("")
    return "\n".join(lines)


def render_agents_md(out: Path, manifest: dict[str, Any], summary: dict[str, Any]) -> None:
    env = Environment(
        loader=FileSystemLoader(SKILL_DIR / "templates"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template("AGENTS.j2")
    content = template.render(manifest=manifest, summary=summary)
    (out / "AGENTS.md").write_text(content, encoding="utf-8")


def print_markdown(manifest: dict[str, Any], summary: dict[str, Any]) -> None:
    counts = summary["counts"]
    table = Table(title="Codex Trace Snapshot")
    table.add_column("Item")
    table.add_column("Count", justify="right")
    for key in ["events", "commands", "results", "nonzero_results", "messages"]:
        table.add_row(key, str(counts[key]))
    console.print(table)
    print(f"OUT_DIR={manifest['run']['out_dir']}")
    console.print(f"[bold]Snapshot:[/bold] {manifest['files']['raw_trace']}")
    console.print()
    console.print("[bold]Next:[/bold]")
    console.print('  cd "$OUT_DIR"')
    console.print("  sed -n '1,160p' AGENTS.md")
    console.print("  jq '.stats' manifest.json")


def print_json(manifest: dict[str, Any], summary: dict[str, Any]) -> None:
    payload = {
        "protocol": manifest["protocol"],
        "skill": manifest["skill"],
        "run": manifest["run"],
        "stats": manifest["stats"],
        "files": manifest["files"],
        "nonzero_results_preview": summary["nonzero_results_preview"][:10],
        "final_answer_preview": summary["final_answer_preview"],
        "warnings": manifest["warnings"],
    }
    console.print_json(data=payload)


@app.command()
def snapshot(
    trace: Annotated[str, typer.Argument(help="codex://threads/<id> or local rollout JSONL path.")],
    out: Annotated[Path | None, typer.Option(help="Run directory.")] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", help="stdout format: markdown or json."),
    ] = "markdown",
    schema: Annotated[bool, typer.Option("--schema", help="Print schema.json content after snapshot.")] = False,
) -> None:
    """Snapshot a Codex trace into a local corpus run directory."""
    if output_format not in {"markdown", "json"}:
        raise typer.BadParameter("--format must be markdown or json")

    source_path = resolve_trace(trace)
    out = out or default_output_dir()
    if out == Path("."):
        raise typer.BadParameter('--out must not be "."; omit --out to use the default run directory')

    prepare_output_dir(out)
    raw_dir = out / "raw"
    data_dir = out / "data"
    views_dir = out / "views"
    raw_trace = raw_dir / "trace.jsonl"
    raw_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    views_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, raw_trace)

    entries = load_entries(raw_trace)
    snapshot = trace_snapshot(raw_trace, entries, display_path="raw/trace.jsonl")
    commands = build_commands(entries)
    command_by_call_id = {command["call_id"]: command for command in commands if command.get("call_id")}
    results = build_results(entries, command_by_call_id)
    messages = build_messages(entries)
    summary = compact_summary(snapshot, entries, commands, results, messages)
    schema_doc = build_schema(entries, snapshot)

    write_jsonl(data_dir / "commands.jsonl", commands)
    write_jsonl(data_dir / "results.jsonl", results)
    write_jsonl(data_dir / "messages.jsonl", messages)

    files = {
        "agents": "AGENTS.md",
        "manifest": "manifest.json",
        "schema": "schema.json",
        "raw_trace": "raw/trace.jsonl",
        "commands": "data/commands.jsonl",
        "results": "data/results.jsonl",
        "messages": "data/messages.jsonl",
        "summary_view": "views/summary.md",
        "timeline_view": "views/timeline.md",
    }
    manifest = {
        "protocol": RUN_PROTOCOL,
        "skill": SKILL_NAME,
        "generated_at": utc_now(),
        "run": {
            "out_dir": str(out),
            "cwd": str(Path.cwd()),
            "command": " ".join(sys.argv),
        },
        "source": {
            "trace": str(source_path),
            "trace_arg": trace,
            "source_kind": "codex rollout JSONL",
        },
        "boundary": [
            "raw/trace.jsonl is a snapshot copy of the resolved trace at snapshot time.",
            "data/*.jsonl are indexes derived from raw/trace.jsonl.",
            "stdout is a short entrypoint; use files in this directory for deeper inspection.",
        ],
        "stats": summary["counts"],
        "files": files,
        "warnings": [],
    }
    (views_dir / "summary.md").write_text(summary_markdown(manifest, summary), encoding="utf-8")
    (views_dir / "timeline.md").write_text(timeline_markdown(messages, commands, results), encoding="utf-8")
    write_json(out / "manifest.json", manifest)
    write_json(out / "schema.json", schema_doc)
    render_agents_md(out, manifest, summary)

    if schema:
        console.print_json(data=schema_doc)
    elif output_format == "json":
        print_json(manifest, summary)
    else:
        print_markdown(manifest, summary)


if __name__ == "__main__":
    app()
