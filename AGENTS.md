# AI Agent 协作指南

这是个人的全局 Skillshare 源目录，`~/.config/skillshare/config.yaml` 的 `sources.skills` 指向这里，`sources.extras` 指向 `extras/`。先读 config 确认，不要凭目录名判断。

- `_` 开头的目录是 `skillshare install --track` 克隆进来的别的仓库，各自有 `AGENTS.md`，到那个仓库里改。
- `.metadata.json` 登记的包由上游管理，用 `skillshare update` 更新，不在本地改。
- 其余内容由本仓库维护。

Skill 怎么装、更新、同步，以及 Skillshare 的坑，看 `_jihuanshe-skills/agents/skill-lifecycle/SKILL.md`。

## 分类

自有 Skill 和第三方包都按 Skill 做完之后主要改变了什么来放目录：

| 目录 | 主要产物 |
| --- | --- |
| `agent/` | Agent 自身的能力：Skill、Agent 配置和上下文 |
| `think/` | 只留在对话里的结论，不改文件也不改外部状态 |
| `code/` | 工作区里的代码、配置、文档、图片和本地验证 |
| `ship/` | commit、PR、release 等共享交付物 |
| `run/` | 主机、服务、网络、监控等持续运行的状态 |
| `connect/` | 和人或协作、社交平台、个人 app 的交互本身 |

同时符合几类时，按 `agent → think → ship → run → connect → code` 取第一个。第一类叫 `agent/` 而不是 `agents/`，是因为 Skillshare 保留了 `agents` 这个名字。

不分 beta／stable，也不靠 `.skillignore` 屏蔽不用的 Skill：不用就卸载或删掉。第三方包装进分类目录用 `skillshare install <source> --into <分类>`，挪目录用 `skillshare move`，安装记录会跟着走。

## extras

`extras/` 里的文件也是从这里同步到各自的目标。改完先跑 `skillshare extras list --json` 和 `skillshare sync extras --dry-run` 看会写哪里。`copy` 模式下，目标里内容不同的普通文件会被跳过保留，加 `--force` 才覆盖；目标是符号链接时可能被替换掉。

`extras/amp/AGENTS.md` 是 Amp「Personal Settings → Advanced → Global AGENTS.md」的源文件。不要写进 `~/.config/amp`，也不要把任何 `AGENTS.md`／`CLAUDE.md` 配成 Skillshare 的 `agents_source`。

## 检查

跑 `mise run lint`、`mise run test`，最后 `git diff --check`。

第三方包变化后运行 `mise run update-lint-excludes`。各工具配置中的生成块来自 `.metadata.json`，不要手改；`mise run check-lint-excludes` 检查生成结果是否过期。
