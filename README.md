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

编辑 source 后同步到 target：

```bash
skillshare sync
```

更新上游 Skill 前先预览：

```bash
skillshare update --all --dry-run
skillshare update --all
skillshare sync
```

`sync` 是 source → target。要把 target 上的文件导回 source，使用：

```bash
skillshare collect
```

## Extras

修改 extras 前，先查看当前配置和同步状态：

```bash
skillshare extras list --json
skillshare sync extras --dry-run
```

source、target 和同步模式以当前 `config.yaml` 为准。不要直接编辑 target；如果 target 中已有本地改动，确认 dry-run 结果后再同步。
