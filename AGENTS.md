# AI Agent 协作指南

这是个人的全局 Skillshare 源目录，`~/.config/skillshare/config.yaml` 的 `sources.skills` 指向这里，`sources.extras` 指向 `extras/`。先读 config 确认，不要凭目录名判断。

- `_` 开头的目录是 `skillshare install --track` 克隆进来的别的仓库，各自有 `AGENTS.md`，到那个仓库里改。
- `.metadata.json` 登记的包由上游管理，用 `skillshare update` 更新，不在本地改。
- 其余内容由本仓库维护。

Skill 怎么装、更新、同步，以及 Skillshare 的坑，看 `_jihuanshe-skills/agents/managing-skill-lifecycle/SKILL.md`。

## extras

`extras/` 里的文件也是从这里同步到各自的目标。改完先跑 `skillshare extras list --json` 和 `skillshare sync extras --dry-run` 看会写哪里。`copy` 模式下，目标里内容不同的普通文件会被跳过保留，加 `--force` 才覆盖；目标是符号链接时可能被替换掉。

`extras/amp/AGENTS.md` 是 Amp「Personal Settings → Advanced → Global AGENTS.md」的源文件。不要写进 `~/.config/amp`，也不要把任何 `AGENTS.md`／`CLAUDE.md` 配成 Skillshare 的 `agents_source`。

## 检查

跑 `mise run lint`；改了第三方 Skill 再跑 `mise run check-lint-excludes`；最后 `git diff --check`。
