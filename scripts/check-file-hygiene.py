# /// script
# requires-python = ">=3.14"
# ///
"""Check text-file hygiene without modifying files."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path


def check_file(path: Path) -> list[str]:
    data = path.read_bytes()
    issues: list[str] = []

    lines = data.split(b"\n")
    for line_number, line in enumerate(lines, start=1):
        body = line[:-1] if line.endswith(b"\r") and line_number < len(lines) else line
        if body.rstrip() != body:
            issues.append(f"{path}:{line_number}: trailing whitespace")

    if data:
        content_end = len(data)
        while content_end > 0 and data[content_end - 1] in b"\r\n":
            content_end -= 1
        ending = data[content_end:]
        if content_end == 0:
            issues.append(f"{path}: file containing only line endings should be empty")
        elif ending not in {b"\n", b"\r", b"\r\n"}:
            issues.append(f"{path}: file must end with exactly one line ending")

    return issues


def main(argv: Sequence[str] | None = None) -> int:
    filenames = list(argv if argv is not None else sys.argv[1:])
    failed = False
    for filename in filenames:
        path = Path(filename)
        try:
            issues = check_file(path)
        except OSError as exc:
            issues = [f"{path}: {exc}"]
        for issue in issues:
            print(issue)
        failed |= bool(issues)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
