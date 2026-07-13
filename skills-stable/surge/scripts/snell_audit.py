#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

"""Compatibility entrypoint for the operate-snell audit CLI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# TODO(cleanup): trigger=date:2026-10-13; action=remove this wrapper and its compatibility test
target = Path(__file__).resolve().parents[2] / "operate-snell" / "scripts" / "snell_audit.py"
if not target.is_file():
    raise SystemExit(f"operate-snell audit CLI not found: {target}")
os.execv(target, [str(target), *sys.argv[1:]])
