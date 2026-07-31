使用与用户相同的语言回复。中文使用直角引号「」；中文与英文单词、缩写或数字相邻时，插入 1 个半角空格。

按 AST 结构搜索或替换代码时，优先使用 `ast-grep`。

## Git 与 GitHub 身份

在配置了多个 Git 身份的环境中，对每个仓库的首次 commit 前，确认该仓库生效的 Git 用户名和邮箱与目标身份一致。

GitHub 多账号时，先从目标 repo、组织或用户明确指示中唯一确定 login；除「Skill 冲突与反馈」一节另有规定外，不能唯一确定时在写操作前询问。不得切换 `gh` 的全局 active 账号；指定身份没有权限时，不改用其他账号。

调用 `gh` 时，先取得指定账号的非空 token；失败即中止，并仅为本次命令注入该 token：

```bash
tok="$(gh auth token --user <login>)" && [ -n "$tok" ] || exit 1
GH_TOKEN="$tok" gh <command>
```

通过 HTTPS 执行 `git push` 时，仅为本次命令注入指定账号的凭据，不修改全局 Git 配置：

```bash
tok="$(gh auth token --user <login>)" && [ -n "$tok" ] || exit 1
GH_TOKEN="$tok" git -c credential.helper= \
    -c 'credential.helper=!gh auth git-credential' \
    push
```

## Skill 冲突与反馈

Skill 指令与当前源码、配置、运行环境或实测结果冲突时，以现场证据为准，只偏离冲突部分并继续完成仍然安全的工作。不要静默绕过，也不要在当前任务中顺手修改已安装的 Skill。

发现可复用的 Skill 缺陷时，定位该 Skill 的权威来源仓库，优先使用当前环境中的 Skill 管理器元数据。一次性环境故障和纯项目代码缺陷不作为 Skill 问题反馈。

提交反馈前，使用与来源仓库匹配的 GitHub login 检查仓库权限。只有该 login 对来源仓库拥有 `push`、`maintain` 或 `admin` 权限且仓库启用了 Issues 时，才已授权在完成最小证据整理、脱敏和同根因 Issue 去重（包括已关闭 Issue）后，直接创建 Issue 或向已有根因 Issue 补充评论，无需再次询问。不能仅因公开仓库允许创建 Issue 就提交。

来源、身份、权限或脱敏边界无法唯一确定时，不提交也不中途询问，改为在收尾明确报告 Skill、来源版本、预期与实际、最小证据、临时绕法和影响；能够确定 Issue 格式时同时提供完整草稿。

## 新执行环境与外部数据

任务需要在新执行环境中运行或验证项目时，按仓库已有配置准备最小必要的依赖和生成物，不从其他 checkout 复制依赖目录、构建产物或工具缓存。只把无法重建的必要非敏感输入带入环境；凭据和敏感配置通过目标环境支持的安全渠道注入，不进入 tracked 文件、日志或交付物。使用外部数据时，区分实时权威来源与固定快照，不把未经核实的本地副本当作当前事实；审计、评测和复现任务使用任务指定的版本或快照，不自行刷新。

## 阻塞通知

仅当任务需要用户执行某个具体操作才能继续、且当前没有其他部分可以推进时，通知 1 次。通知只说明需要用户返回 Amp 处理，不包含凭据、路径、命令或日志。

当前环境存在 `sag` 时，先执行：

```bash
sag speak --lang zh --timeout 30s \
  "当前任务需要你的操作才能继续，请查看 Amp。"
```

`sag` 不可用或执行失败，且 `BRRR_SECRET` 非空时，发送 brrr Push：

```bash
printf 'header = "Authorization: Bearer %s"\n' "$BRRR_SECRET" | \
curl -fsS --max-time 10 -X POST -K - \
  -H "Content-Type: application/json" \
  --data '{"title":"Amp 任务等待操作","message":"当前任务需要你的操作才能继续，请返回 Amp 查看详情。","interruption_level":"time-sensitive"}' \
  https://api.brrr.now/v1/send
```

两种渠道都不可用或通知失败时，不为修复通知能力扩展任务；汇报阻塞状态并结束。

## 临时兼容代码

引入仅为兼容、迁移或灰度而存在的临时代码时，在最接近该行为的位置留下符合仓库惯例的 TODO，说明为何暂时保留、什么可验证条件成立后可以清理、届时应清理什么，以及如何验证清理结果。信息应足以让不了解当前对话的人或 AI 安全行动，不要求固定标签或字段格式。

执行清理任务时，搜索相关 TODO 和临时兼容逻辑；仅在条件满足且清理属于当前任务时清理并验证，否则保留。不要模仿或扩散被标记的临时写法。
