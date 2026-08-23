# AI Agent 协作指南

本仓库可能是普通 Git checkout，也可能是当前 Skillshare 配置的 source。涉及 Skillshare 操作时先读当前 `config.yaml`，确认 `sources.skills`/`sources.extras` 是否指向本 checkout，以及对应的 `target`/`mode`；不要凭目录名或默认配置判断。

## Skill 状态模型

- `.metadata.json` 中的条目由 Skillshare 或上游管理；`skillshare install --track` 会把上游仓库克隆到 source 下的 `_...` 目录，这些目录也不要直接改写或重命名；其余 source 内容由本仓库维护。
- `skillshare install`、`update` 和 `uninstall` 只改变 source；`sync` 单向将 source 分发到 target，target 修改不会自动回写，反向导入使用 `skillshare collect`。需要更新 target 时，再运行 `skillshare sync`。
- 不要直接编辑 target，也不要把 worktree 放在 configured source 内。

## Extra 同步

- Extra 同样按 source → target 同步；编辑 `extras/` 后先检查当前 `config.yaml`，运行 `skillshare extras list --json` 和 `skillshare sync extras --dry-run`，确认 source diff 可检查且可回退后再同步。`copy` 模式下，内容不同的普通 target 文件默认跳过并保留，`--force` 才覆盖；符号链接可能被同步替换。
- `extras/amp/AGENTS.md` 仅作为 Amp「Personal Settings → Advanced → Global AGENTS.md」的 source；不要写入 `~/.config/amp`，也不要将 `AGENTS.md`/`CLAUDE.md` 配置为 Skillshare `agents_source`。

## 验证

- 运行 `mise run lint`；修改外部 Skill 时再运行 `mise run check-lint-excludes`；最后运行 `git diff --check`，并报告未验证部分。
