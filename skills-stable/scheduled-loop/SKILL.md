---
name: scheduled-loop
description: "Set up recurring agent work inside a harness: scheduled checks, monitors, periodic follow-ups, reminders, and keep-checking loops where the agent itself performs each run. Use when the user asks to schedule, loop, keep watching, periodically verify, or be reminded later. Not for deploying durable monitoring infrastructure such as collectors, probes, and alert backends — that is observability-contracts."
metadata:
  version: "2"
---

# Scheduled Loop

用户说「盯着这个」「每天查一次」「到点提醒我」时，用这个 skill 决定循环的形态并创建它。执行每次检查的是 agent 本人。要交付无人值守的常驻监控链路，如 collector、探针和告警后端，用 `$observability-contracts`。循环结果要推送到聊天之外时，用 `$brrr-now` 发送。

## 核心决策

每种 harness 的调度原语都分两类：开全新会话的定时任务，和唤醒当前线程的定时消息。Codex 用 `automation_update` 创建 Scheduled Task 或 Scheduled Message，Claude Code 对应 CronCreate 和 ScheduleWakeup。先决定用哪类，再找当前 harness 的对应原语。

选全新会话，当每次运行靠调度 prompt 就能独立成功：任务能写成自包含指令，所需状态都在可重新获取的地方，比如文件、URL、ticket 和 API。

选唤醒当前线程，当下一次检查离不开本线程的上下文：进行中的协调状态、worker 线程、活跃的目标门槛。只有丢掉当前上下文会实质改变该做的事时才选这类。

两可时选全新会话，把所需上下文写进调度 prompt 或落成持久笔记。线程延续只在连续性本身是任务的一部分时使用。

## 从原话补全五个判断

从对话推断一切能推断的，只问会实质改变方案的缺口：

- 每次运行做什么。
- 多久一次。运行成本高或对外有噪音的工作不要发明节奏，问用户。轻量检查按紧急程度建议一个节奏并直接采用。
- 什么变化值得汇报。默认只报实质状态变化、阻塞、完成和验证失败。
- 什么时候停。默认在目标完成、不可能达成或被明确取消时停。
- 什么时候要问用户。默认在缺少秘密、审批、账号访问、产品决策，或动作不可逆且含糊时问。

## 调度 prompt 的形态

全新会话的 prompt 自包含：

```text
Every run, start fresh. Read [sources]. Check [condition]. Report only if [threshold].
Stop when [condition]. Ask the user only if [input condition].
```

唤醒当前线程的 prompt 面向延续：

```text
Continue this thread's active loop. Re-read [durable state]. Preserve the current gate/goal.
Check [condition]. Report only if [threshold]. Stop when [condition].
Ask the user only if [input condition].
```

## 创建后

确认一句话就够：调度项的名字、它是全新会话还是线程唤醒、节奏、汇报门槛和停止条件。
