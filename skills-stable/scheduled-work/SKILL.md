---
name: scheduled-work
description: "Set up scheduled agent work inside a harness where the agent itself runs each check and nothing is deployed: do something later, keep checking until something changes, confirm a job ran and ping on failure, or follow up periodically. Use when the user asks the agent to schedule, loop, keep watching, verify each run, or be reminded later. Not for deploying durable monitoring infrastructure like collectors, probes, and alert backends — that is end-to-end-monitoring."
metadata:
  version: "3"
---

# Scheduled Work

用户说「盯着这个」「每天查一次」「到点提醒我」时，用这个 skill 决定调度形态并创建它。执行每次运行的是 agent 本人。要交付无人值守的常驻监控链路，如 collector、探针和告警后端，用 `$end-to-end-monitoring`。运行结果要推送到聊天之外时，用 `$brrr-now` 发送。

## 核心决策

听起来是一个功能，实际是两种工作。每种 harness 的调度原语都分两类：一类每次运行都开全新线程，Codex 叫 Scheduled Task，Claude Code 用 CronCreate。另一类每次都回到同一个线程，Codex 叫 Scheduled Message，Claude Code 用 ScheduleWakeup。先决定要全新线程还是同一线程，再找当前 harness 的对应原语，Codex 里两类都通过 `automation_update` 创建。

选全新线程，当每次运行脱离创建它的对话也说得通：任务能写成自包含指令，所需状态都在可重新获取的地方，比如文件、URL、ticket 和 API。「每天早上九点汇总我该跟进的邮件、日历和团队消息」就是这类：明天的汇总不需要记得今天的汇总，只需要同一份指令、当天的信息和一个新的汇报位置。

选同一线程，当下一次检查依赖已经发生的工作。「每 30 分钟看一次这个 PR，有评论就处理并保住 CI，合并后停」就是这类：线程记得是哪个 PR、处理过哪些评论、CI 上次挂在哪。轮询更新、等一个状态变化、持续调查推进、有明确停止条件的收敛工作，都是这个形态。线程就是把多次运行连起来的那个东西。

两可时选全新线程，把所需上下文写进调度 prompt 或落成持久笔记。同一线程只在连续性本身是任务的一部分时使用。

## 从原话补全五个判断

从对话推断一切能推断的，只问会实质改变方案的缺口：

- 每次运行做什么。
- 多久一次。运行成本高或对外有噪音的工作不要发明节奏，问用户。轻量检查按紧急程度建议一个节奏并直接采用。
- 什么变化值得汇报。默认只报实质状态变化、阻塞、完成和验证失败。
- 什么时候停。默认在目标完成、不可能达成或被明确取消时停。
- 什么时候要问用户。默认在缺少秘密、审批、账号访问、产品决策，或动作不可逆且含糊时问。

## 调度 prompt 的形态

写一份耐久的 prompt：以后的某次运行读到它，仍然说得通。

全新线程的 prompt 自包含：

```text
Every run, start fresh. Read [sources]. Check [condition]. Report only if [threshold].
Stop when [condition]. Ask the user only if [input condition].
```

同一线程的 prompt 面向延续：

```text
Continue this thread's active loop. Re-read [durable state]. Preserve the current gate/goal.
Check [condition]. Report only if [threshold]. Stop when [condition].
Ask the user only if [input condition].
```

## 创建后

确认一句话就够：调度项的名字、它是全新线程还是同一线程、节奏、汇报门槛和停止条件。
