# Convex Risk Surfaces

这是一份问题索引，不是平台行为清单。只读取工作负载触及的章节，并从目标项目版本、当前官方文档或对应源码取得答案。数字、delivery、retry、cancel、auth propagation、runtime、deployment class、region、价格和 beta 状态都可能变化。

## Transaction and contention

- 高频 mutation 的 read set、write set、热点 key、峰值并发和可接受 conflict rate 是什么？
- 目标版本的 OCC retry 与错误语义是什么？团队级并发限制与单热点吞吐是否被错误等同？
- Sharding 或 aggregate component 把写入压力换成了哪些精确读取、估算、rebalance、query bounds 或 key-distribution 代价？
- Evidence: [OCC](https://docs.convex.dev/database/advanced/occ), [Errors](https://docs.convex.dev/error), [Limits](https://docs.convex.dev/production/state/limits), target component README and source.

## Query and realtime

- 目标版本以什么粒度跟踪 query dependency？哪些写入会使订阅失效和重算？
- Compound index ordering、过滤前扫描、无 range query 与 pagination 是否保持有界？
- 更新频率、read-set、唯一订阅参数与订阅数、重算、cache miss 后读取和返回字节分别是多少？
- Evidence: [Query functions](https://docs.convex.dev/functions/query-functions), [Indexes](https://docs.convex.dev/database/reading-data/indexes), [Pagination](https://docs.convex.dev/database/pagination).

## Client delivery and offline

- 目标 client 在 reconnect、process termination、mobile eviction 和 restart 后分别保留什么状态？
- Pending writes 是否需要 durable local outbox？冲突、权限撤销、账号切换和永久 rejection 的产品语义是什么？
- 每种 WebSocket、Rust、HTTP 或 OpenAPI caller 的 ordering、subscription 与 retry owner 是谁？
- Evidence: [Client libraries](https://docs.convex.dev/understanding/overview#client-libraries), [Mutation functions](https://docs.convex.dev/functions/mutation-functions), [OpenAPI](https://docs.convex.dev/client/open-api).

## Actions and external side effects

- 目标版本的 action transaction、retry 和 disconnect 语义是什么？调用失败能否区分「未执行」与「结果未知」？
- Durable intent、idempotency key、attempt、provider event 和 reconciliation 由哪个权威数据库保存？
- 多次 `runQuery` 或 `runMutation` 之间需要一致 snapshot 或原子性吗？
- Evidence: [Actions](https://docs.convex.dev/functions/actions).

## Scheduler, Workflow, and Workpool

- Scheduled mutation、scheduled action、cron、Workflow 和 Workpool 各自的 delivery、retry、auth propagation、overlap、cancel 与 cleanup 是什么？
- 调度调用与发起 transaction 是否原子？长 run 会排队、跳过还是并发？
- Active workflow 对 step topology、代码版本、journal、输入输出和旧实例保留有什么要求？
- Evidence: [Scheduled Functions](https://docs.convex.dev/scheduling/scheduled-functions), [Cron Jobs](https://docs.convex.dev/scheduling/cron-jobs), target project package README and source.

## Search

- Full-text、vector search 和普通 query 的 transaction、reactivity、排序、分词、filter 和结果加载语义分别是什么？
- 产品是否需要中文分词、稳定排序、动态 faceting、复杂 filters、reactive semantic search 或搜索分析？
- Search index 能否从权威状态重建，是否存在隐式回写？
- Evidence: [Full Text Search](https://docs.convex.dev/search/text-search), [Vector Search](https://docs.convex.dev/search/vector-search).

## File Storage

- 下载 URL 是 bearer capability 还是每次重新授权？需要 expiry、单独 revoke、CDN policy 或大文件 private serving 吗？
- 上传文件与业务 mutation 之间如何处理 pending 状态、失败清理和 orphan GC？
- 生命周期、出口流量、对象版本和外部处理由谁负责？
- Evidence: [File Storage](https://docs.convex.dev/file-storage/overview), [Upload Files](https://docs.convex.dev/file-storage/upload-files).

## Backup and analytical sync

- Backup 包含 code、config、environment、files 和 pending jobs 中的哪些对象？Restore 如何处理目标已有文件？
- 目标 RPO/RTO 是否经过 restore drill，而不是只证明 backup 存在？
- CDC 如何处理 insert、update、delete、truncate、restore、schema evolution、lag、cursor recovery 和全量重建？
- Evidence: [Backup and Restore](https://docs.convex.dev/database/backup-restore), [Streaming Import and Export](https://docs.convex.dev/production/integrations/streaming-import-export), [Import warnings](https://docs.convex.dev/database/import-export/import#warnings).

## Authorization, operator writes, and audit

- 每个 public function 是否有参数验证和明确的 access-control decision？哪些暴露面需要 authentication、tenant/resource authorization 和 rate/abuse control？
- Dashboard、import、repair 或 admin path 是否绕过 mutation、component trigger、projection 或 audit invariant？
- 普通 logs 与 durable audit 的 delivery、去重、actor propagation 和 rollback 语义是什么？
- Evidence: [Internal Functions](https://docs.convex.dev/functions/internal-functions), [Authorization](https://docs.convex.dev/production/state#authorization), [Log Streams](https://docs.convex.dev/production/integrations/log-streams), [Audit Logging](https://docs.convex.dev/production/integrations/audit-logging).

## Cloud platform gates

- 当前 region、data residency、deployment class、concurrency、dataset、cache、networking、backup、SLA 和价格是否满足硬约束？
- Region failover、active-active、专用 outbound identity 或公开能力之外的要求有书面承诺吗？
- Evidence: [Regions](https://docs.convex.dev/production/regions), [Limits](https://docs.convex.dev/production/state/limits), [State and Guarantees](https://docs.convex.dev/production/state), [Networking](https://docs.convex.dev/production/networking).

## Self-hosted

- 目标 release、storage backend、backend 与 dashboard 版本、HA、backup、upgrade、capacity 和 monitoring 分别如何实现？
- 当前公开 issue 是否与目标 version、runtime、storage backend 和 workload 匹配，并已由本项目复现？
- 哪些 Cloud 保证在 self-hosted 环境中有独立证据？
- Evidence: [Self-hosting](https://docs.convex.dev/self-hosting), [convex-backend self-hosted README](https://github.com/get-convex/convex-backend/tree/main/self-hosted), [convex-backend issues](https://github.com/get-convex/convex-backend/issues).
