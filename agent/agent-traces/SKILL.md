---
name: agent-traces
description: >-
  查本机和云端的 Agent 会话记录，找回以前的决定、命令和上下文，或看另一个 Agent 现在在做什么时使用。
---

# 查 Agent 会话记录

结论附上来源：哪个 Agent、会话 ID、时间点。只读到对话、没读到命令的部分说清楚。记录里有 token、私聊和客户数据，引用时脱敏。

## 记录在哪

| 来源 | 位置 | 坑 |
| --- | --- | --- |
| Codex | `~/.codex/state_5.sqlite` 的 `threads` 表（`cwd`、`title`、`git_branch`、`updated_at_ms`、`rollout_path`）；正文在 `rollout_path` 指向的 JSONL；旧会话在 `~/.codex/archived_sessions/*.jsonl.zst` | 命令在 `response_item` 的 `custom_tool_call` 里，`input` 是 JS 代码 `tools.exec_command({cmd, workdir})`，要从里面抠出 `cmd`；push 常写成 `git -c … push`，按 `git push` 搜会漏。`thread_history_1.sqlite` 落后几天，不能拿来判断最新状态。`history.jsonl` 从 2026-10-15 起不再更新。续接会话的文件名是 `<父 ID>_<子 ID>`。 |
| Claude Code | `~/.claude/projects/<cwd 中 / 换成 ->/<session>.jsonl`，子 Agent 在同名目录的 `subagents/`；用户输入的索引在 `~/.claude/history.jsonl`（`display`、`project`、`sessionId`） | 找用户原话先查 `history.jsonl`，秒级命中。正文总量几十 GB，先按目录和修改时间筛。 |
| pi | `~/.pi/agent/sessions/<cwd>/<时间>_<ID>.jsonl` | — |
| Amp | 只在云端：`amp threads search`／`list`／`markdown` | `search` 是全文匹配，噪声大，用 `repo:`、`after:7d` 等过滤收窄，命中后用 `markdown` 读全文核对。本地文件里搜不到 Amp 的内容。 |
| Codex Cloud | 只在云端：`codex cloud list`／`status` | — |

搜关键词时，会话里注入的 Skill 列表、`ls` 和 `git pull` 输出会制造大量假命中。找「用户怎么定的」只看用户消息。

存储格式随版本变（`state_5`、`logs_2` 里的数字就是版本号）。位置对不上时先看现场，再更新这张表。

`amp threads import` 会把本机的 Codex、Claude Code 会话上传成 Amp 线程，属于对外写入，查东西时不要用。

## 工具

按关键词搜很久以前的 Codex 对话时，可以用 [sherlog](https://github.com/catoncat/sherlog) 的 `shlog`（Homebrew tap `catoncat/sherlog`）给会话建全文索引。`find` 毫秒级返回，并给出 `read-range`／`read-page` 的下一步命令。用之前先 `shlog sync`，它默认只同步 Codex。用法以 `shlog <子命令> --help` 为准。

- 它只索引对话文字，不含命令和工具输出。要看 Agent 跑过什么命令、改了什么，读原始 JSONL。
- 0.6.2 版的 `shlog sync --source claude-code` 会报 `index invariant check failed: … stale next_seq`，整批不写入。这时 Claude Code 只能读原始文件。

有别的开源 CLI 能读这些记录时，按任务挑最合适的，并补进上面的表。
