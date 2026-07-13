# Convex 系统限制、失败语义与已知缺陷审计

审计日期：2026-07-13。

这是一份带时间点的 evidence dossier，不是永久有效的平台说明。使用其中的价格、地域、限制、beta 状态、issue 或源码行为前，重新核对目标项目版本和当前官方资料。

## 目录

- [结论](#结论)
- [审计边界与证据等级](#审计边界与证据等级)
- [一、事务正确性与 contention](#一事务正确性与-contention)
- [二、查询、实时订阅与客户端语义](#二查询实时订阅与客户端语义)
- [三、Action、Scheduler、Workflow 与失败语义](#三actionschedulerworkflow-与失败语义)
- [四、搜索能力不是同一种一致性模型](#四搜索能力不是同一种一致性模型)
- [五、文件、备份与分析同步](#五文件备份与分析同步)
- [六、安全、运营写入与审计](#六安全运营写入与审计)
- [七、Cloud 平台硬门](#七cloud-平台硬门)
- [八、Self-hosted Convex 的独立风险面](#八self-hosted-convex-的独立风险面)
- [Appendix A：2026-07-13 公开硬限制快照](#appendix-a2026-07-13-公开硬限制快照)
- [Appendix B：本机官方仓库审计快照](#appendix-b本机官方仓库审计快照)
- [十一、仍未验证](#十一仍未验证)

## 结论

本次审计不对 Convex Cloud 的总体可靠性或特定 workload 的适配度背书。公开文档与源码支持以下五个系统设计约束：

1. Serializable transaction 保证正确性，不保证热点写入总能成功。OCC 重试有限，contention topology 是容量模型。
2. Realtime subscription 的失效单元是 query read set。文档更新频率、read-set 宽度、订阅数和返回字节共同决定 fan-out 成本。
3. Action、scheduled function、Workflow 和客户端断线具有不同的失败语义。它们不能统称为「可靠后台任务」。
4. Authorization、运营写路径、灾备重建和审计仍主要由应用与组织负责。认证成功不等于数据边界安全。
5. Self-hosted Convex 是另一种产品。不能把 Convex Cloud 的可用性、持久性、扩缩容和运维保证外推给它。

是否适合目标 workload，取决于目标版本、deployment class、实际 conflict rate、query shape、subscription load、失败语义和平台硬门的证据。不能把任意查询、离线写入、强制取消的长进程、通用 CDC、完整灾备或标准数据库运维能力当成平台默认值。

## 审计边界与证据等级

本次只采用一手公开资料：

- Convex 官方文档及其 `convex-backend` 文档源码。
- `get-convex` 官方仓库源码、README、CHANGELOG 和 issue。
- 本机 `/Users/alex/Developer/tries/convex-*` 的固定 commit。

没有使用博客测评、论坛转述或模型记忆。没有对 Convex Cloud 做 live load test，也没有 Enterprise 合同、DPA 或私有 support 承诺。

证据分四级：

- `documented`：官方文档明确承诺或限制。
- `source-confirmed`：当前官方源码直接呈现该行为。
- `component-confirmed`：官方组件 README 或源码明确呈现该行为。
- `maintainer-confirmed`：官方 maintainer 在公开 issue 中确认该行为，但它不等于文档承诺。
- `reported`：当前公开 issue 的可复现报告，未获 maintainer 确认或未由本次运行复现。

公开仓库源码与 Cloud 线上部署不是同一个可观测对象。官方文档称开源 backend 与 Cloud 使用同一代码，但仓库也只承诺内部开发在数日内同步。因此 source-confirmed 结论可以说明实现设计，不能证明某一时刻的 Cloud release 已部署同一 commit。[Self-hosting](https://docs.convex.dev/self-hosting)、[仓库同步说明](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/self-hosted/README.md#L140-L146)

## 一、事务正确性与 contention

### OCC 自动重试不是无限吞吐保证

分类：`documented` + `source-confirmed`。

Convex mutation 是 serializable transaction。确定性使平台能够自动重试 OCC conflict，但连续冲突最终会返回 `OptimisticConcurrencyControlFailure`。当前开源 backend 的默认最大 OCC retry 为 4 次，初始 backoff 为 100 ms，最大 backoff 为 2 秒；Cloud 可以通过环境配置覆盖这个默认值，因此不能把 4 当成 Cloud 合同值，但可以确认重试不是无限的。[OCC 文档](https://docs.convex.dev/database/advanced/occ)、[错误语义](https://docs.convex.dev/error#write-conflict-optimistic-concurrency-control)、[retry knob](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/crates/common/src/knobs.rs#L231-L241)、[达到上限后返回错误](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/crates/application/src/application_function_runner/mod.rs#L997-L1060)

这使单例计数器、全局库存、单租户配额行、全局聚合根节点和宽 read set 成为架构问题。团队级 mutation concurrency 只表示可同时运行多少函数，不表示同一个热点 key 能获得相同吞吐。

选型检查：对每条高频写路径列出 read set、write set、热点 key 和预期峰值并发。不可分片的业务 invariant 必须压测实际 conflict rate。

### 分片把写 contention 换成读放大或估算误差

分类：`component-confirmed`。

官方 Sharded Counter 将写入分散到随机 shard，但精确读取必须读取全部 shard。精确读取用于 mutation 时又会对所有 shard 建立 read dependency；估算读取只采样部分 shard，因此在大步长更新、shard 数变化或分布不均时会产生误差。`rebalance` 本身读写全部 shard，也会增加 OCC。[Sharded Counter](https://github.com/get-convex/sharded-counter/blob/534b098a5f1e48304390a16e98b937ba6dad2244/README.md#L122-L228)

官方 Aggregate 的树结构也有 contention topology。无 bounds 的 `count` 依赖整个聚合结构；任何更新会使订阅重跑。以 `_creationTime` 为递增 key 时，所有插入集中在树末端，README 明确说这些插入无法并行。[Aggregate reactivity and contention](https://github.com/get-convex/aggregate/blob/ef00fb8afe9e419f6013ae7d8e8c0478c2960752/README.md#L550-L664)

选型检查：固定排行榜和 rollup 可以留在 Convex，但必须同时设计 namespace、bounds、shard 数和读放大；「使用 Aggregate 组件」不是 contention 已解决的证据。

## 二、查询、实时订阅与客户端语义

### Realtime 的成本由 read set 决定，不由 UI 实际使用的字段决定

分类：`documented` + `source-confirmed`。

Convex 根据 query 读取的文档和 index range 建立依赖。相关写入会使 query cache 失效并重新执行。当前没有字段投影 API；公开 issue #97 要求只追踪指定字段，说明读取整个 document 时，未被 UI 使用的字段变化也会触发重跑。[Query caching and reactivity](https://docs.convex.dev/functions/query-functions#caching--reactivity--consistency)、[read-set 源码](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/crates/database/src/reads.rs#L322-L346)、[Issue #97](https://github.com/get-convex/convex-backend/issues/97)

Subscription update 计入 function call，缓存未命中后的数据库传输计入 I/O。S16 与 S256 的 query cache 都是 1 GB shared。Paginated query 同样完全 reactive，插入和删除会使既有页面增长或缩小。[Limits](https://docs.convex.dev/production/state/limits)、[Reactive pagination](https://docs.convex.dev/database/pagination#reactivity)

选型检查：分别测量文档变化频率、read-set 覆盖范围、唯一订阅参数与订阅数、重算次数、cache miss 后读取和返回字节。不要把这些维度合成未经验证的乘法模型。高频状态和大列表 projection 不应混在同一文档。

### 「有索引」不足以证明查询有界

分类：`documented`。

Convex index range 必须遵守 compound index 的 equality prefix 顺序。`.filter()` 在扫描后执行，不减少扫描量。`withIndex()` 没有 range 再 `.collect()` 仍可能扫描整个 index。单次 query/mutation 的公开限制包括 16 MiB read、32,000 scanned documents、4,096 index ranges；用户 JavaScript 执行时间为 1 秒。[Indexes](https://docs.convex.dev/database/reading-data/indexes)、[Filters](https://docs.convex.dev/database/reading-data/filters)、[Transaction limits](https://docs.convex.dev/production/state/limits#transactions)

同步创建 index 会等待 backfill 完成后才注册新函数。大表需要 staged index；staged index 完成 backfill 并启用前不能查询。[Staged indexes](https://docs.convex.dev/database/reading-data/indexes#staged-indexes)

选型检查：产品查询必须能够枚举成固定 index shapes。不断增加任意筛选组合、跨表排序、窗口计算或 full-history scan 时，应使用 search、OLAP 或下游 read model。

### JavaScript 客户端不是 durable offline-first 数据层

分类：`documented` + `source-confirmed`。

WebSocket 重连会重建 query 和重发 mutation，但待发请求只保存在进程内存中。浏览器实现只用 `beforeunload` 提示「Your changes may not be saved」。进程被杀、移动端回收、崩溃或没有 `beforeunload` 的运行时不会获得持久 outbox。[内存 mutation queue](https://docs.convex.dev/understanding/overview#client-libraries)、[beforeunload 源码](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/npm-packages/convex/src/browser/sync/client.ts#L387-L415)

选型检查：需要进程重启后继续提交、复杂离线冲突合并或本地 transaction 时，必须另建本地持久队列与同步模型。

### Transport 不同，ordering、subscription 和 retry 保证也不同

分类：`documented`。

React 与 Rust client 的 mutation 使用每客户端有序队列；HTTP/OpenAPI 查询不 reactive。不能把 WebSocket client 的 ordered mutation、session retry 和 subscription 保证外推给 Go 或普通 HTTP caller。[Mutation ordering](https://docs.convex.dev/functions/mutation-functions#calling-mutations-from-clients)、[OpenAPI limitations](https://docs.convex.dev/client/open-api)

选型检查：外部 producer 必须自己提供 idempotency key、ordering key 和 retry policy。Functions API 只是访问路径，不是 delivery guarantee。

## 三、Action、Scheduler、Workflow 与失败语义

### Action 返回失败时，外部副作用仍可能已经发生

分类：`documented` + `source-confirmed`。

Action 不具备 transaction，也不自动 retry。直接从客户端调用 action 时，它与同客户端的 mutation/action 并行执行；官方把多数直接调用称为 anti-pattern，建议先用 mutation 写入 intent 再调度 action。Action 内多次 `runQuery` 或 `runMutation` 是独立 transaction，彼此可能看到不同状态。[Actions](https://docs.convex.dev/functions/actions)

当前 JavaScript client 断线时会重发 mutation，却不会重发 in-flight action，因为无法判断 action 是否已经产生副作用。客户端把它报告为 `Connection lost while action was in flight`。这个错误只说明结果未知，不说明副作用没有发生。[request manager](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/npm-packages/convex/src/browser/sync/request_manager.ts#L193-L225)

选型检查：每个外部副作用都需要稳定 idempotency key、durable intent、attempt 状态和 reconciliation。不能根据 action Promise rejection 直接重试扣款、发信或 provider 调用。

### Built-in scheduler 有两套不同保证

分类：`documented`。

从 mutation 调度与 mutation 原子提交。从 action 调度不与 action 结果绑定：action 后续失败时，已经调度的工作仍会执行。Scheduled mutation 是 exactly-once；scheduled action 是 at-most-once，transient error 后永久失败。取消已经开始的 scheduled function 不会停止当前执行，只阻止它后续调度子任务。Auth identity 不传播。[Scheduled Functions](https://docs.convex.dev/scheduling/scheduled-functions)

同一 cron 同时最多一个 run。前一次执行太久时，后续 tick 会被跳过而不是排队补跑。[Cron error handling](https://docs.convex.dev/scheduling/cron-jobs#error-handling)

选型检查：不能丢周期的工作使用 durable cursor 和显式 period key；关键后台任务从 mutation 建立 intent，并在 scheduled function 中重新验证 actor、tenant 和当前权限。

### Workflow 的 durability 以 deterministic replay 和代码冻结为代价

分类：`component-confirmed`。

Workflow 会 replay 已记录的 step history。Active workflow 生命周期内增加、删除或重排步骤会触发 determinism violation。单个 workflow 的 step 输入输出总量限制为 1 MB，journal 当前限制为 8 MiB，并继续受 mutation transaction 限制。Completed workflow 不会自动 cleanup。取消 workflow 或 Workpool work 不会中止正在执行的 action。[Workflow limitations](https://github.com/get-convex/workflow/blob/38140a9399531adb5fe9e316a7d03cff21f61083/README.md#L793-L817)、[Workflow cleanup and cancel](https://github.com/get-convex/workflow/blob/38140a9399531adb5fe9e316a7d03cff21f61083/README.md#L475-L539)、[Issue #35](https://github.com/get-convex/workflow/issues/35)、[Workpool cancellation](https://github.com/get-convex/workpool/blob/121c076a5666f74e6ebca03cbf72abd4ce4bb2b3/README.md#L394-L409)

Workpool retry 只对幂等 action 安全。`onComplete` 与最初 enqueue 位于不同 transaction；组件有额外调度开销，官方建议不要创建过多 Workpool。[Workpool idempotency and transaction boundary](https://github.com/get-convex/workpool/blob/121c076a5666f74e6ebca03cbf72abd4ce4bb2b3/README.md#L132-L169)、[Workpool overhead](https://github.com/get-convex/workpool/blob/121c076a5666f74e6ebca03cbf72abd4ce4bb2b3/README.md#L351-L360)

选型检查：长生命周期 workflow 必须显式版本化定义并保留旧代码，直到旧实例结束。History 只存 ID，不存 provider payload。需要强制终止进程、PTY、浏览器、GPU 或撤销已经发出的副作用时，仍需外部 Worker。

### Scheduler 文档、公开限制与源码存在漂移

分类：`source-confirmed` documentation defect。

当前 `Scheduled Functions` 页面仍写单个 function 最多调度 1,000 项、参数合计 8 MB；统一 Limits 页面写单项 4 MiB、mutation 内合计 16 MiB。当前源码实际硬执行 1,000 项和 16 MiB 合计值，但单项 4 MiB 只生成 warning，源码明确标记「not currently enforced」和未来会成为 hard error。[Scheduled Functions source doc](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/npm-packages/docs/docs/scheduling/scheduled-functions.mdx#L43-L44)、[Limits](https://docs.convex.dev/production/state/limits#execution-time-and-scheduling)、[limit knobs](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/crates/common/src/knobs.rs#L384-L407)、[实际 enforcement](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/crates/model/src/scheduled_jobs/mod.rs#L156-L188)

选型检查：不要依赖当前允许超过单项 4 MiB 的行为；跨 scheduled boundary 只传 ID。

## 四、搜索能力不是同一种一致性模型

### Vector search 只在 action 中运行

分类：`documented`。

Vector index up-to-date，但 vector search 只能在 action 中运行，不能直接 reactive subscription。搜索得到 ID 后再调用 query 加载文档，不与 vector search 位于同一 transaction；文档可能已经删除或变化。[Vector Search](https://docs.convex.dev/search/vector-search)

选型检查：需要 reactive semantic search 时，将结果 materialize 为 serving projection，或接受显式刷新与结果漂移。

### Full-text search 的语言、排序和查询表达能力有限

分类：`documented`。

Full-text search reactive 且 transactional，但最适合英文和 Latin script，使用按空格与标点切分的 tokenizer。只支持 relevance order，relevance 规则可能变化；每个 query 最多 16 terms、8 filters，并最多扫描 1,024 个 search results。[Full Text Search](https://docs.convex.dev/search/text-search#limits)

选型检查：中文分词、稳定排序、动态 faceting、复杂 filters 或搜索分析是核心能力时，优先专门 search system。

## 五、文件、备份与分析同步

### File Storage URL 是不可过期的 bearer capability

分类：`documented`。

`storage.getUrl()` 返回的 URL 无需再次授权，不能单独撤销或自动过期，只能删除文件。若每次下载都要重新授权，需要经 HTTP action 返回 bytes，但 HTTP action response 当前限制 20 MiB。[File Storage security model](https://docs.convex.dev/file-storage/overview#security-model)

上传流程把上传文件和 mutation 写入业务引用拆成多个步骤。由此可以推得上传成功、业务 mutation 失败时可能留下 orphan file；这是流程推论，不是官方明确保证。[Upload flow](https://docs.convex.dev/file-storage/upload-files)

选型检查：需要 expiring signed URL、大文件私有下载、CDN policy 或对象生命周期时使用外部 object storage；若保留 Convex File Storage，建立 pending upload 与 orphan GC。

### Backup 不是完整 deployment restore

分类：`documented`。

Backup 包含 table documents 和可选 files，不含 code/config、environment variables 或 pending scheduled functions。手动和日备保留 7 天，周备 14 天。Restore 会破坏性替换 table data，但不会删除目标 deployment 已存在的 files，因此不是 bit-for-bit rollback。生成与恢复可能耗时数小时。D1024 physical restore 需要联系 support。[Backup & Restore](https://docs.convex.dev/database/backup-restore)

选型检查：灾备包必须另外版本化代码、schema、crons、auth config、env 来源和 pending-job 重建方案，并实测 RPO/RTO。

### Streaming export 仍不是普通数据库 CDC

分类：`documented beta` + `source-confirmed`。

Fivetran export 和 Airbyte import 都是 beta。Export 需要 Pro。Import、backup restore、table replacement 和部分 schema change 不会由 Fivetran 正常处理，官方要求 reset sync。[Streaming Import/Export](https://docs.convex.dev/production/integrations/streaming-import-export)、[Import warnings](https://docs.convex.dev/database/import-export/import#warnings)

当前 legacy `document_deltas` 的 delete tombstone 只含 `_id`，没有删除前字段。下游若按旧字段维护聚合，无法知道应 decrement 哪个 bucket；公开 issue #316 正在请求 before/after image。[tombstone source](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/crates/local_backend/src/streaming_export.rs#L180-L199)、[Issue #316](https://github.com/get-convex/convex-backend/issues/316)

源码中的新 `/data/sync` API 明确标记 Early Access，可无通知发生不兼容变化；cursor 必须至少每 3 天续用，否则过 retention window 后必须全量重建。[Data Sync source](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/crates/local_backend/src/streaming_export.rs#L235-L268)

选型检查：持续同步必须验证 delete、truncate、restore、schema evolution、cursor recovery、lag 和重建时间。不能把「支持 Fivetran」翻译成可靠 CDC。

## 六、安全、运营写入与审计

### Functions 默认 public，authorization 由应用代码执行

分类：`documented`。

Convex functions 默认 public，可以由恶意 client 直接调用。Internal function 只缩小公开面，仍应验证参数和 invariant。官方状态页仍把完整 authorization framework 列为 future feature；当前每个 public function 都需要参数验证和明确的 access-control decision，再按暴露面判断 authentication、tenant/resource authorization 和 abuse control 是否适用。[Internal Functions](https://docs.convex.dev/functions/internal-functions)、[Authorization status](https://docs.convex.dev/production/state#authorization)

选型检查：静态审计所有 public functions 是否具备 validator 和明确的 access-control decision，并核对需要登录、tenant/resource authorization 或 abuse control 的暴露面。Auth provider 接入不等于 row-level authorization。

### Dashboard 直接编辑会绕过 helper trigger 与应用 invariant

分类：`maintainer-confirmed`。

Dashboard 直接编辑数据不会运行用户 mutation。官方成员在 issue #114 确认这一点；使用 Aggregate、custom trigger、denormalized projection 或 audit side effect 时，Dashboard CRUD 会导致派生状态失步。[Issue #114](https://github.com/get-convex/convex-backend/issues/114)

选型检查：生产运营写入通过专用 admin mutation。使用 component trigger 或 aggregate 时，必须有 consistency checker 和 repair procedure。

### 普通 log stream 不是审计账本

分类：`documented`。

Log stream 是 best-effort delivery。高吞吐会丢事件，network retry 会重复事件。单函数普通 log 还受 256 行与单行 4 KiB 限制。[Log stream guarantees](https://docs.convex.dev/production/integrations/log-streams#guarantees)、[Logging limits](https://docs.convex.dev/production/state/limits#functions)

Transactional audit logging 只对 Enterprise D1024 开放，delivery 为 at-least-once；失败和 OCC rollback 也可能留下 audit record，actor 需要应用手工传递。[Audit Logging](https://docs.convex.dev/production/integrations/audit-logging)

选型检查：普通 logs 只用于 observability。合规审计需要确认 D1024、S3 destination、去重键、actor propagation 和 rollback 语义。

## 七、Cloud 平台硬门

分类：`documented`。

当前公开 Cloud region 只有 US East 与 EU West，已有 deployment 不能原地迁移 region，只能新建并 export/import。状态页写 99.99% availability target，允许无通知 maintenance，并明确该页不构成合同；公开 class SLA 只适用于 Business/Enterprise，S16/S256 为 99.9%，D1024 为 99.95%。[Regions](https://docs.convex.dev/production/regions)、[Status and Guarantees](https://docs.convex.dev/production/state)、[Deployment classes](https://docs.convex.dev/production/state/limits#deployment-classes)

S16/S256 最大 dataset 为 1 TB、query cache 为 1 GB shared；D1024 为 4 TB 与 2 GB dedicated。当前并发 query 为 16/256/1024，mutation 为 16/256/512，scheduled jobs 为 8/256/512。EU 公开价格是 US 的 1.3 倍。Subscription update 和 file access 也计 function call。[Limits](https://docs.convex.dev/production/state/limits)

Node runtime version 变更后的数分钟内，新代码可能仍在旧 Node version 上执行。Self-hosted 不支持项目 Node version 配置，只使用 backend 的 `.nvmrc`。[Runtimes](https://docs.convex.dev/functions/runtimes#nodejs-runtime)

Outbound IP 是同 region 全部 Convex deployment 共享的，不能把 source IP 当作 authentication 或 authorization。[Networking](https://docs.convex.dev/production/networking)

选型检查：数据驻留不在两个公开 region、要求 region failover/active-active、要求高于合同 SLA，或峰值会撞 class concurrency 时，必须先得到 Enterprise 书面能力与价格。

## 八、Self-hosted Convex 的独立风险面

### 官方只承诺 Cloud free-tier feature surface

分类：`documented operational risk`。

Self-host README 只写支持 Cloud free-tier features，并说明 Cloud 为 scale 优化。默认形态是一套 backend、dashboard 和本地 SQLite；生产 uptime 文档建议外接 managed Postgres/MySQL，但没有公开的 backend 多副本、自动 failover 或无状态横向扩展 runbook。[Self-host README](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/self-hosted/README.md)、[Postgres/MySQL guidance](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/self-hosted/advanced/postgres_or_mysql.md)

Backend 和 dashboard 版本必须一致，不保证不同版本兼容。In-place upgrade 可能失败；fallback 是停流量、export、重建、import 和恢复 env，大数据量会产生 downtime。[Self-host changelog](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/self-hosted/CHANGELOG.md#L1-L16)、[Upgrade procedure](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/self-hosted/advanced/upgrading.md)

### 当前源码可确认的 self-hosted 缺陷

分类：`source-confirmed` + public issue。

1. SQLite `index_scan` 忽略 `_size_hint`，SQL 没有 `LIMIT`，并在返回前把整个范围 materialize 为 `Vec`。这支持 issue #495 对大范围 indexed `.take(1)` 仍可能 OOM 或触发 system-operation limit 的根因分析。[SQLite source](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/crates/sqlite/src/lib.rs#L121-L216)、[ignored size hint](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/crates/sqlite/src/lib.rs#L559-L575)、[Issue #495](https://github.com/get-convex/convex-backend/issues/495)
2. Node executor 在每次 action 调用时替换 process-global `process.env`，await 完成后再恢复。并发 invocation 会共享这个全局对象，支持 issue #492 关于环境变量间歇性丢失的竞态分析。[Node executor source](https://github.com/get-convex/convex-backend/blob/559e283c62b2cfb21ee9151a664566304ab7b601/npm-packages/node-executor/src/executor.ts#L75-L117)、[Issue #492](https://github.com/get-convex/convex-backend/issues/492)

选型检查：生产 self-hosted 不使用 SQLite 承载大表；Node action 并发依赖 env 时，必须先验证修复版本或隔离 workload。Self-hosted 需要自己的 backup、HA、upgrade rehearsal、capacity test 和 end-to-end monitoring。

### 当前公开但本次未复现的缺陷报告

分类：`reported`。这些是风险信号，不是已确认故障率。

- Issue #498 报告 Cloud 和 local default runtime 中，同一 `Blob` 第二次读取返回等长的全零字节，Node action 不受影响。报告给出最小复现和 `convex@1.42.1` 环境，但尚无 maintainer 确认。本 workload 若会重复消费 Blob，发布前应在目标 runtime 跑同一 probe。[Issue #498](https://github.com/get-convex/convex-backend/issues/498)
- Issue #487 报告 single-node self-hosted 在 Postgres mid-commit 断连时，shutdown 与 in-flight isolate 竞态触发 SIGABRT，放大为 VM reboot。[Issue #487](https://github.com/get-convex/convex-backend/issues/487)
- Issue #466 报告大型 component/function bundle 在有 active WebSocket session 时，每次 deploy 后产生约 4 分 26 秒 query rejection。[Issue #466](https://github.com/get-convex/convex-backend/issues/466)
- Issue #317 报告 Railway self-hosted vector backfill/compaction 在大规模 embedding 数据上崩溃并拖垮 backend。[Issue #317](https://github.com/get-convex/convex-backend/issues/317)

这些 issue 必须按 target version、storage backend、runtime 和 workload 单独复现。不能从一个 issue 推断 Convex Cloud 的整体可靠性。

## Appendix A：2026-07-13 公开硬限制快照

以下数字来自 2026-07-13 的官方 Limits 页面，可能变化：

| Surface | Current public limit |
| --- | --- |
| Document | 1 MiB, 1024 fields, depth 16, 8192 array elements |
| Function args / return | 16 MiB; Node action args 5 MiB |
| Runtime | Query/mutation user code 1 s; action 10 min |
| Transaction | 16 MiB read, 16 MiB write, 32k scanned docs, 16k written docs, 4096 index ranges |
| Action memory | Convex runtime 64 MiB; Node runtime 512 MiB |
| HTTP action response | 20 MiB |
| Scheduling | 1000 scheduled calls per mutation; 1M outstanding scheduled functions |
| Database indexes | 32 per table, 16 fields per index |
| Full-text search | 4 indexes per table, 16 terms, 8 query filters, 1024 max result scan |
| Vector search | 4 indexes per table, 2–4096 dimensions, 64 filters, 256 results |

来源：[Limits](https://docs.convex.dev/production/state/limits)。长期 Skill 不应写死这些数字，只应写获取路径和 stop condition。

## Appendix B：本机官方仓库审计快照

审计开始时 15 个仓库工作区全部 clean。`current` 表示本机 HEAD 与 2026-07-13 查询到的远端 HEAD 相同；`behind` 只作为历史材料，不承担当前事实。

| Repository | Local commit | Remote relation |
| --- | --- | --- |
| action-cache | `9bdceaf63a45` | behind |
| action-retrier | `223f64c1b9cf` | current |
| agent | `b3034d7bd7fa` | current |
| aggregate | [commit](https://github.com/get-convex/aggregate/commit/ef00fb8afe9e419f6013ae7d8e8c0478c2960752) | current |
| convex-backend | `559e283c62b2` | current |
| crons | `e9117b389c7b` | current |
| demos | `66c654b82513` | behind |
| helpers | `62347d31f265` | behind |
| convex-js | `f57c39da88fd` | behind; current JS source was read from `convex-backend` |
| migrations | `2219852f3b68` | current |
| persistent-text-streaming | `588be3cc3f9b` | current |
| rate-limiter | `da8e62b8d7e0` | current |
| sharded-counter | `534b098a5f1e` | current |
| workflow | `38140a939953` | current |
| workpool | `121c076a5666` | current |

## 十一、仍未验证

- 没有对用户真实项目或 Convex Cloud 做 load test，无法给出 p95/p99、OCC saturation point、subscription fan-out 成本或 scheduler lag。
- 没有 Enterprise 合同、DPA、SLA 和 support 承诺，公开文档不能替代客户协议。
- 没有复现 issue #498、#487、#466 或 #317。
- 没有验证未公开的 self-hosted 多实例方案。结论只是「没有公开、可依赖的 HA runbook」，不是「技术上绝不可能」。
- 没有穷尽 Discord、私有 support case、全部 closed issue 和每个历史 release。公开 issue 只用于识别当前风险面，不用于估计 incidence rate。
