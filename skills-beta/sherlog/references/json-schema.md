# Public JSON Contracts

字段使用 camelCase，具体 payload 可直接从 `--json` 输出查看。这里只给影响检索决策的三个 contract：coverage、`evidenceRead`、`nextAction`/error。

## `coverage` / `requestedCoverage`

```ts
interface CoverageStatus {
  requested: Selector | null;
  complete: boolean;
  freshness: "fresh" | "stale" | "missing" | "not_checked";
  staleReason?: "none" | "missing" | "source_content_changed" | "source_set_changed";
}
```

- `find/list/read/stats` 的 coverage 只来自 stored proof；`find/list` 的 `freshness` 是 `not_checked`。Live comparison 只在 `status` 中出现。
- `requestedCoverage` 只在 `status --cwd/--selector` 时出现，其中 `recommendedAction: "query" | "sync"` 决定是否同范围 sync。
- `coverage.complete=true` 只表示 SQLite 有 compatible covering record，不代表源会话文件此刻未变化。

## `evidenceRead`

`find` 的每个 candidate 带 `evidenceRead`，指示如何读取该 candidate 的实际内容：

```ts
type EvidenceRead =
  | {
      kind: "read-range" | "read-page";
      sessionRef: string;
      command: { executable: "inherit"; args: string[]; sideEffect: "read_index" };
    };
```

- `executable: "inherit"` 表示：使用产生这条 `find` 结果的同一个 `shlog` 调用（即你在本会话使用的 `shlog`），不要按字面执行名为 `inherit` 的程序。
- `args` 已闭包 `--source/--db/--json`，与产生候选的上下文一致；把 `args` 完整传给 `shlog` 执行。
- `matchSource="session"` 时 `matchSeq=null`；不要构造虚假的 `--seq -1`；`read-range --query` 无 message anchor 时返回 `anchor_not_found`，按 nextAction 回退 `read-page`。

## `nextAction` 与 error envelope

```ts
interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    [key: string]: unknown;
  };
}
```

常见 code：`index_unavailable`、`index_schema_upgrade_required`、`session_not_found`、`anchor_not_found`、`unsupported_source`、`invalid_selector`、`invalid_cold_root`、`index_error`。

`nextAction.commands[].argv` 是 **recommendation**，执行前要核对：

- 它可能省略原命令的 `--db` / `--source` / scope（尤其是 `index_unavailable`）；把原命令上下文补回去。
- 不要为了覆盖缺失而盲目扩大 scope。
- `anchor_not_found` 的 nextAction 是回退 `read-page`；`index_schema_upgrade_required` 的 nextAction 是带原 `--db` 的迁移 sync。

CLI parse error 不保证 JSON envelope；例如缺少 `find` query 是 plain stderr compatibility text。
