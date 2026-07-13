---
name: end-to-end-monitoring
description: "Design, deploy, repair, or verify standing monitoring and alerting infrastructure for open-ended production responsibility that must outlive the current task and run independently of any agent session: a host, service, cron job, crawler, dependency, data pipeline, or AI workflow. Not for finite or state-bounded checks performed by the agent itself — that is schedule-agent-work."
metadata:
  version: "7"
---

# End-to-End Monitoring

交付的是一份验证过的可观测性契约，不是一堆监控组件。契约的每一环都要设计并验证，验证不了的环节要点名列出：

```text
protected subject -> signal producer -> observability backend -> alert rule -> notification channel -> responder -> runbook
```

有限期、依赖当前任务上下文或到某个状态就停止的周期检查归 `$schedule-agent-work`。开放期限的生产责任，或必须独立于当前任务持续运行的监控留在这里。

## 先问什么

只问会改变设计的问题。本地检查、已认证工具、仓库文件和官方文档能回答的，不问用户：

- 保护对象是什么，什么算成功、什么算失败。
- 检测最晚可以多晚，仍来得及修复或重跑。
- 通知发给谁或什么服务，那个渠道允许打扰它吗。
- 用什么 observability backend。已有的直接复用，不必问。一个都没有时必须问，backend 决定 token、告警和查询语法，掉头代价大。

缺的细节不改变设计时，取保守默认并声明：

```text
hostmetrics cadence: 60s to start; 300s for fleets of >=5 hosts or any backend that bills per datapoint
hostmetrics cost: price the cadence against the backend's rate before deploying; formula and floor caveat in references/host-monitoring.md
hostmetrics freshness threshold: >=3x collection interval (60s -> 3m, 300s -> 15m); never below 3x or the alert flaps
custom probe freshness: start at 2x the probe cadence, cap at cadence + repair window; a cap below 2x means the cadence is too slow for the promise - shorten the cadence or declare the contract unsatisfiable; do not reuse the host default for hourly jobs
disk threshold: root filesystem >= 90%
notification mode: onset-only
secret storage: root-owned env file, chmod 600, on Linux/systemd hosts; otherwise the platform secret store
```

## 工作循环

1. 定义保护对象和承诺。
2. 检查机器、项目、调度器、服务和 observability backend 的事实。
3. 选满足承诺的最小 signal producer。
4. 先建立稳定身份，再创建凭据和告警。
5. 配置 producer 和 secrets 边界。
6. 创建 freshness 告警，再加语义或阈值告警。
7. 逐环验证：信号、后端查询、告警执行、通知送达、responder 接手。
8. 汇报已实现、已验证和未验证的部分。

工作时维护一份紧凑契约，只填实际需要的字段，缺的字段按上面的分界问或取默认：

```text
subject:
success signal:
failure signal:
producer:
cadence:
freshness / absence threshold:
severity mapping:
observability backend:
identity:
credential / revocation boundary:
alert rule:
channel:
responder:
runbook:
interruption behavior:
deadline / repair window:
secrets boundary:
```

## 设计规则

- 用现成的可观测性原语：logs、spans、metrics、severity、告警规则、freshness 检查、通知渠道和 runbook。人的参与由 severity、channel、responder、interruption behavior 和 runbook 表达，不另造事件协议。
- runbook 至少写明告警含义、第一步动作和如何吊销或重启，放在 responder 拿得到的位置，交付报告给出路径。
- 用满足契约的最小机制，已有监控能复用就复用。标准主机指标优先 OpenTelemetry Collector hostmetrics。业务、爬虫、外部依赖和 AI 工作流的检查，把探针挂在拥有承诺的调度器或运行时上，Linux 主机上通常一个 systemd timer 探针就够。
- project、environment、service 名、subject id、token 名，都在创建凭据之前定稳。每个 revocation boundary 一个 scoped write credential，不用 admin key 或个人 key。临时 dev-session 凭据只做引导，换成命名凭据之前不许声称监控已持久。
- 凡是保护承诺的监控必须有 freshness 告警。它兜住主机宕机、collector 停止、凭据吊销、DNS 和网络断裂这些不再发信号的失败。
- 一次性程序叫 probe、check 或 reporter，不叫 agent。agent 要能观察、决策并采取多步行动。
- 信号路径和通知路径都验证过之前不许说完成。验证不了的环节，在报告里点名。

## 工具边界

只读遥测查询、dashboard、告警定义和运行历史，优先用 observability backend 的 MCP 工具。MCP 不可用时，可用已认证的浏览器 UI 做同等范围的只读查询和告警检查。仍只运行有边界、有 `LIMIT` 的查询，不碰 cookies、local storage 和密码。创建或改动告警、渠道、凭据，只在用户要求部署、配置、轮换或修复时做。验证请求只授权只读检查和已获授权的测试信号，不授权新建或修改基础设施；验证必须改变状态时先取得明确授权。主机事实、运行时状态、systemd、日志和权限走 SSH。MCP 完不成的凭据操作，也用已认证的浏览器 UI 完成。provider 端点、token 行为、collector 配置或告警语法可能已变化时，查当前官方文档。secret 不进聊天摘要、shell history、进程 argv、unit 文件、git 和普通用户可写文件。

## 按需读的 reference

- 选了 Logfire，或涉及 token、告警、渠道、后端查询：[`references/logfire.md`](references/logfire.md)
- systemd service、timer、secret 文件、运行时验证：[`references/systemd.md`](references/systemd.md)
- 主机 CPU、内存、磁盘、网络等标准指标监控：[`references/host-monitoring.md`](references/host-monitoring.md)。cadence 与成本规则对任何后端通用，告警 SQL 和 token SOP 只适用 Logfire
- 业务探针、爬虫检查、cron 语义检查、外部依赖、AI 工作流检查：[`references/custom-probe.md`](references/custom-probe.md)

## 交付报告

最后分四栏：契约本身、实际部署了什么、验证了什么、未验证或仍需用户动作的。验证栏给证据：命令、后端查询结果、告警测试和通知回执。只有本地命令成功就说只有本地成功。遥测到了后端但告警和渠道没测过，就照实说。通知发了但真实 responder 没确认收到，也照实说。
