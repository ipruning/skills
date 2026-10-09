#!/usr/bin/env python3
"""Generate tool-specific exclusions from Skillshare's package inventory."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# file, block name, comment prefix, indentation, entry format
BLOCKS = (
    (".typos.toml", "typos", "#", "    ", "directory"),
    (".markdownlint-cli2.yaml", "markdownlint", "#", "    ", "yaml"),
    ("biome.jsonc", "biome", "//", "            ", "biome"),
    ("pyproject.toml", "ruff", "#", "    ", "directory"),
    ("pyproject.toml", "ty", "#", "    ", "directory"),
    ("pyproject.toml", "tombi", "#", "    ", "glob"),
    ("prek.toml", "prek", "#", "", "regex"),
    (".autocorrectignore", "autocorrect", "#", "", "ignore"),
)


def render_entries(entries: list[str], kind: str, indent: str) -> str:
    if kind == "regex":
        expression = "|".join(f"^{re.escape(entry)}/" for entry in entries) or "^$"
        return f"exclude = {json.dumps(expression)}\n"
    if kind == "yaml" and not entries:
        return f"{indent}[]\n"
    lines = []
    for entry in entries:
        if kind == "ignore":
            line = f"{entry}/"
        elif kind == "yaml":
            line = f"- {json.dumps(entry + '/')}"
        elif kind == "biome":
            line = f"{json.dumps('!!' + entry)},"
        else:
            suffix = "/**" if kind == "glob" else "/"
            line = f"{json.dumps(entry + suffix)},"
        lines.append(f"{indent}{line}\n")
    return "".join(lines)


def sync_excludes(root: Path, *, write: bool = False) -> list[str]:
    metadata = json.loads((root / ".metadata.json").read_text())
    entries = sorted(entry for entry in metadata["entries"] if not entry.startswith("_"))
    rendered: dict[str, str] = {}
    for filename, name, comment, indent, kind in BLOCKS:
        source = rendered.get(filename)
        if source is None:
            source = (root / filename).read_text()
        start = f"{indent}{comment} BEGIN GENERATED LINT EXCLUDES: {name}\n"
        end = f"{indent}{comment} END GENERATED LINT EXCLUDES: {name}\n"
        if source.count(start) != 1 or source.count(end) != 1:
            raise ValueError(f"{filename}: expected one generated block for {name}")
        before, remainder = source.split(start)
        _, after = remainder.split(end)
        rendered[filename] = before + start + render_entries(entries, kind, indent) + end + after

    changed = [name for name, content in rendered.items() if (root / name).read_text() != content]
    if write:
        for name in changed:
            (root / name).write_text(rendered[name])
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Update generated blocks")
    args = parser.parse_args()
    try:
        changed = sync_excludes(Path(__file__).resolve().parents[1], write=args.write)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")
    if changed and not args.write:
        print("Stale lint exclusions: " + ", ".join(changed))
        print("Run mise run update-lint-excludes after changing installed packages.")
        return 1
    print("Updated: " + ", ".join(changed) if changed else "Lint exclusions match Skillshare metadata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
