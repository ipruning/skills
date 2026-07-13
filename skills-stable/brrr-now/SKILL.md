---
name: brrr-now
description: "Send, test, or integrate brrr.now push notifications when the user wants to be pinged, reminded, or woken outside chat. Not for implementing push notifications inside the user's own product."
metadata:
  version: "8"
---

# brrr Push Notifications

聊天本身能覆盖的内容，不要推送。

## 理解用户在要什么

用户的原话通常很随意：「跑完叫我」「到点提醒我」「盯着这个部署」。动手之前，把它补全成四个判断：

- 触发事件是什么。通知要挂在能观察到真实结果的位置上。会话内的等待用 harness 自己的等待机制，前台 `sleep` 只在普通 shell 脚本里可靠。要延后或反复触发的调度，一次性提醒和检查循环都交给 `$schedule-agent-work` 或 harness 自己的调度机制。只有目标主机上没有可用的调度器时，才自己落临时脚本、cron 或 systemd。
- 接收者看到通知时是否能重新建立情景。通知必须独立说清对象、状态、影响和行动，不能依赖当前聊天或把原始 health report 当正文。
- 要多紧急。默认普通，也就是不传 `--interruption-level`。用户表达了「必须马上看到」「吵醒我也行」才升级。听不出来而后果要紧时，问一句：普通通知就行，还是要能吵醒你？
- 送不到怎么办。无人值守工作要依赖通知时，先真发一条测试，让用户确认手机上收到了。HTTP `202` 只证明 API 收下，不证明设备端送达。送达失败就退回聊天汇报，不要静默吞掉。

用户没有要求过通知而你想主动发时，先问一句，再发第一条。

## 写通知

把通知写成一张能独立阅读的事件卡片，不写成日志摘录。

- `title` 写最小可操作对象和当前结论：`<stable identity>: <state change or result>`。主机事件用 hostname 或 instance name，不写宽泛的 `CI VM warning`。只有 IP 能帮助区分或接手时才放在 `subtitle`；公网 IP 或敏感地址默认留在详情页。
- `subtitle` 写次级定位：角色、环境、provider、必要时的 IP 或时间窗口。没有有用信息就省略。
- `message` 按「发生了什么；当前影响。需要做什么」组织。无须操作也明确写出。只保留会改变判断的事实，不放原始字段、完整日志、长指标列表或未解释的内部术语。
- `open_url` 指向接手页：失败 job、日志、incident、runbook 或诊断报告。详情放在那里，不挤进锁屏。
- 锁屏默认可见。凭据、客户数据、完整请求和敏感路径不进入标题、subtitle 或正文。

标题单独出现时应能回答「哪个对象现在怎样了」。正文应让接收者在几秒内知道影响和行动。不要承诺尚未实现的自动升级、重试或恢复行为。

BRRR 是单向投递，不是 ticket 或 incident backend。`thread_id` 只让相关通知在 Notification Center 归组，不去重、不替换旧通知，也不提供 acknowledge 或 resolve。生产者必须按状态变化通知：重复采样在源头累计，越过频率、时长或影响阈值时才升级。系统健康且无须行动的事件通常不推送，确需留痕时用 `passive`。只有此前通知过故障时才发送恢复通知。

## 发送

用 sender script [`scripts/brrr-send.sh`](scripts/brrr-send.sh)，flags 传参，`--help` 列出全部。Runtime 检测、endpoint 和鉴权它自己处理。显式加载的 `BRRR_SECRET` 优先；没有显式凭据且处于 exe.dev VM 时，才回退到 HTTP Proxy integration。本机缺配置时它失败会自己说明缺什么。

```bash
/bin/bash "<brrr-now skill dir>/scripts/brrr-send.sh" \
  --title "payments/main: build passed" \
  --subtitle "GitHub Actions · production" \
  --message "All required checks passed. No action needed." \
  --thread-id "payments-main-build" \
  --open-url "https://example.invalid/builds/123"
```

`--dry-run` 校验 payload 并报告 `auth_mode`，不真发，配置缺失时同样以退出码 3 失败，适合在延迟发送之前确认命令没写错。凭证是否有效，只有真发一条能证明。

真发成功后，sender stdout 只报告 `auth_mode` 和 `http_status`，不输出 endpoint、payload、响应正文或 secret。成功的 `2xx` 只证明 API 或 proxy 接受了请求；设备端送达仍以用户确认为准。

同一件事复用同一个 `thread_id`，通知才会在手机上归组。归组不能替代生产者侧的去重和冷却。有值得点开的页面就加 `--open-url`。会过时的提醒用 `--expiration-date` 限制 APNs 重试期限。

目标主机上不一定有这个 skill 目录。在本机发送时，直接按绝对路径调用 sender script。要写进 repo、装到远程主机或 systemd 时，把它复制或改编到那一侧的稳定路径。

## exe.dev HTTP Proxy

exe.dev VM 没有加载 `BRRR_SECRET` 时，sender script 才会调用 `https://brrr.int.exe.xyz/v1/send`。这要求当前 VM runtime 附有名为 `brrr` 的 HTTP Proxy integration。`notify` mobile notification integration 不是同一个东西，不能当作已配置的 brrr proxy。`https://brrr.int.exe.xyz/` 只是 proxy 根路径，发送通知用 `https://brrr.int.exe.xyz/v1/send`。

先查再配：VM 内读 `https://reflection.int.exe.xyz/integrations`，确认当前 runtime 实际看得到 `name=brrr`、`type=http-proxy` 再使用。缺失才创建。创建 integration 所需的 `BRRR_SECRET` 取自发起配置的本机授权来源，不复制进 VM；VM 里的 proxy 请求由 exe.dev 注入认证。执行 add 前确认变量非空，空 bearer 会创建一个静默坏掉的 integration。

```bash
ssh exe.dev integrations add http-proxy \
  --name=brrr \
  --target=https://api.brrr.now/ \
  --bearer="$BRRR_SECRET" \
  --attach=auto:all \
  --comment="Push notifications to the user's devices. Auth is injected by exe.dev. POST JSON to https://brrr.int.exe.xyz/v1/send with title, message, and optional subtitle, thread_id, open_url, image_url, expiration_date, filter_criteria, sound, interruption_level, and volume (critical only). Use only for user-requested pings or task-critical alerts."
```

如果用网页表单配置，提交前看 preview，必须是 `--attach=auto:all`。表单可能先自动生成 `tag:brrr`。

配好后从实际发送通知的 runtime 发一条测试通知；systemd `OnFailure=` 场景要测独立的 notification handler，不能用失败源服务或交互 shell 的成功代替。`401` 或 `403` 先查当前 runtime 的 integration attachment；如果 notification handler 已经通过授权的 env file 加载 `BRRR_SECRET`，保留显式 bearer 路径，不要为了迁就 machine proxy 删除它。成功的 `2xx` 说明 proxy 或 API 打通，设备端送达仍以用户确认为准。

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
