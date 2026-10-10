# Skills

这个仓库保存个人 Skill 和 Skillshare extras。它可以作为普通 Git 仓库使用，也可以配置为 Skillshare source。

## 配置 Skillshare

在仓库根目录执行：

```bash
brew install skillshare

skillshare init \
  --source "$PWD" \
  --remote https://github.com/<owner>/<repo> \
  --all-targets \
  --mode merge \
  --subdir . \
  --no-skill
```

将 `<owner>/<repo>` 替换为本仓库的远程地址。使用交互式 TUI 时，去掉 `--all-targets` 和 `--no-skill`。

查看配置并预览同步：

```bash
skillshare status
skillshare sync --dry-run
```

确认无误后执行：

```bash
skillshare sync
```

## 日常流程

编辑 Skill source 后同步到 target：

```bash
skillshare sync
```

更新上游 Skill 前先预览：

```bash
skillshare update --all --dry-run
skillshare update --all
mise run update-lint-excludes
mise run lint
skillshare sync
```

`sync` 只将 Skills 从 source 同步到 target。要把 target 上的 Skill 导回 source，使用：

```bash
skillshare collect
```

## Extras

全局 Agent 指令的消费位置和同步步骤见 [extras/README.md](extras/README.md)。

## 检查

```bash
mise install
mise run lint
mise run test
```

CI 使用相同入口，执行 lint、Python 和 Node 测试，以及 Runner shell 测试。根目录的 Python 依赖只包含检查工具和测试需要的库；Python Skill 脚本需要的第三方运行依赖由各自的内联元数据声明。

第三方包的 lint 排除项由 `.metadata.json` 生成。增删或更新包后运行 `mise run update-lint-excludes`；lint 会检查生成块与元数据是否一致。各工具自己的格式规则仍在对应配置文件中维护。
