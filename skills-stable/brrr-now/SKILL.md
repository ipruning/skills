---
name: brrr-now
description: "Send, test, or integrate brrr.now push notifications when the user wants to be pinged, reminded, or woken outside chat. Not for implementing push notifications inside the user's own product."
metadata:
  version: "6"
---

# brrr Push Notifications

聊天本身能覆盖的内容，不要推送。

## 理解用户在要什么

用户的原话通常很随意：「跑完叫我」「到点提醒我」「盯着这个部署」。动手之前，把它补全成三个判断：

- 触发事件是什么。通知要挂在能观察到真实结果的位置上。会话内的等待用 harness 自己的等待机制，前台 `sleep` 只在普通 shell 脚本里可靠。要延后或反复触发的调度，一次性提醒和检查循环都交给 `$schedule-agent-work` 或 harness 自己的调度机制。只有目标主机上没有可用的调度器时，才自己落临时脚本、cron 或 systemd。
- 要多紧急。默认普通，也就是不传 `--interruption-level`。用户表达了「必须马上看到」「吵醒我也行」才升级。听不出来而后果要紧时，问一句：普通通知就行，还是要能吵醒你？
- 送不到怎么办。无人值守工作要依赖通知时，先真发一条测试，让用户确认手机上收到了。HTTP `202` 只证明 API 收下，不证明设备端送达。送达失败就退回聊天汇报，不要静默吞掉。

用户没有要求过通知而你想主动发时，先问一句，再发第一条。

## 发送

用 sender script [`scripts/brrr-send.sh`](scripts/brrr-send.sh)，flags 传参，`--help` 列出全部。Runtime 检测、endpoint 和鉴权它自己处理。本机缺配置时它失败会自己说明缺什么。exe.dev VM 上的失败先按下面 exe.dev 一节核对 proxy integration。

```bash
/bin/bash "<brrr-now skill dir>/scripts/brrr-send.sh" \
  --title "Task complete" \
  --message "long_running_command finished" \
  --thread-id "agent-task"
```

`--dry-run` 校验 payload 并报告 `auth_mode`，不真发，配置缺失时同样以退出码 3 失败，适合在延迟发送之前确认命令没写错。凭证是否有效，只有真发一条能证明。

同一件事复用同一个 `thread_id`，通知才会在手机上归组。有值得点开的页面就加 `--open-url`。

目标主机上不一定有这个 skill 目录。在本机发送时，直接按绝对路径调用 sender script。要写进 repo、装到远程主机或 systemd 时，把它复制或改编到那一侧的稳定路径。

## exe.dev HTTP Proxy

exe.dev VM 里 sender script 会调用 `https://brrr.int.exe.xyz/v1/send`，这要求 exe.dev 上存在名为 `brrr` 的 HTTP Proxy integration。`notify` mobile notification integration 不是同一个东西，不能当作已配置的 brrr proxy。`https://brrr.int.exe.xyz/` 只是 proxy 根路径，发送通知用 `https://brrr.int.exe.xyz/v1/send`。

先查再配：VM 内读 `https://reflection.int.exe.xyz/integrations`，看到 `name=brrr`、`type=http-proxy` 就直接用。缺失才创建。`BRRR_SECRET` 取自本机的 `~/.config/brrr/env` 或 `~/.config/notify/brrr.env`，从不来自 VM 内，VM 里的请求由 exe.dev 注入认证。执行 add 前确认变量非空，空 bearer 会创建一个静默坏掉的 integration。

```bash
ssh exe.dev integrations add http-proxy \
  --name=brrr \
  --target=https://api.brrr.now/ \
  --bearer="$BRRR_SECRET" \
  --attach=auto:all \
  --comment="Push notifications to the user's devices. Auth is injected by exe.dev. POST JSON to https://brrr.int.exe.xyz/v1/send with title, message, optional thread_id, open_url, sound, interruption_level, and volume (critical only). Use only for user-requested pings or task-critical alerts."
```

如果用网页表单配置，提交前看 preview，必须是 `--attach=auto:all`。表单可能先自动生成 `tag:brrr`。

配好后从 VM 内向 `https://brrr.int.exe.xyz/v1/send` 发一条真实测试通知。HTTP `202` 说明 proxy 打通，设备端送达仍以用户确认为准。

## 紧急程度

`--interruption-level` 有四档，省略等于 `active`：

- `passive`：静默进通知列表，不打扰，适合 heartbeat 这类沉默即告警的流。
- `active`：普通提醒，默认档，通常直接省略。
- `time-sensitive`：穿透 Focus 和 Notification Summary，用于用户要求尽快看到的通知。
- `critical`：闹钟级警报，以吵醒用户为目的，前提是用户已经在 brrr app 里启用 critical alerts。

这些语义随上游漂移，与 <https://brrr.now/docs/> 或实测冲突时，以 docs 和实测为准。

## 接进真实工作

launcher 进程正常退出，不代表它拉起的后台工作成功了，所以通知的 hook 要观察真实结果。一次性命令包一层，通知它的成败。repo 里的脚本直接调 sender script。systemd 服务加 `OnFailure=`。queue worker 挂在 task result 上。重要主机加 heartbeat，沉默本身就是告警，但检测沉默要另一套长期运行的监控，那套体系的设计与部署归 `$end-to-end-monitoring`，本 skill 只负责把 brrr 挂到已有观察点上。

具体做法看 [`references/integration-patterns.md`](references/integration-patterns.md)，Linux service unit 看 [`references/systemd-pattern.md`](references/systemd-pattern.md)。
