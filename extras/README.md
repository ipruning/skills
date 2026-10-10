# 全局 Agent 指令

这里保存三个客户端的全局指令源文件：

| 源文件 | 消费位置 |
| --- | --- |
| `codex/AGENTS.md` | Skillshare 配置中的 Codex extras 目标 |
| `claude/CLAUDE.md` | Skillshare 配置中的 Claude extras 目标 |
| `amp/AGENTS.md` | Amp「Personal Settings → Advanced → Global AGENTS.md」 |

实际同步目录和 copy／merge 模式以 `~/.config/skillshare/config.yaml` 为准。Amp 当前使用设置页面中的正文，不写入 `~/.config/amp`。

修改共同规则时检查三个宿主文件，保留输出目录、浏览器工具和 Orb 凭据等客户端差异。项目专属规则写在项目自己的 `AGENTS.md`；特定任务的操作说明写进对应 Skill，触发范围写进 `SKILL.md` 的 `description`。

## 同步

修改源文件前查看当前配置和同步状态，直接编辑这里的源文件：

```bash
skillshare extras list --json
```

修改后预览同步目标和本地冲突：

```bash
skillshare sync extras --dry-run
```

确认结果后同步配置中的 extras：

```bash
skillshare sync extras
```

Amp 的正文在设置页面中更新。历史决定见 [CHANGELOG.md](CHANGELOG.md)。
