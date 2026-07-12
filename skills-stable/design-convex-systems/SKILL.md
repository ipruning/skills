---
name: design-convex-systems
description: Produce architecture decisions, boundary designs, or audits for systems using or considering Convex. Use for Convex adoption and fit decisions, deciding what application state Convex should own, designing boundaries around external workers, raw-byte storage, search, and analytics, or auditing an existing Convex system for contention, realtime fan-out, failure semantics, authorization, operator writes, disaster recovery, Cloud constraints, and self-hosting risks. Not for scaffolding a chosen React + TanStack + Vite + Convex app or delivering its first feature; use web-fullstack-start for that. Also not for implementing an already-decided schema or function, ordinary API syntax, narrow bug diagnosis, benchmark execution, or operating a deployment.
---

# Design Convex Systems

设计 Convex 的系统边界、事务语义和运行模型，不按前后端语言或框架投票。React 和 TypeScript 不足以证明 Convex 合适，Go、Rust 和 Python 也不构成否决条件。

`application state` 指需要分配权威写入方的在线产品状态。`Convex database` 指 Convex 的具体存储与事务系统。Convex 的核心价值是把 Convex database、事务函数、查询缓存失效、实时订阅和客户端状态同步收进同一边界。

## 选择工作模式

根据用户要求的交付物选择模式。Audit 可以附带 Fit 结论；只有用户明确要求目标架构或重构方案时才进入 Design。混合请求按 `Audit -> Fit -> Design` 分段，省略用户没有要求的后续模式。

| Mode | User intent | Primary output |
| --- | --- | --- |
| Fit | 是否采用 Convex，或现有系统是否继续让 Convex 拥有状态 | `use Convex`, `use Convex narrowly`, `do not use Convex`, or `insufficient evidence` |
| Design | 新系统如何使用 Convex，或现有边界如何重构 | ownership map, transaction and query model, failure model, external boundaries, operating model |
| Audit | 当前 Convex 架构有哪些边界错误和失效风险 | evidence-backed findings, consequences, unverified areas, recommended boundary |

用户只说「看看是否适合」时选择 Fit。用户问「应该怎么设计」时选择 Design。用户给出现有代码并问「用法是否正确、有什么问题」时选择 Audit。不要因为正文知识面广，就把普通实现、性能、安全或运维问题吸进来；它们只有在会改变 Convex 系统设计时才属于本 Skill。

## 建立证据边界

已有项目先读当前代码，再接受架构文档的结论。核对根 `AGENTS.md`、README、架构文档、项目清单、lockfile、`convex/` schema 和 functions、客户端订阅、HTTP caller、外部 Worker、定时任务、文件流、导出和分析代码。

新系统从 PRD、brief 或用户描述中提取权威写入方、在线查询、实时需求、任务依赖与时长、文件流、搜索流、分析流和平台硬约束。缺失事实会改变结论且无法安全推断时，标为 `insufficient evidence`，不编造一个完整架构。

区分以下证据：

- 项目静态代码说明设计，不证明 live deployment 正在运行同一版本或配置。
- 官方文档说明公开能力，不替代 Enterprise 合同、DPA、SLA 或私有 support 承诺。
- 当前源码说明实现行为，不证明 Convex Cloud 已部署同一 commit。
- 公开 issue 只说明风险信号。未复现或未由 maintainer 确认时，不把它写成系统事实或故障率。

普通任务按相关标题读取 [risk-surfaces.md](references/risk-surfaces.md)，不默认加载全部章节。用户要求源码证据、精确限制、已知缺陷、self-hosted 生产判断或文档冲突分析时，再按目录读取 [system-limitations-audit-2026-07-13.md](references/system-limitations-audit-2026-07-13.md) 的相关章节。后者是时间点证据，不是当前平台事实；引用任何 client、function、scheduler、workflow、storage、同步或部署行为前，核对目标版本。价格、地域、限制、beta 状态、issue 和 Cloud 能力还要刷新当前官方资料。本机实测与 reference 冲突时，以目标版本的实测行为为准，并报告差异。

## 拆成五个边界

不要问「整个项目是否属于 Convex」。分别设计五个边界，不要把执行位置和存储位置称为数据 owner。

| Boundary | Question | Typical location |
| --- | --- | --- |
| Application state | Which state needs transactional writes, authorization, subscription recovery, and reactive views? | Convex database or an operational database |
| Execution runtime | Where do AI calls, crawling, shell, browsers, GPUs, and long-lived processes run? | Convex action, durable workflow, or external worker |
| Raw-byte storage | Where do capture/replay data, logs, media, model outputs, and large artifacts live? | Convex File Storage or external object storage |
| Search / derived serving | Where do full-text, vector retrieval, faceting, ranking, and materialized read models run? | Convex search, a serving projection, or an external search system |
| Analytical destination | Where do ad hoc SQL, full scans, BI, training, and cross-dataset analysis run? | OLAP, datasets, or a warehouse |

一份系统可以只把 application state 交给 Convex。混合架构是正常边界，不是折中失败。

## 先过平台硬门

核对托管方式、部署地域、数据驻留与合规、SLA、容量与成本、备份恢复、网络约束和 support 依赖。任一硬约束已经冲突时，Fit 选择 `do not use Convex`；Design 把 Convex 排除在冲突边界之外；Audit 把它列为 blocking finding。

Cloud 与 self-hosted 分开设计。不能把 Cloud 的持久性、扩缩容、可用性和运维保证外推给 self-hosted，也不能把单节点 self-hosted 的缺陷外推成 Cloud 的故障率。Self-hosted 单独验证 storage backend、HA、backup、upgrade、capacity 和 monitoring。

## 设计 application-state ownership

Convex 拥有 application state 时，应同时成立：

- 当前应用是这批状态的唯一权威写入方，不是在复制另一个系统已经拥有的业务对象。
- 所有事务写入经过 Convex mutations，业务不变量由 Convex functions 执行，其他服务不直接连接底层数据库。
- 在线查询固定、有界、可索引；复杂结果可以提前物化成 serving projection。
- 团队接受 JavaScript 或 TypeScript 位于事务语义边界。

客户端需要实时订阅、断线重连后恢复订阅和一致查询结果，或一致派生视图时，Convex 的相对价值更高。没有这些需求不会自动否决 Convex，但要重新比较它与现有数据库加普通 API 的复杂度。

外部 Go、Rust 或 Python 服务可以通过 Functions API 充当消费者、生产者或计算服务。经过 API 不等于权威已经统一；Convex mutation 仍须执行权限、业务不变量和幂等规则。只有当核心事务必须在外部运行时直接操作同一数据库，并且不能拆成「外部计算 + Convex mutation」时，语言约束才会否决 Convex。

另一个服务已经是权威写入方、多个服务必须直接执行同一数据库事务、核心负载是任意联表与全量扫描，或标准 SQL、JDBC/ODBC、数据库扩展和平台解耦是硬约束时，收窄或拒绝 Convex ownership。

## 设计事务、查询与 realtime

对每条高频 mutation 列出 read set、write set、热点 key 和峰值并发。Serializable transaction 保证正确性，不证明热点写入具有足够吞吐。使用已有目标版本与 deployment class 压测结果；缺失时，把 conflict rate 记为未验证的 stop condition，不在本 Skill 内设计或执行 benchmark。

核对 compound index shape、过滤前扫描量、分页行为和 transaction limit，不以「有索引」代替查询成本证据。对关键订阅分别列出更新频率、read-set 范围、唯一订阅参数与订阅数、cache miss 后读取、重算次数和返回字节，不把这些维度压成未经验证的乘法公式。

需要离线写入或外部 producer 时，明确持久队列、ordering、idempotency 和 retry 的 owner。自动重连不等于 durable offline queue，Functions API 也不等于 delivery guarantee。

## 设计执行运行时与失败语义

- 短时、有界、单步的外部调用可以使用 action。存在外部副作用时，确定 durable intent、idempotency、attempt 和 reconciliation 的 owner。
- 可拆成多步并需要延迟或恢复的流程，评估 Scheduled Functions、Workpool 或 Workflow。分别核对 delivery、retry、auth propagation、overlap、代码版本寿命、cleanup 和 cancel，不使用统一的「可靠后台任务」标签。
- 需要单个长进程、shell、PTY、浏览器、子进程、GPU、特殊系统依赖、独立扩缩容、进程隔离、强制取消、心跳或长连接时，使用外部 Worker。

Convex 保存用户意图、application state、run 的客户端可见状态和恢复所需的 serving projection。完整 provider event、工具结果、stdout、trace 和大型 artifact 进入 raw-byte storage。

Agent 系统要区分产品 thread 与 runtime session。Convex 可以保存 thread、message、run、lease 和 run 的客户端可见状态；不要把 private reasoning、原始 provider payload 或逐 token 的无界事件流当成 application state。

## 设计文件、搜索与分析边界

Convex File Storage 与外部 object storage 都是可选项。按授权、撤销、serving path、生命周期、成本和外部处理需求选择。业务元数据、权限和产品可见状态可以留在 Convex，原始字节不必使用同一存储。

Search 是独立 serving 边界。按语言、排序、filter、reactivity、一致性和运维 owner 在 Convex search、serving projection 与外部 search system 之间选择，不把它并入 OLAP 判断。Search index 与 serving projection 默认是可重建派生状态，不反向成为隐式权威写入方。

固定分析页面不等于 OLAP。预计算排行榜、趋势卡片和有限维度 rollup 可以留在 Convex；持续经营分析、复杂 SQL 和跨业务联表进入单向分析副本。漏斗、留存和过程行为在发生时进入事件管道，不靠当前状态反推历史过程。

如果分析本身是主要工作负载，而实时 application state 只是次要需求，先选择权威业务数据库、事件存储或分析系统；不要先选 Convex，再靠导出补回主要能力。

## 设计 authorization、运营写入与灾备

认证成功不等于数据边界安全。每个 public function 都需要参数验证和明确的 access-control decision，再按暴露面判断 authentication、tenant/resource authorization 和 abuse control 是否适用。

列出所有运营写路径，检查它们是否绕过 mutation、trigger、projection、authorization 或 audit invariant。灾备设计给出 code、config、environment、files、pending jobs 和 RPO/RTO 的恢复证据，不以「有 backup」结束。普通 logs 只用于 observability；合规审计另行验证 durable delivery、去重、actor propagation 和 rollback 语义。

## 保护数据权威

每类业务对象只保留一个权威写入方。默认流向是：

```text
client -> Convex mutation -> application state
worker -> Convex mutation -> application state or run client state
worker -> Convex File Storage or external object storage -> raw bytes
application state -> Convex search, serving projection, or external search system
Convex or raw-byte store -> analytical destination
external system -> Convex read model
```

下游 search index、serving projection 和分析副本默认可重建，不反向修改权威对象。外部系统镜像进 Convex 的数据是 read model，必须验证同步时延、完整性和删除语义。不要用双向同步掩盖权威写入方未决。

## 输出 Fit

先给以下四种互斥结论之一：

- `use Convex`：Convex 可以拥有主要 application state，且平台硬门已经通过。
- `use Convex narrowly`：Convex 只拥有明确列出的 application state 或 serving projection；执行、原始字节、搜索或分析边界位于外部。
- `do not use Convex`：不存在值得由 Convex 拥有的 application-state 切片，或平台硬约束直接排除 Convex。
- `insufficient evidence`：缺失的平台硬约束、权威写入方、查询形态、contention 或失败语义会改变结论。

随后给出 ownership map、外部边界、主要风险、平台缺口、stop conditions，以及已验证与未验证的事实。

## 输出 Design

给出一份可以执行的系统设计：

1. 当前或目标数据流与每类对象的权威写入方。
2. Convex tables、mutations、queries、serving projections 和 subscription boundaries。
3. Transaction contention 与 realtime fan-out 模型。
4. Action、scheduler、workflow 和 external worker 的 failure semantics。
5. Raw-byte storage、search 和 analytical destination，以及单向同步和重建规则。
6. Authorization、operator write path、audit 和 disaster recovery。
7. 平台硬门、未验证项，以及让设计失效的 stop conditions。

引用现有项目时带 `file:line`。用户没有要求实现时，不顺手修改代码、迁移数据或部署。

## 输出 Audit

先画出当前 ownership 与数据流，再按证据报告会改变系统行为的 findings。每条说明当前事实、后果、建议边界和证据位置。把未复现 issue、缺失 live evidence 和合同能力放入未验证区，不与确认缺陷混写。最后给出保留、收窄或外移 Convex 职责后的目标边界。

用户只要求审计时，不顺手修复、迁移或部署。结论说明真实边界，不为采用或拒绝 Convex 寻找修辞。
