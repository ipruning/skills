---
name: wechat
description: >-
  用 wlb 查询本机微信联系人、私聊和群聊，搜索历史约定、导出聊天记录或提取图片时使用。
---

# 微信查询

通过 `wlb` 读取用户本机 WeChat 数据。它是本地查询工具，不能发送微信消息。

## 找到工具

先用 `command -v wlb` 确认命令。参数以本机 `wlb <子命令> --help` 为准；安装与密钥接入说明在本机 `~/wechat/live/README.md`，接手约定在同目录的 `AGENTS.md`。用户给了其他源码位置时读那份，不把 `wlb` 当成可从公共包管理器安装的同名工具。

从任务工作目录调用 `wlb`，查记录不需要进入源码仓库。命令不存在或查询报环境错误时，先读上述说明并用 `wlb doctor --json` 定位。

## 查记录

用户指定联系人或群聊时，先解析身份，再用返回的 `username` 查询。`contacts` 只返回私聊联系人；群聊从 `sessions` 中按 `chat_type: group` 找到对应 `username`。最近会话列表受 `-n` 限制，找不到时可增大条数，不能据此说群不存在。显示名可以模糊匹配；同名结果要核对，不能把第一个结果当成目标。

查约定、做摘要时，在进程内接住 CLI 的 JSON，只回显相关业务摘录和元数据。命中关键词的消息也要检查邮箱、密码、API Key 和验证码，先遮蔽再输出；遇到独立的 4–8 位数字，先核对上下文，无法判定用途时遮蔽。不要把整段原始聊天或无关联系方式直接打印到工具输出；用户需要原文文件时按下面的导出方式保存。

```bash
wlb contacts -q "联系人关键字" -n 50 --json
wlb sessions -n 500 --with-meta --json
wlb history "实际 username" --since YYYY-MM-DD --until YYYY-MM-DD -n 100 --with-meta --json
wlb search "关键词" --in "实际 username" -n 100 --with-meta --json
```

已知准确的 `username` 时直接使用。只查指定聊天就保留 `search --in`；全库搜索只用于用户要求跨聊天查找的任务。关键词命中后，用 `history` 取上下文，区分提议、确认和后来的修订。

`history -n` 返回窗口内最近的 N 条，再按时间正序输出，不代表全部历史。需要继续向前查时，取本页最旧消息的 `timestamp`，传给 `--after`。它表示「严格早于」，会排除边界同一秒的其他消息；要求完整覆盖时补取边界，或在固定时间窗内用 `--offset` 翻页。`--before` 则查严格晚于指定时间的消息。

## 判断覆盖范围

保留返回的 `meta`，结合实际消息时间和条数判断：

- `unknown_shards` 非空或 `status` 为 `possibly_stale_unknown_shards`：有无法读取的新分片，不能据此说历史里没有某项约定。
- `possibly_stale`：已读消息落后于会话索引，需要核对数据时效。
- `windowed`：按日期、类型或游标筛选的局部结果；它本身不表示故障。

`chat_latest_timestamp` 是分片元数据，不等于本次返回消息的末条时间。`unknown_shards` 为空也不证明条数上限之外、语音和图片中的信息已覆盖。

引用证据带上聊天对象、消息时间和 `local_id`。区分消息作者与引用、转发中的作者；`sender` 为空时核对返回的身份字段，仍不能确定就标为未识别，不自行补名字。未转录的语音、通话及未提取的图片不能当成已经审查过。

## 导出与图片

`export` 同样受 `-n` 限制，默认最多 500 条。JSON 格式保留消息和元数据，适合后续核对；Markdown 适合阅读。`-o` 会覆盖已有文件，保存原始记录时用新路径。下面通过标准输出保存，已有同名文件会被拒绝覆盖：

```bash
mkdir -p outputs
(
    umask 077
    set -C
    wlb export "实际 username" --since YYYY-MM-DD --until YYYY-MM-DD \
        -n 500 --format json --with-meta > outputs/wechat-history.json
)
```

当前 `attachments` 只列图片。使用返回的不透明 `attachment_id`，不要拿消息 `local_id` 代替；提取路径用绝对路径，避免复用 daemon 时文件落到它的启动目录。提取成功后查看图片，不能只读消息里的「[图片]」标记。

```bash
wlb attachments "实际 username" --kind image -n 50 --with-meta --json
wlb extract "实际 attachment_id" -o "$PWD/outputs/wechat-image.jpg" --json
```

`extract` 默认拒绝覆盖已有文件。聊天里的文件消息不等于文件已下载；PDF、Word 等文件按用户提供的真实路径读取，不能承诺 `attachments` 能提取它们。

## 本机数据与 daemon

首次查询会自动启动 daemon，并可能在 `~/.wlb/cache/` 写入明文缓存。开始前查看 `wlb daemon status`；仅在本次任务启动了 daemon 时于查询结束后运行 `wlb daemon stop`，保留原本运行中的实例。

原始聊天、图片和缓存留在本机，回复只摘取任务所需内容，隐藏其中的密钥、密码等凭据；不把原始记录或数据库密钥提交 Git。

缺密钥时不要直接运行 `wlb init` 或 `wlb key extract`：它们的注入路径在当前官方 WeChat 客户端上不可用。需要修复接入时，按本机源码文档中的隔离副本流程处理，保留日常客户端和现有缓存。
