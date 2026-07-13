---
name: summarize-lark-meetings
description: "Use when the user wants to review or summarize Feishu/Lark meetings over a date range, such as 总结这两周的会 or a meeting weekly report: find minute_tokens, pull transcript files, inspect coverage and duplicate evidence, build Chinese prompts, and optionally fan summaries out to Amp. Do not use for a single minute_token or single-meeting lookup (that is the lark skill), or for turning chat history into a report corpus — that is lark-chat-corpus."
metadata:
  version: "5"
---

# Summarize Lark Meetings

单会议、单 `minute_token` 或未来日程不走这条流水线：读 lark-cli 的内嵌 skill，`lark-cli skills read lark-vc` 管单个会议，`lark-minutes` 管单个 token，`lark-calendar` 管日历事件。

## 文件夹即接口

脚本是 `scripts/lark_meeting_stt.py`。每次运行把状态全物化到一个 run 目录，命令之间靠文件传递，你在阶段之间读证据、改选择。

run 根下你要读或改的文件：

- `coverage.md` 给登录用户、日期范围、各源计数、日历和 VC 覆盖证据。`pull` 前必读，它告诉你可能漏了哪些会。漏会不阻塞流水线：继续跑，把漏会清单和 hint 写进最终交付。用户点名要补某场会时走 `lark-cli` 内嵌的 `lark-minutes` 单独处理，产物不并入本 run。
- `duplicates.md` 和 `duplicates.json` 是重复证据，脚本从不在这里改选择。
- `selected.txt` 由 `pull` 写出全部成功拉取的 token，`prompts` 读取。唯一的编辑点：读完 dedup 证据后编辑它，跳掉重复。重跑 `pull` 时只要现有内容与本次全量清单不同就保留原样，新的全量清单落在 `selected.txt.new`。
- `minutes-found.json`、`pulled.md`、`prompt-index.json` 分别是找到的全部 token、导出结果、当前 prompt 列表。

生成目录 `raw/`、`minutes/`、`prompts/`、`summaries/` 是各阶段的产物。

## 流水线

从这个 skill 目录跑。相对日期先解析成 `YYYY-MM-DD` 再传。顺序是硬依赖，每步读上一步的产物。参数细节看 `<command> --help`。

```bash
run="$HOME/Downloads/lark-meeting-$(date +%Y%m%d-%H%M%S)"
uv run --script scripts/lark_meeting_stt.py list --start YYYY-MM-DD --end YYYY-MM-DD --run "$run"
sed -n '1,220p' "$run/coverage.md"                  # 读覆盖，确认没漏会
uv run --script scripts/lark_meeting_stt.py pull --run "$run"
uv run --script scripts/lark_meeting_stt.py check --run "$run"
sed -n '1,220p' "$run/duplicates.md"                # 读重复证据，据此改 selected.txt
uv run --script scripts/lark_meeting_stt.py prompts --run "$run"
uv run --script scripts/lark_meeting_stt.py summarize --run "$run"
```

`pull` 拉取 `minutes-found.json` 里全部妙记，唯一的选择编辑点在 `check` 之后：读 duplicates 证据，从 `selected.txt` 删掉重复。`prompts` 每次重建并写出 `prompt-index.json`，只有它 `"ok": true` 才跑 `summarize`。导出失败的 token 留在 `pulled.md`，别拿会议纪要或总结顶替失败的 transcript。

`summarize` 默认不传 Amp mode 和 reasoning effort，由本机安装的 Amp 选择当前默认值。只有用户明确要求才传 `--amp-mode` 或 `--amp-effort`，取值是否被支持先看 `amp --help`。脚本默认同时运行 2 个 Amp 任务，并重试 Bun keyring 的 `ERR_DLOPEN_FAILED` 瞬时加载失败，其他 Amp 错误不重试。同一 prompt 已有成功总结时，重跑会复用原文件，prompt 变化后才重新总结。`summaries/` 只保留当前选择对应的总结文件。Amp 慢或限流就调低 `--concurrency`，长会调高 `--timeout-seconds`。

用户指定用当前 agent 或别的工具总结时，跑到 `prompts` 为止，自己读 `prompts/` 下的 prompt 文件出总结，不跑 `summarize`。

## 重复证据

`check` 把重复分三档，给你判断，不替你删：

- `强重复`：全文 SHA-256 相同。
- `高度可疑`：前 80 行规范化 hash 相同。
- `弱可疑`：首行相同，或行数接近且时长与标题其一吻合。

强重复直接跳。拿不准就保留，多一份重复总结的代价低于漏一场会。需要判断时打开相关的 `minutes/<token>/transcript.txt` 再定。

## 输出契约

自动化用 `--format json`，加在子命令之后。命令进入自身业务逻辑后，stdout 是一个 JSON 对象，进度和依赖命令输出走 stderr。业务失败退出码 1，json 的 stdout 带 `"ok": false`、`error` 和 `exit_code`，部分失败的明细看报告里的 `counts`、`failed` 或 `oversized`。Typer 语法错误，比如缺必填或未知命令，退出码 2、help 走 stderr。冷启动 `uv run --script` 可能装依赖并把日志写 stderr，别把 stderr 当结果解析。

## 规则

- 所有 raw transcript 都留着。跳过会议靠编辑 `selected.txt`，不靠删 `minutes/<token>/transcript.txt`。
- 重复分组是证据，不是删除指令。
- 改过 `selected.txt` 后重新跑 `prompts`。
- `prompt-index.json` 缺失或 `"ok": false` 时不要跑 `summarize`。
