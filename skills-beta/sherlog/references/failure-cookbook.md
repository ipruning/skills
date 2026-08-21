# Failure Cookbook

先判断失败发生在哪一层，读取 error payload/hint，再按表处理；不要把所有问题都用无条件 full sync 解决。

**`nextAction` 限制**：`index_unavailable` 有闭包 `command` 时，按宿主权限原样执行 `recommended: true`（或唯一）那条。默认 Codex `all`+`cwd` 二选一只用于无 `--root/--cwd/--selector` 的首次安装；cwd/root/selector 查询不要改走 `all(root)`。旧版或只有 `argv` 的建议仍需检查是否保留原命令的 `--db`、`--source` 和 selector/scope。缺失时补回原上下文，不要为了覆盖缺失而盲目扩大 scope。

## 错误处理表

| 错误 | 立即动作 |
| --- | --- |
| `shlog` 不存在 / 版本过旧 | 安装或升级 CLI（见下方），再重试原命令 |
| `index_unavailable` | 执行 recommended 闭包 command（`write_index`）；旧版无 command 时才补 `--db`/`--source`/scope，且只限当前 repo 才 `--cwd` |
| `index_schema_upgrade_required` | supported `legacy_v7` 才执行带原 `--db` 的迁移 sync；future/incompatible 版本不重复 sync，用兼容 binary 或可信 backup |
| `session_not_found` | 确认 `sessionRef`/source；恢复 `--cwd/--selector` 后跑 `status`；`recommendedAction=sync` 才同范围 sync |
| `anchor_not_found` | 按 nextAction 回退 `read-page`，或改用消息中真实出现的 term；不伪造 seq |
| zero results | 同 selector `status`；`query` 则 refine，`sync` 则同范围 sync 后重试 |
| strict sync failure | 看 `errorDetails[]` 修 source 后同范围重试；不用 `--best-effort` 冒充 complete |
| `invalid_selector` / `invalid_cold_root` | 修正参数/路径后重试；不降级成无 scope 的全局 destructive sync/prune |

## 安装

```bash
curl -fsSL https://github.com/catoncat/sherlog/releases/latest/download/install.sh | sh
# 或：brew tap catoncat/sherlog && brew install sherlog
```

CLI 与 skill 分开安装；版本落后时升级后重试原命令。只有随后出现 supported v7 migration 或 coverage `recommendedAction=sync` 时才运行对应 scope 的 sync。

## (a) Zero results / coverage

`find` 是 query-only：不扫描源会话文件，所以 stored coverage 的 `freshness` 正常为 `not_checked`，zero-result diagnosis 通常是 `coverage_not_confirmed`。即使 `coverage.complete=true`，也不代表源会话文件此刻未变化。

对相同 selector 跑 `status --cwd/--selector --json`：

- `recommendedAction: "query"`：不要 sync，refine/retry。
- `recommendedAction: "sync"`：同范围 sync 后重试；不扩大为无关全量 destructive sync。
- `source_content_changed` + `query`：proven append 的 soft stale，只有答案依赖最新 tail 时才 sync。truncate/prefix rewrite 无法证明 append，会给出 `sync`，不要当 soft stale 继续 query。

Refine：去掉冗余自然语言；用稳定 identifier/error phrase；单字 CJK 改两字词；不用用户自造 FTS `OR`/`NEAR`/`*`。已有 candidate 时继续 `evidenceRead`，但不要声称完整。

## (b) Index unavailable / schema upgrade

`index_unavailable`：index 不存在，只读命令不会创建它。优先原样执行 recommended（或唯一）`nextAction.commands[].command`，其中已闭包 `--db`/`--source`/scope，并以 `sideEffect: "write_index"` 声明写入。默认 Codex alternatives 只覆盖无 scope 的首次查询。旧 CLI 没有闭包 command 时使用：

```bash
shlog sync --json          # 默认 Codex all(root)
shlog sync --cwd <repo> --json   # 仅限当前 repo 的问题
```

`index_schema_upgrade_required`：`status` 会报告 `index.layout`（`native_v8` / `legacy_v7` / `none`）。supported `legacy_v7` 才运行带原 `--db` 的同 source/root `sync` 触发迁移；迁移单向且 coverage 清空，需重新 sync 常用 root/selector。future/unknown 版本不要手改 index，用兼容 binary 或受信 backup 恢复。不要手工 patch 旧库或反复重试读命令。

## (c) Session / anchor errors

`session_not_found`：可能因 bare UUID 被按 Codex 解释、raw 存在但未同步、selector 未覆盖或已 prune。从原始 find invocation / candidate cwd / 用户问题恢复最窄 `--cwd`/`--selector`，跑同 source/root 的 `status`；只有 `recommendedAction=sync` 才同步同范围，再重试原 read。无法恢复 scope 时说明无法证明 coverage。

`anchor_not_found`：query 只命中 session-level 字段（`matchedProfileFields`）或投影缺该 term。按 nextAction 回退 `read-page`，或 refine query 到消息中真实出现的 term；不伪造 `--seq`。关键句因 elision 不可见时用 `--max-message-chars 0`。

## (d) Sync / destructive failures

- strict failure：`errorDetails[]` 是 per-file/source evidence。strict 不发布部分 complete coverage；修 filesystem/permission/malformed source 后同范围 retry。
- `--best-effort`：允许成功 file 先进 projection，但带 errors 且 coverage 不 complete；回答时说明可能漏掉的 scope。
- `sync --prune` / `cold remove`：破坏性，只在用户明确授权后执行。cold root unreadable/walk error 或 non-Codex source 时 prune fail-closed，不绕过；不手工删 DB/lock/backup。
