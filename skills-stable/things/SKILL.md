---
name: things
description: "Read-only local macOS Things queries and summaries when the user asks about their Things tasks, Today list, Inbox, projects, tags, completed or logbook history, or task search. Read-only, never writes."
metadata:
  version: "2"
---

# Things

只读地查本机 macOS Things，把用户的口语问题翻成一次 `things_query.py` 查询，不写入。用户要改 Things 就说明这是只读工具，问要不要换一个单独的、经批准的写入方式。

入口是 `scripts/things_query.py`，通过 `uv run --script` 跑，路径按这个 skill 目录的绝对路径解析。collection、filter、flag 的权威清单是 `--help`。

```bash
SKILL_DIR=/absolute/path/to/things
uv run --script "$SKILL_DIR/scripts/things_query.py" --collection today --format json
uv run --script "$SKILL_DIR/scripts/things_query.py" --help
```

## 把问题翻成查询

用户不说 collection 名，也不说 flag。听意图，选最小够用的 collection 加 filter。能猜就猜，查错代价小，再查一次就行，不用停下来问。

| 用户会说 | collection + filter |
|---|---|
| 今天要干嘛、手头有啥 | `--collection today` |
| 收件箱里有啥没整理 | `--collection inbox` |
| 有 deadline 的、快到期 | `--collection deadlines` |
| 找关于 X 的任务 | `--collection todos --search X` |
| X 这事办完没、这周做完了啥 | `--collection completed --search X` |
| 某个项目或 tag 下的 | `--collection projects` 或 `--collection tags` |
| 最近加的、这周新增 | `--collection todos --last 1w` |

这张表是常见映射，不是全集。翻不准或用户问了别的，跑 `--help` 看还有哪些 collection 和 filter，比如按状态筛的 `--status`、限量的 `--limit`。用户说「today」「明天」「昨天」这类相对日子时，先跑 `date '+%Y-%m-%d %H:%M:%S %Z %z'` 确认本机日期和时区。Things Today 是预测视图，不是简单的 `start_date == 今天`，语义细节看 reference。

## 输出纪律

- 探索性地查先用 `--count-only` 给数量，别一上来倒出全部任务。
- 用户要「看」任务再列 title，按 Things 顺序。默认不带 `notes`、UUID、数据库路径，用户明确要 notes 才加 `--include-notes`。
- 中文提问用中文答。相对日子用 `date` 拿到的本机绝对日期，比如「按本机 <YYYY-MM-DD> <TZ> 的 Today 列表」。结果是 Things Today 预测视图而非精确日期过滤时，点明这一点。

## reference

日期语义、`today()` 漏算的未生成重复任务、数据库路径、权限报错，读 `references/things-semantics.md`。
