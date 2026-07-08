---
name: brrr-now
description: "Send, test, or integrate brrr.now push notifications when the user wants to be pinged, reminded, or woken outside chat. Not for implementing push notifications inside the user's own product."
metadata:
  version: "5"
---

# brrr Push Notifications

brrr.now 把通知推送到用户的手机上。聊天本身能覆盖的内容，不要推送。

## 理解用户在要什么

用户的原话通常很随意：「跑完叫我」「到点提醒我」「盯着这个部署」。动手之前，把它补全成三个判断：

- 触发事件是什么。通知要挂在能观察到真实结果的位置上。会话内的等待用 harness 自己的等待机制，前台 `sleep` 只在普通 shell 脚本里可靠。跨会话、跨机器的事件，用临时脚本、cron 或 systemd 承载。反复运行的检查循环，交给 `$scheduled-work` 决定调度形态。
- 要多紧急。默认普通，也就是不传 `--interruption-level`。用户表达了「必须马上看到」「吵醒我也行」才升级。听不出来而后果要紧时，问一句：普通通知就行，还是要能吵醒你？
- 送不到怎么办。无人值守工作要依赖通知时，先真发一条测试，确认能送到。送达失败就退回聊天汇报，不要静默吞掉。

用户没有要求过通知而你想主动发时，先问一句，再发第一条。

## 发送

用 sender script [`scripts/brrr-send.sh`](scripts/brrr-send.sh)，flags 传参，`--help` 列出全部。Runtime 检测、endpoint 和鉴权它自己处理。配置缺什么，它失败时会自己说明。

```bash
/bin/bash "<brrr-now skill dir>/scripts/brrr-send.sh" \
  --title "Task complete" \
  --message "long_running_command finished" \
  --thread-id "agent-task"
```

`--dry-run` 校验配置和 payload 但不真发，适合在延迟发送之前确认命令没写错。

同一件事复用同一个 `thread_id`，通知才会在手机上归组。有值得点开的页面就加 `--open-url`。

目标主机上不一定有这个 skill 目录。在本机发送时，直接按绝对路径调用 sender script。要写进 repo、装到远程主机或 systemd 时，把它复制或改编到那一侧的稳定路径。

## exe.dev HTTP Proxy

exe.dev VM 里 sender script 会调用 `https://brrr.int.exe.xyz/v1/send`。这要求 exe.dev 上存在名为 `brrr` 的 HTTP Proxy integration。`notify` mobile notification integration 不是同一个东西，不能当作已配置的 brrr proxy。

```bash
ssh exe.dev integrations add http-proxy \
  --name=brrr \
  --target=https://api.brrr.now/ \
  --bearer="$BRRR_SECRET" \
  --attach=auto:all \
  --comment="Push notifications to the user's devices. Auth is injected by exe.dev. POST JSON to https://brrr.int.exe.xyz/v1/send with title, message, optional thread_id, open_url, and interruption_level. Use only for user-requested pings or task-critical alerts."
```

从 VM 内使用时，先读 `https://reflection.int.exe.xyz/integrations`。不要在 VM 里找 `BRRR_SECRET`，exe.dev 会注入认证。`https://brrr.int.exe.xyz/` 只是 proxy 根路径；发送通知用 `https://brrr.int.exe.xyz/v1/send`。

从 VM 内验证时，先确认 reflection 里能看到 `name=brrr`、`type=http-proxy` 和上面的英文 comment，再向 `https://brrr.int.exe.xyz/v1/send` 发一条真实测试通知。成功信号是 HTTP `202`。

如果用网页表单配置，提交前看 preview，必须是 `--attach=auto:all`。表单可能先自动生成 `tag:brrr`。

## 升级紧急程度

`--interruption-level time-sensitive` 穿透 Focus 和 Notification Summary，用于用户要求尽快看到的通知。`critical` 是闹钟级警报，以吵醒用户为目的，前提是用户已经在 brrr app 里启用 critical alerts。改动 API 字段或 critical alerts 语义之前，先查 <https://brrr.now/docs/>。

## 接进真实工作

launcher 进程正常退出，不代表它拉起的后台工作成功了，所以通知的 hook 要观察真实结果。一次性命令包一层，通知它的成败。repo 里的脚本直接调 sender script。systemd 服务加 `OnFailure=`。queue worker 挂在 task result 上。重要主机加 heartbeat，沉默本身就是告警。

具体做法看 [`references/integration-patterns.md`](references/integration-patterns.md)，Linux service unit 看 [`references/systemd-pattern.md`](references/systemd-pattern.md)。
