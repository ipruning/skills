---
name: codex-trace-inspect
description: >
  Snapshot Codex threads, codex://threads links, and rollout JSONL into a local
  corpus for audit, comparison, indexing, and focused inspection.
metadata:
  version: "0.3.0"
---

# Codex Trace Inspect

Codex traces are local JSONL event streams. Create a run directory, then inspect that directory instead of loading the whole trace into context.

```zsh
uv run scripts/snapshot.py 'codex://threads/<id>' --out "$RUN_DIR"
cd "$RUN_DIR"
sed -n '1,160p' AGENTS.md
jq '.stats' manifest.json
```

If `--out` is omitted, the snapshotter creates a directory under `$TMPDIR/agent-corpus-runs/codex-trace-inspect/`.

The output directory contains:

- `AGENTS.md`: run-specific reading protocol.
- `manifest.json`: source, boundary, stats, and file index.
- `schema.json`: JSONL fields and trace payload key sets.
- `raw/trace.jsonl`: snapshot copy of the resolved trace.
- `data/commands.jsonl`, `data/results.jsonl`, `data/messages.jsonl`: query indexes.
- `views/summary.md`: human-readable summary.
- `views/timeline.md`: compact chronological reading view.

Use `jq`, `rg`, or `duckdb -no-init` on the output files for deeper inspection. Do not paste full `raw/` or full JSONL indexes into context.
