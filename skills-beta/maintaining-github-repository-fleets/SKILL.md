---
name: maintaining-github-repository-fleets
description: "Audits and applies human-approved maintenance plans across a GitHub user or organization repository fleet. Use when comparing GitHub inventory with local checkouts, cloning missing repositories, strictly fast-forwarding safe default branches, detecting origin/upstream or canonical-name drift, materializing multiple repositories for AI audits, or refreshing Jihuanshe's existing repository code corpus through its owning .github workflow. Not for ordinary single-repository Git work, pull requests, releases, deployments, organization access audits, or repository architecture and codemap semantic analysis."
---

# 维护 GitHub 仓库集合

先把远端 inventory、本地 checkout 和拟执行动作固化为不可变计划。向用户展示计划并停止。只有用户明确批准这份计划后，才用计划 hash 执行。不得把一句笼统的「同步所有」视为对尚未展示计划的批准。

## 边界

本 Skill 管理两类本地对象：

- 日常开发 checkout：缺失仓库可以 clone；只有满足全部门禁的默认分支可以 fast-forward。
- 临时审计 lease：把固定 commit clone 到隔离目录，供 AI 或 Sub Agent 只读取证。

在具体 plan hash 获批前只观察。CLI 不修改 GitHub metadata，不 push，不同步 fork 的 upstream，不修 remote，不切分支，不 stash、reset、rebase、clean 或 prune。Description、topics、visibility、archive、默认分支和组织权限不属于这个 CLI 的写入面。

单仓库 Git 工作使用现场仓库的普通 Git 工作流。PR、release、deployment、GitHub access audit 和 repository codemap 使用各自的专业 Skill。

## 确定目标

先把用户原话翻译成四个值，不从 cwd、目录名或当前 active GitHub account 猜测：

- `owner`：GitHub user 或 organization。
- `gh_user`：本次命令使用的已登录 GitHub login。
- `root`：日常 checkout 根目录或临时 lease 父目录。
- `scope`：显式 `--all`，或一个以上 `--repo <name>`。

| 用户意图 | 参数判断 |
| --- | --- |
| 「同步我的 GitHub checkout」 | `owner` 是用户明确指定的 GitHub user；`root` 是用户给出的 checkout 父目录。 |
| 「治理某个组织的仓库」 | `owner` 是明确的 organization；如果对象是 Jihuanshe `_repo-corpus`，改走本 Skill 的代码缓存流程。 |
| 「全部仓库」 | 使用 `--all`。 |
| 「只看 A、B」 | 对每个名称使用一次 `--repo`。 |

用 `gh auth status --hostname github.com` 只读发现已登录账号。多账号或 owner 与 login 不同时，按全局 GitHub 身份规则确定 login；不能唯一确定就先向用户确认。CLI 通过 `gh auth token --user <login>` 取得单次 token，不切换全局 active account。

## 生成计划

脚本只有 `plan` 和 `apply` 两个公开命令：

```bash
skill_dir="<directory containing this SKILL.md>"
cli="$skill_dir/scripts/repo_fleet.py"
uv run --script "$cli" --help
```

`plan` 可以读取 GitHub 和本地 Git 状态，并写一个新 plan 文件。它不得 fetch、clone、checkout、merge 或修改 Git refs。计划文件必须放在用户可审阅的位置；在 Amp 中使用 workspace 的 `.amp/in/artifacts/`。

### 日常 checkout 同步

显式声明允许纳入计划的候选动作。`--allow` 只决定哪些具体 action 进入 plan，不构成执行授权。只审计时同时传两类 action 才能完整暴露 clone 与 fast-forward 候选，但不得继续调用 `apply`：

```bash
uv run --script "$cli" plan \
  --operation workspace-sync \
  --owner <owner> \
  --gh-user <login> \
  --root <checkout-root> \
  --all \
  --allow clone \
  --allow fast-forward \
  --out <new-plan.json>
```

只调查部分仓库时，用重复的 `--repo <name>` 代替 `--all`。

plan hash 同时覆盖规范化后的 scope、允许动作、现场 findings、blocked 原因与具体 actions。`plan` 只枚举 `root` 的直接子目录，不递归寻找 `.git`。它用 Git common dir 区分 primary checkout、linked worktree、外部 worktree 和嵌套 checkout。仓库归属只由 `origin` 决定；`upstream` 单独报告。没有 `origin` 的仓库是 `local_only`，不得根据目录名补猜远端。

如果旧 remote URL 经 GitHub redirect 指向新 canonical name，计划报告 `name_mismatch`，不得把新名称再 clone 一份。

### 临时 AI 审计材料

`root` 必须是已经存在的 lease 父目录。历史策略必须显式选择：

```bash
uv run --script "$cli" plan \
  --operation audit-materialize \
  --owner <owner> \
  --gh-user <login> \
  --root <lease-parent> \
  --all \
  --history shallow \
  --out <new-plan.json>
```

`shallow` 只取默认分支浅历史；`full` 使用 blobless、single-branch clone。两者都固定远端 SHA，不递归 submodule。计划必须向用户明确展示选择的策略、仓库数和目标目录。

每个审计 checkout 都有 `.repo-fleet-lease.json` ownership marker。不得把 lease 当日常开发 checkout，也不得把现有开发 checkout 变成 lease。

### 释放审计 lease

删除也必须先计划：

```bash
uv run --script "$cli" plan \
  --operation audit-release \
  --lease <owned-lease-directory> \
  --out <new-release-plan.json>
```

脚本只接受 marker、resolved path 和 owner 都一致的非 symlink 目录。marker 与 result 是防止误选目录和恢复中断的本地证据，不是抵御同一系统账号恶意篡改的安全边界。怀疑同 UID 进程或本地文件被篡改时，不执行 release 或 resume。

## 展示并等待批准

读取完整 plan JSON，向用户展示：

- `owner`、`gh_user`、`root`、operation 和 scope；
- policy 中允许的 action 或历史策略；
- 每个 action 的 repository、类型、目标路径和 pinned SHA；
- `blocked` 中每项具体原因；
- clone、fast-forward、materialize、release 和 no-op 数量；
- 计划的 `plan_sha256`。

展示后停止。用户需要明确批准当前 hash 对应的计划。用户改变 scope、允许动作、目标目录或历史策略时，生成新计划并重新批准。不得编辑旧 plan 后自行重算 hash 继续执行。

## 执行批准计划

只有获得批准后才能运行：

```bash
uv run --script "$cli" apply <approved-plan.json> \
  --confirm-owner <owner> \
  --confirm-plan-sha256 <approved-sha256> \
  --result <new-result.json>
```

result 路径在 apply 时选择，不属于批准的 mutation scope；它必须与 plan 分开并位于 managed root 外部。`apply` 不接受 `--all`、`--repo`、`--allow` 或新的 action。它重新校验 plan schema、hash、owner、路径边界和现场 preconditions，再串行执行并逐项原子 checkpoint。原 plan 保持不变，result 文件可以用于中断恢复。

工作区 clone 先写同级 staging，校验 origin、默认分支和 pinned SHA 后再原子改名。Fast-forward 只处理 clean primary default-branch checkout，并要求 origin identity、local HEAD 与 remote SHA 仍和计划一致。实际更新使用 `git merge --ff-only`，更新后再回读状态。任一门禁不成立就记录 `stale`，不得改用 `pull`、普通 merge、rebase、reset 或 push。

退出码含义：

| Code | Meaning |
| ---: | --- |
| `0` | 全部 action 已验证收敛。 |
| `2` | 参数、schema、计划 hash 或确认信息无效；没有开始执行。 |
| `4` | 一个以上 action 因现场变化成为 `stale`。 |
| `5` | 发生 `unverified` 或只完成部分 action；停止并 reconcile。 |

`stale` 表示重新运行 `plan` 并再次让用户批准。不得绕过 CLI 用临时 Git 命令补做。`unverified` 表示 mutation 结果不确定；先读取 result、Git 状态和远端事实，确认实际状态后再决定恢复。

## Jihuanshe 代码缓存

当目标是 Jihuanshe 持久 `_repo-corpus` 时，不使用通用 `audit-materialize` 重建现有能力。定位 `jihuanshe/.github` 的权威 checkout，读取其 `AGENTS.md`，调用已有脚本：

```bash
node scripts/graph/sync-corpus.mjs \
  --gh-user <login> \
  --dry-run \
  --json \
  --quiet > <dry-run.json>

jq -S 'del(.generatedAt,.metadataGeneratedAt)' <dry-run.json> | shasum -a 256
```

`--repo`、`--no-clean`、`--no-prune`、`--corpus-dir`、`--jobs` 或其他 policy flag 必须在 dry-run 时就完整给出。保存原始 JSON，并用去掉两个时间字段后的稳定 JSON hash 标识批准对象。展示 clone、update、empty、prune、legacy-index cleanup、scope、clean policy 和 credential identity，然后停止等待用户批准该 hash。

批准后先用完全相同的 scope 和 policy flags 重新 dry-run，计算相同的稳定 hash。hash 变化就重新展示并等待批准；相同才运行只去掉 `--dry-run` 的命令。这个门禁适用于全量和部分 scope。

`_repo-corpus` 是允许 detached、shallow、sparse、reset、clean 和 prune 的证据缓存，不是开发工作区。不得在其中保留分支、commit 或未提交工作。

Jihuanshe GitHub Description 只能使用该 `.github` 仓库规定的 `sync-github-descriptions.mjs` 流程；不要通过本 CLI 或 `gh repo edit` 绕过仓库图谱证据门禁。

## 报告

报告 observation、plan 和 apply 三层事实，不把它们混成「已同步」：

- observation：远端与本地在计划时间的状态；
- plan：用户批准的具体动作；
- result：实际执行、跳过、stale、unverified 和回读验证结果。

只把 result 中的 verified 状态报告为完成。保留 plan 与 result 供复核；临时 lease 在审计结束后另行生成 release plan。
