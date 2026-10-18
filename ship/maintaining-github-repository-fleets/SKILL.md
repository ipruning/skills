---
name: maintaining-github-repository-fleets
description: 在一个 GitHub 用户或组织的大量仓库上批量扫描代码、批量改动开 PR、合并并回查结果，或派多个子 Agent 分仓处理时使用。
---

# 维护 GitHub 仓库群

几十上百个仓库一起改，成败在于每个仓的差异有没有被照顾到，以及中途出错能不能看清停在哪。先在一个仓走完全程，再铺开。

## 选账号

本机常登录多个 gh 账号，active 账号不一定对得上要操作的组织。每条命令按组织显式注入，不依赖也不切换全局 active：

```bash
GH_TOKEN="$(gh auth token --user <login>)" gh pr list --repo <org>/<repo>
GH_TOKEN="$(gh auth token --user <login>)" \
  git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push origin HEAD
```

普通 `git push` 走的是 Git 自己的凭据链，和 gh 当前 active 账号无关。某个组织的目录下长期用同一账号时，可以在该目录的 `mise.toml` 里固定：

```toml
[env]
GH_TOKEN = "{{ exec(command='gh auth token --user <login>') }}"
```

token 只经环境变量或文件传递，不写进命令行参数（`ps` 和 Agent 的命令日志都看得到）、日志或提交内容。

## 扫代码

跨组织找某段代码，不要用 GitHub code search：API 大约每分钟 10 次，只索引默认分支，还会丢掉 `$`、`{` 等符号，查 `${{ secrets.X }}` 这类模式基本不可靠。把全组织浅克隆到本地再 `rg`：

```bash
bash <skill_dir>/scripts/clone-org.sh <owner> ~/fleet/<owner> --user <login>
cd ~/fleet/<owner>
rg --hidden -g '!.git/' -n '<pattern>'
rg --hidden -g '!.git/' -l '<pattern>' | cut -d/ -f1 | sort -u   # 命中的仓库
```

- `rg` 默认跳过隐藏目录，不加 `--hidden` 就扫不到 `.github/workflows`。
- 脚本只取默认分支最新一次提交，跳过空仓库和已归档仓库（`--include-archived` 可以带上）。再跑一次就是增量更新。
- 镜像目录是缓存，每次更新都会 `reset --hard` 和 `clean`，不要在里面改代码。脚本靠 `.fleet-mirror` 标记拒绝写入开发目录。
- 输出里的 `stale` 是镜像里有、远端列表里已经没有的目录（改名、删除、归档），需要时手动删。

## 批量改动和开 PR

- 每个仓库单独一个工作树或新克隆，不在镜像里改。工作目录、分支名和 PR 链接记到一张表里（文件），中断后照表续。
- 每个仓先读它自己的 `AGENTS.md`、`CLAUDE.md`、`CONTRIBUTING`：分支前缀、commit 格式、必需的 trailer、检查命令各仓不同，不要套用第一个仓的写法。
- 每仓 commit 前跑 `git config --show-origin user.email`。`includeIf` 按目录切换身份，换个父目录身份就可能变。
- 同一处改动在一个仓里每次只开一个 PR，不基于另一个未合并的 PR 分支叠 PR。

## 合并和回查

每个 PR 合并前单独看：

```bash
gh pr view <n> --repo <org>/<repo> --json mergeStateStatus,statusCheckRollup,reviewDecision
```

`mergeStateStatus` 为 `BEHIND` 说明分支保护要求先跟上 base（strict），用 `gh pr update-branch`，然后等 CI 重新跑完。未解决的评审线程不在这个 JSON 里，要查 GraphQL 的 `reviewThreads { isResolved }`。

合并到默认分支可能触发发布或部署。合并前在镜像里找出带这类 workflow 的仓，逐个看它们的 `on:` 触发条件：

```bash
rg --hidden -g '!.git/' -l -e 'release' -e 'deploy' */.github/workflows
```

合并后回查各仓默认分支上的 CI（`gh run list --repo <org>/<repo> --branch <default> --limit 3`），PR 上绿不代表合并后的提交也绿。

## 派子 Agent 分仓并行

- 每个子 Agent 分到互不重叠的仓库，并各用一个独立临时目录。共用目录时，一个 Agent 写的脚本会被另一个覆盖，结果分支名都对不上。
- 分支名、commit 格式由派发方在提示里定死，不让各 Agent 自己起。
- 提示里写清楚允许哪些外部写入（例如推自己的分支、开 PR、回复评审），合并留给派发方做。
- 要求子 Agent 把最终报告写到自己目录下的文件，在最后一条消息里给出路径，只在完成或被卡住时汇报。只放在消息里的报告会丢。
