---
name: pr-open
description: 'Create or update GitHub PRs. Triggers: open PR, create PR, update PR.'
metadata:
  version: '6'
---

# Opening OR Updating PR

## Step 0: Normalize Workspace

### 0a. 并行评估

```bash
git fetch origin
git status --porcelain
git branch --show-current
git log --oneline HEAD..origin/main 2>/dev/null
```

如果不在 main，还要检查：

```bash
BRANCH=$(git branch --show-current)
git log --oneline HEAD..origin/"$BRANCH" 2>/dev/null
gh pr view --json number,state 2>/dev/null
```

### 0b. 处理工作区

> ⚠️ 工作区不干净时，**禁止**做 rebase / checkout / branch 操作。先处理脏状态。

| 工作区 | 操作 |
| :--- | :--- |
| 干净 | 继续 |
| 有未提交改动 | 先 commit 到当前分支（或 stash），再做任何 branch/rebase 操作 |

### 0c. 处理分支

| 当前分支 | 操作 |
| :--- | :--- |
| `main` + 有 Linear issue | `linear issue start <id> --from-ref origin/main` |
| `main` + 无 issue 上下文 | 询问用户分支名 |
| feature branch，名称规范 | 继续 |
| 临时分支（如 `alex/temp`） | `git branch -m <proper-name>`，如有远端旧分支 `git push origin --delete <old>` |

### 0d. 同步远端

| 情况 | 操作 |
| :--- | :--- |
| 远端分支不存在 | 首次推送，无需处理 |
| 远端分支 = 本地 | 无需处理 |
| 远端有本地没有的 commit | 先确认来源（自己另一台机器 or 别人推的），询问用户 |
| main 有与本 PR 相关的变更或存在冲突 | `git rebase origin/main` |
| main 只是领先几个无关 commit | 不需要 rebase——squash merge 不在乎中间历史 |

> ⚠️ **禁止 `git reset --soft origin/main && git commit`**——会把分支旧代码覆盖 main 上后续 PR 的修改。
>
> ⚠️ rebase 冲突解决时 ours/theirs 与 merge **相反**：ours = origin/main（rebase onto 目标），theirs = 你的 commit。

## Step 1: Gather All Context

> ⚠️ **先收集所有上下文，再动笔写 PR / 更新 Linear。** 跳过任何一个来源都可能导致描述不完整或与实际偏移。

以下来源**并行获取**：

### 1a. Code diff

```bash
# 分支上所有变更（... = merge-base 视角，最接近 PR diff）
git diff --stat origin/main...HEAD
git diff origin/main...HEAD

# 分支上的所有 commits（可能有之前的 wip commits）
git log --oneline origin/main..HEAD
```

**常见错误**：只看 `git status`（uncommitted changes），忽略分支上已有的 commits，导致 PR 描述不完整。

### 1b. Existing PR

```bash
gh pr view --json number,url,state,title,body
```

已有 Open 的 PR，那么后续只需增量更新。

### 1c. Existing Linear Issue

```bash
linear issue view $(linear issue id) --json
```

### 1d. Amp Threads

**识别当前 Thread 并追溯**：

1. **当前 Thread**：你正在工作的这个
2. **Handoff 来源**：如果当前 Thread 是从其他 Thread handoff 过来的，追溯上游
3. **Cluster 搜索**：用 `find_thread` 工具的 `cluster_of:` 过滤器查找同一任务的相关 threads

| 搜索场景 | query 参数 |
| :--------- | :----------- |
| 同 cluster 的 threads | `cluster_of:T-当前thread-id` |
| 关联 Linear issue | `task:AI-596` |
| 包含依赖任务 | `task:AI-596+` |
| 按关键词 + 时间范围 | `skills migration after:7d` |

对每个候选 Thread，用 `read_thread` 验证是否真正相关：

- ✅ 讨论了本 PR 要解决的问题 / 包含设计决策 / 是直接前置任务
- ❌ 只是碰巧修改了同一文件 / 完全独立的功能开发

### 1e. PR 模板

```markdown
# Pull Request

<!-- Thank you for your contribution! -->

## Title

建议 PR 标题遵循下列格式：

`<type>(<scope>): <subject>`

- type
  - `feat` 新功能或对外行为变化
  - `fix` Bug 修复
  - `refactor` 重构，不改变对外行为
  - `chore` 工程杂务 (依赖升级、脚手架、配置等)
  - `ci` CI、构建、质量检查
  - `docs` 文档
  - `test` 测试
  - `perf` 性能优化
  - `revert` 回滚
- scope
  - 例如：deck, eye, search, news, tcgen, spider, core, playground, infra, docs
- subject
  - 一句话说明做了什么 / 目的是什么，不写实现细节
  - 中文或中英混排都可以，避免句号结尾
  - 控制在 72 字符内，细节放正文

## Change Summary

<!-- Please give a short summary of the changes. -->

## Related Amp Threads

<!-- Optional: Link to Amp threads that contributed to this PR for context and traceability. -->
<!-- Example: https://ampcode.com/threads/T-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx -->

## Checklist

- [ ] PR 的标题能精确地压缩变更信息（模块、类型、意图都清晰）
- [ ] PR 中新增的行为（新功能或修复）有相应的测试
- [ ] 本地运行 `mise format`、`mise lint` 与 `mise test` 并通过

### AI Review

- [ ] 使用 `gpt-5.4-pro` 检查过代码，建议 2/2 Pass，提示词可用 Repo Prompt 构建
  - AI 的正确建议：请修复
  - AI 的错误建议：请添加必要的注释
    - AI 是不懂业务的 Junior 程序员，如果它给出了错误建议，大概率你代码无法「自解释」，即很有其中有业务相关的魔法，为确保「一切与代码相关的都在 Monorepo 中跟踪」的原则，请麻烦添加注释
- [ ] 使用 Amp 或 Codex 的 `gpt-5.4 high` 的 `/review` 命令检查过代码（如可用），建议 3/3 Pass
```

## Step 2: Push & Create/Update PR + Linear

> ⚠️ **PR 和 Linear 在同一步骤内一起写出**，确保两者内容对齐、来源一致。

### 2a. Push

```bash
BRANCH=$(git branch --show-current)
if [ -n "$(git log --oneline HEAD..origin/"$BRANCH" 2>/dev/null)" ]; then
  echo "⚠️ Remote has commits not in HEAD. Rebase first or confirm overwrite."
  exit 1
fi

git push -u origin HEAD --force-with-lease
```

### 2b. 判断 PR create vs edit

> ⚠️ **必须检查 PR 的 state，不能只看 PR 是否存在！**

Squash merge 后，本地分支名可能与已合并 PR 的分支名相同。如果不检查 state 就执行 `gh pr edit`，会错误地修改历史 PR 的内容。

| `gh pr view` 结果 | 操作 |
| :---------------- | :--- |
| 不存在 PR | `gh pr create` |
| state = `OPEN` | `gh pr edit` 更新现有 PR |
| state = `MERGED` 或 `CLOSED` | `gh pr create` 创建新 PR |

### 2c. 写出 PR

```bash
# 创建新 PR
gh pr create --base main --title "..." --body "..."

# 更新现有 OPEN 状态的 PR
gh pr edit --title "..." --body "..."
```

### 2d. 同步 Linear Issue

对比 Step 1c 获取的现有 issue 与 PR 最终内容，判断是否偏移：

| 判断项 | 偏移 → `linear issue update` | 无偏移 → `linear issue comment add` |
| :--- | :--- | :--- |
| issue 标题能否准确概括 PR 变更？ | 标题过时或范围变了 | 仍然准确 |
| issue 描述是否覆盖所有关键变更？ | 缺少重要内容 | 已覆盖 |
| PR 中有 issue 里没提的工作？ | 有 | 无 |

**对齐原则**：

- Issue 标题 = PR 标题的中文版（或等价语义）
- Issue 描述 = PR body 的精简版，聚焦「做了什么」而非「怎么做的」
- 不要保留过时的原始描述——直接覆盖，Git 有历史
- 无论 update 还是 comment，都必须关联 PR 链接和相关 Amp Threads

## Amp CheatSheet

| 工具 | 用途 | 备注 |
| :----- | :----- | :----- |
| `find_thread` | 搜索 Threads | 支持 `file:`, `task:`, `cluster_of:`, `after:` 等过滤器 |
| `read_thread` | 读取并摘要 Thread | 需提供 threadID 和 goal 参数 |
| `handoff` | 移交到新 Thread | 当前 Thread 的工作由新 Thread 继续 |

## gh CheatSheet

```bash
gh pr view --json number,title,url,state,body

gh pr create --base main --title "..." --body "..."

gh pr edit --title "..." --body "..."
```

## linear CheatSheet

```bash
linear issue id

linear issue view <issue-id> --json

linear issue update --help

linear issue comment add --help
```

## Troubleshooting

### Repository not found

```bash
gh auth status

gh auth switch
```
