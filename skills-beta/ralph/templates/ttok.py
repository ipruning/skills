#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["tiktoken==0.12.0"]
# ///
"""Count tokens using tiktoken o200k_base encoding.

Usage:
  uv run --script ./ttok.py path/to/file.md
  uv run --script ./ttok.py < file.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOKENIZER = "o200k_base"


def count_tokens(text: str) -> int:
    import tiktoken

    enc = tiktoken.get_encoding(TOKENIZER)
    return len(enc.encode(text, disallowed_special=()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Count tokens with tiktoken.")
    parser.add_argument("path", nargs="?", help="Input file path. If omitted, read stdin.")
    args = parser.parse_args()

    if args.path:
        text = Path(args.path).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        parser.error("provide a file path or pipe stdin")

    print(count_tokens(text))


if __name__ == "__main__":
    main()
