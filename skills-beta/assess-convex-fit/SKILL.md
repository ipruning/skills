---
name: assess-convex-fit
description: Assess whether Convex is the right application database or runtime boundary for a new or existing system. Use for Convex adoption decisions, architecture audits, deciding what belongs in Convex versus an existing backend, Postgres, object storage, an external worker, or a warehouse, and detecting when a Convex project has crossed into OLAP, raw-data, or long-running-runtime workloads. Not for ordinary Convex schema or function implementation after the boundary is decided, API syntax questions, or generic database benchmarking without a concrete product and data flow.
---

# Assess Convex Fit

判断 ownership 与 workload，不按前后端语言或框架投票。React 和 TypeScript 不足以证明 Convex 合适，Go、Rust 和 Python 也不构成否决条件。

## 先核实当前系统

现有项目先读当前代码，再接受架构文档的结论。至少核对这些 truth surface：

- 根 `AGENTS.md`、README 和架构文档中的产品范围、数据 owner 与运行时边界。
- `package.json`、lockfile、`convex/` schema/functions、客户端订阅与 HTTP 调用。
- 外部 Worker、定时任务、对象存储、批处理、导出和分析代码。
- 生产状态只在用户要求且已授权时读取。没有 live evidence 时，把判断限定为静态架构。

Convex 的能力、限制、客户端支持和导出方式会变化。先读项目实际安装的版本和 `convex/_generated/ai/guidelines.md`；需要当前平台事实时，只查对应的 Convex 官方文档，不从记忆写死数字：

- 函数：<https://docs.convex.dev/functions/overview>
- 限制：<https://docs.convex.dev/production/state/limits>
- 流式导入与导出：<https://docs.convex.dev/production/integrations/streaming-import-export>
- 自托管：<https://docs.convex.dev/self-hosting>

## 拆成四种 ownership

不要问「整个项目是否属于 Convex」。分别判断四层：

| 层 | 要回答的问题 | 常见 owner |
| --- | --- | --- |
| Application state | 哪些状态需要事务写入、权限控制、客户端恢复和实时订阅？ | Convex 或现有业务数据库 |
| Execution runtime | AI、爬取、shell、浏览器、GPU、长任务在哪里运行？ | Convex action 或外部 Worker |
| Raw data | Replay、日志、媒体、模型产物和大文件的权威字节在哪里？ | 对象存储 |
| Analytical data | 任意 SQL、全量扫描、BI、训练和跨数据集分析在哪里完成？ | Parquet、OLAP 数据库或数仓 |

一份系统可以只把第一层交给 Convex。混合架构不是折中失败，而是正常边界。

## 判定 Application Database

以下边界成立时，Convex 可以作为 Application Database：

- 数据由当前应用拥有，不是在复制另一个系统已经拥有的业务对象。
- 所有事务写入可以通过 Convex functions，其他服务不需要直接连接底层数据库。
- 在线查询固定、有界、可索引；复杂结果可以提前物化成产品投影。
- 团队接受 JavaScript 或 TypeScript 位于事务边界。

客户端需要实时订阅、跨设备恢复或一致的派生视图时，Convex 的相对价值更高。没有这些需求不会自动否决 Convex，但要重新比较它与现有数据库加普通 API 的复杂度。

出现以下任一事实时，直接收窄或拒绝：

- 另一个服务已经是数据 owner，Convex 会形成双写或语义副本。
- 多个服务必须以各自语言直接执行同一数据库事务。
- 核心查询是任意联表、全量扫描、动态聚合或数据团队直接 SQL。
- 标准 SQL、JDBC/ODBC、数据库扩展或数据库与应用平台解耦是硬约束。

固定分析页面不等于 OLAP。预计算排行榜、趋势卡片和有限维度 rollup 可以作为产品投影留在 Convex；不断增加筛选组合、冗余 rollup、人工回算和全历史扫描，说明分析层已经越界。

## 判定执行运行时

短时、有界、以 HTTP API 为主的外部调用可以放在 Convex action。决定前核对当前 action runtime、超时、内存、副作用重试和网络限制。

以下工作放到外部 Worker，Convex 只保存用户意图、产品状态、run 状态和恢复所需的有限投影：

- shell、PTY、浏览器、子进程、GPU 或特殊系统依赖。
- 执行时间无法可靠限制在当前 action 上限内。
- 需要独立扩缩容、进程隔离、主动取消、心跳或长连接。
- 原始 provider event、完整工具结果、stdout、trace 或大型 artifact。

Agent 系统要区分产品 thread 与 runtime session。Convex 可以保存 thread、message、run、lease 和客户端可见投影；不要把 private reasoning、原始 provider payload 或逐 token 的无界事件流当成产品状态。

## 保护数据权威

每类业务对象只保留一个权威写入方。可接受的流向是：

```text
client -> Convex application state
worker -> Convex mutations
worker -> object storage raw artifacts
Convex or object storage -> warehouse analytical copy
```

下游副本默认只读。需要把外部数据库镜像进 Convex 时，明确它是 read model，并验证同步时延、完整性和删除语义。不要用双向同步掩盖 owner 未决。

行为分析也不必全部从 Application Database 反推。漏斗、留存和过程事件有独立价值时，在行为发生时进入事件管道；Convex 当前状态只回答当前事实。

## 给出结论

先给以下四种结论之一：

- `use Convex`：Convex 可以拥有主要应用状态。
- `use Convex narrowly`：只拥有明确列出的产品状态或 serving projection。
- `do not use Convex`：关键约束与 Convex 的事务或运行时边界冲突。
- `insufficient evidence`：缺失的数据 owner、查询形态或运行时事实会改变结论。

随后给出：

1. 当前数据流与权威 owner，引用现有项目时带 `file:line`。
2. Convex 应拥有和不应拥有的表、状态与执行职责。
3. 外部 Worker、对象存储和数仓是否必要。
4. 让当前判断失效的可查验 stop condition，例如分析维度、数据量、任务时长、直接数据库访问或 SLA 发生变化。
5. 已验证和未验证的边界。不要把静态代码判断写成 live deployment 事实。

用户只问判断时不要顺手迁移、部署或修改架构。结论应说明真实边界，不为采用或拒绝 Convex 寻找修辞。
