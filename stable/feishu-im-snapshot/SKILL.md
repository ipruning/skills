---
name: feishu-im-snapshot
description: >
  Snapshot recent Feishu/Lark chat history into a local corpus for reports and
  analysis. Use for weekly reports, chat summaries, action items, or attention
  lists. Triggers: 最近一周, 周报, 我该关注什么, 下周任务, 飞书聊天总结,
  TCG 行业群摘要.
metadata:
  version: "0.5.0"
---

# Feishu IM Snapshot

Snapshot recent Feishu/Lark IM chats into a local corpus directory, then read that directory.

```zsh
uv run scripts/snapshot.py --days 7 --out "$RUN_DIR"
cd "$RUN_DIR"
sed -n '1,160p' AGENTS.md
jq '.stats' manifest.json
```

If `--out` is omitted, the snapshotter creates a directory under `$TMPDIR/agent-corpus-runs/feishu-im-snapshot/`.

The output directory contains:

- `AGENTS.md`: run-specific reading protocol.
- `manifest.json`: source, boundary, stats, warnings, and file index.
- `schema.json`: JSONL field descriptions.
- `raw/messages.jsonl`: raw messages returned by `+messages-search` before ignored-chat removal.
- `data/messages.jsonl`, `data/chats.jsonl`, `data/reactions.jsonl`: query indexes.
- `views/direct/*.md`, `views/group/*.md`: Markdown reading corpus.

Use `views/` as the primary reading corpus. Use `jq`, `rg`, or `duckdb -no-init` on the output files for deeper inspection. Do not paste full `raw/` or full JSONL indexes into context.
