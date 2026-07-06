---
name: lark-meeting-summary
description: "Use when a user asks for a date-range Feishu/Lark Minutes collection: find minute_tokens, pull transcript files, inspect coverage and duplicate evidence, build Chinese prompts, or run Amp summaries. Do not use for a single minute_token lookup."
metadata:
  version: "2"
---

# Lark Meeting Amp Summary

按日期范围收集 Feishu/Lark 妙记、导出 transcript、看覆盖和重复证据、生成中文 prompt、跑 Amp 总结。参数细节看 `<command> --help`，正文只讲管道形状、文件夹接口和 CLI 强制不了的判断。

单个已知会议用 `lark-vc`，单个已知 `minute_token` 用 `lark-minutes`，未来日历事件用 `lark-calendar`。

## 文件夹即接口

脚本是 `scripts/lark_meeting_stt.py`。每次运行把状态全物化到一个 run 目录，命令之间靠文件传递，你在阶段之间读证据、改选择。

run 根下你要读或改的文件：

- `coverage.md` 给登录用户、日期范围、各源计数、日历和 VC 覆盖证据。`pull` 前必读，它告诉你可能漏了哪些会。
- `duplicates.md` 和 `duplicates.json` 是重复证据，脚本从不在这里改选择。
- `selected.txt` 由 `pull` 写出全部成功拉取的 token，`prompts` 读取。唯一的编辑点：读完 dedup 证据后编辑它，跳掉重复。
- `minutes-found.json`、`pulled.md`、`prompt-index.json` 分别是找到的全部 token、导出结果、当前 prompt 列表。

跳过一个会靠从 `selected.txt` 删对应 token，不要删 `minutes/<token>/transcript.txt`。

生成目录 `raw/`、`minutes/`、`prompts/`、`summaries/` 是各阶段的产物。

## 流水线

从这个 skill 目录跑。相对日期先解析成 `YYYY-MM-DD` 再传。顺序是硬依赖，每步读上一步的产物。

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

`pull` 拉取 `minutes-found.json` 里全部妙记，唯一的决策关卡在 `check` 之后：读 duplicates 证据，从 `selected.txt` 删掉重复。`prompts` 每次重建并写出 `prompt-index.json`，只有它 `"ok": true` 才跑 `summarize`。导出失败的 token 留在 `pulled.md`，别拿会议纪要或总结顶替失败的 transcript。Amp 慢或限流就调低 `--concurrency`，长会调高 `--timeout-seconds`，细节 flag 看 `--help`。

## 重复证据

`check` 把重复分三档，给你判断，不替你删：

- `强重复`：全文 SHA-256 相同。
- `高度可疑`：前 80 行规范化 hash 相同。
- `弱可疑`：首行相同，或行数接近且时长、标题证据吻合。

需要判断时打开相关的 `minutes/<token>/transcript.txt` 再定。

## 输出契约

自动化用 `--format json`，加在子命令之后。命令进入自身业务逻辑后，stdout 是一个 JSON 对象，进度和依赖命令输出走 stderr。业务错误退出码 1，json 下 stdout 是 `{"ok": false, "error": "...", "exit_code": 1}`。Typer 语法错误，比如缺必填或未知命令，退出码 2、help 走 stderr。冷启动 `uv run --script` 可能装依赖并把日志写 stderr，别把 stderr 当结果解析。

## 规则

- 所有 raw transcript 都留着。
- 重复分组是证据，不是删除指令。
- 跳过会议靠编辑选择文件，不靠删 transcript。
- 改过 `selected.txt` 后重新跑 `prompts`。
- `prompt-index.json` 缺失或 `"ok": false` 时不要跑 `summarize`。
