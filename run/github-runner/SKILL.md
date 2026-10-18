---
name: github-runner
description: >-
  部署、迁移和排查 GitHub 组织级 self-hosted runner 时使用。
---

# GitHub Actions 自托管 Runner

本 Skill 管 GitHub.com 上 organization 级、以 systemd 服务常驻在 Linux 上的 runner。repository 级、enterprise 级和 ephemeral、JIT runner 的控制面不同，不能直接套这里的脚本。

官方资料：[self-hosted runner 文档](https://docs.github.com/en/actions/hosting-your-own-runners)、[REST API：self-hosted runners](https://docs.github.com/en/rest/actions/self-hosted-runners)、[actions/runner 源码和 release](https://github.com/actions/runner)。脚本参数看 `bash <dir>/scripts/setup-runners.sh --help` 和 `bash <dir>/scripts/remove-runners.sh --help`。

## 读哪份

| 要做的事 | 读 |
| --- | --- |
| 部署、删除 runner，或者脚本中途失败要收拾 | [references/deploy-and-remove.md](references/deploy-and-remove.md) |
| 同一 Linux 用户下的多个 runner 都跑 mise | [references/mise-isolation.md](references/mise-isolation.md) |
| 给宿主上的一组 runner 设总的 CPU、内存上限 | [references/shared-slice.md](references/shared-slice.md) |
| 把持久 runner 池放进专用 KVM VM，或者切换、下线旧池 | [references/vm-pool.md](references/vm-pool.md) |
| 持久 VM 里 job 失败，要判断该修 Runner 还是该修仓库；改 toolcache、Go 缓存或 BuildKit builder | [references/persistent-vm-baseline.md](references/persistent-vm-baseline.md) |
| 迁移 label 或宿主前盘点 workflow；定期巡查池的健康、容量和监控 | [references/operations-audit.md](references/operations-audit.md) |

## 部署和删除

部署和删除会改 GitHub 上的注册、systemd unit 和本地目录。几条硬规则：

- **token 只走文件。** 正常部署和删除只接受 `--token-file`；确认远端已注销后的 `--resume-after-unregister` 不接收 token。
- **drain 检查不能删。** GitHub 的 `config.sh` 运行期间 token 在它的 argv 里，同 UID 的进程还能读它的环境和内存。脚本因此要求 `--drained`，并在交出 token 前确认服务用户下没有任何进程。
- **只做全新部署。** 目标目录已存在就停，从不传 `--replace`。远端有同名 runner 时先在 GitHub 上处理。
- **批量操作不是原子的。** 失败后按 [deploy-and-remove.md 的恢复流程](references/deploy-and-remove.md#失败后从哪接着做)接着做，不要把缺目录或缺 `.runner` 当成功或失败的证据。

## 运行模型

每个实例有自己的目录 `~<USER>/actions-runner-<N>/` 和自己的 systemd 服务。目录按编号固定，所以一个 Linux 用户只能放一组编号池；第二个组织或前缀用另一个服务用户，或者另外设计目录布局。

drain 指停止给 runner 派新 job，并等到 GitHub 上 `busy=false`、本机没有 `Runner.Worker` 进程。

同一 Linux 用户不是隔离：同 UID 的 job 能读写彼此能访问的 `$HOME` 状态，也能改 runner 自己的文件。要防不可信的 job，用独立 VM 或独立宿主上的 ephemeral 或 JIT runner；拆目录不算安全边界。

部署完要三层都对上才算部署好：

- 本地实例目录和 `.runner` 里的身份；
- systemd unit 的 `User`、`FragmentPath`、`ExecStart` 和运行状态；
- GitHub 上的 runner 名字、online、busy、label 和 group。

只看 `.runner`、只看服务 active、只看网页上 online，都不够。

持久 VM 池里 job 失败，先分清是 Runner 的问题还是仓库的问题。系统能力、toolcache 布局和权限、Guest 里的 Docker、网络和持久 builder 归 Runner；语言版本、依赖声明、跨 job 传数据、端口分配和 workflow 自己的清理归仓库。服务用户不一定有免密 sudo，workflow 只读检查约定好的系统能力，缺了就报错退出，不在 job 里改 Guest。仓库没声明的依赖，不靠往 VM 全局装东西来补；Runner 的权限错了，也不让仓库去绕。细节见 [persistent-vm-baseline.md](references/persistent-vm-baseline.md)。

## 排查

```bash
systemctl list-units --type=service --all 'actions.runner*'
systemctl list-unit-files 'actions.runner*'
systemctl show <UNIT> -p User -p FragmentPath -p ExecStart -p ActiveState -p SubState -p MainPID
journalctl -u <UNIT> -n 100 --no-pager
tail -100 ~<USER>/actions-runner-<N>/_diag/Runner_*.log
```

| 现象 | 先查 | 怎么处理 |
| --- | --- | --- |
| runner offline | unit 是否 active、runner journal、GitHub 上的注册 | 修 unit 或重新注册，不先删目录 |
| job 一直排队 | online、busy、label、group 和 workflow 的 `runs-on` | 修真正对不上的那一处 |
| 有 `.runner` 但没有 unit | `.runner` 身份和 setup 失败在哪个编号 | 用 remove 对这个编号注销，不把 `.runner` 当部署成功 |
| mise 二进制被换掉、报 `Invalid cross-device link`，或 `mise` 突然不见 | 多个 job 是否共用一个 `MISE_DATA_DIR`，`TMPDIR` 和它是否在同一文件系统 | 见 [mise-isolation.md](references/mise-isolation.md) |
| `command -v` 能找到工具，job 却报 `No version is set for shim` | `PATH` 命中的是当前仓库没配置的 mise shim，还是真正的可执行文件 | 可选工具用 `tool --version` 探测后降级；必需工具在仓库配置里声明版本，不把宿主上碰巧留下的工具当 Runner 基线 |
| `setup-node` 建不了另一个版本的目录 | `_work/_tool/node` 父目录的 owner 和权限，以及固定版本目录 | 父目录保持 runner 所有、可写；只把装好的固定版本目录设成 root 所有、只读 |
| `setup-go` 恢复缓存报 `File exists`，或 post step 上传巨大的缓存包 | `GOMODCACHE`、`GOCACHE` 是否已被持久 Guest 共享保留 | 先用日志确认路径、冲突和包大小；确认后只关 Actions 的缓存，留着本地 Go 缓存 |
| `pnpm/action-setup` 报 `TAR_ENTRY_ERROR` 或 `spawn ETXTBSY` | 多个 runner 是否共用一个 Linux 用户和默认的 `~/setup-pnpm` | 在仓库 workflow 里固定 Action 版本，把 `dest` 指到 `${{ runner.temp }}/setup-pnpm`；不靠重跑，也不扩大 Guest 基线 |
| job 在用户步骤之前报 hook 不是有效脚本 | `ACTIONS_RUNNER_HOOK_JOB_STARTED/COMPLETED` 的路径、扩展名和 unit 实际生效的环境 | hook 文件名必须以 `.sh`、`.ps1` 或 `.js` 结尾；逐个 unit 读回 drop-in 和环境，用真实 job 验收，不能只直接跑脚本 |
| 同一台机器上 job 能读到 `/tmp` 里的文件，换个 runner 就丢 | workflow 是否把 Guest 共享目录当成跨 job 传数据的通道 | 修仓库 workflow，用固定版本的 artifact Action 或明确的外部存储；不给 Runner 加共享残留 |
| 改了 `Slice=` 但 cgroup 没变 | 当前 job、`MainPID`、`ControlGroup` | drain 后 restart；`daemon-reexec` 代替不了服务 restart |
| 磁盘满 | `_work`、toolcache、日志分别是谁写、谁读 | 只清确认没有 job 在用的内容 |
| timer active 但该做的事没做 | 上次成功时间、是否走了跳过分支、新鲜度、外部心跳 | 见 [operations-audit.md](references/operations-audit.md) |
| balloon 没扩容或缩错了 | Guest 探针、PSI、残留进程和容器、tmpfs | 探针失败不能当成功返回；见 [operations-audit.md](references/operations-audit.md) |

## 操作规则

- 不手改 GitHub 生成的主 unit，持久修改写 systemd drop-in。
- unit 实际名字以 `systemctl` 和实例目录的 `.service` 文件为准。runner 会把组织名里字母、数字和 `._-` 以外的字符换成 `-`；名字超过 150 个字符时会截断并加一个随机四位数后缀，不能从 runner 名直接拼出来。
- restart、remove 或清 `_work` 前，要同时确认 GitHub 上 `busy=false`、本机没有在跑的 job。没有可靠的 drain 手段就用维护窗口。
- 删 drop-in 后先 `daemon-reload`，再趁空闲 restart。只删磁盘上的文件，不会改变已在运行的进程的环境和 cgroup。
- 凭据不用普通 `Environment=` 长期存在 unit 里，用短期 token、systemd credentials，或只在任务期间存在的受限文件描述符。
- 审 Actions 原始日志时，以 GitHub annotation 和 step 退出码为准，不用裸 `grep 'error|deprecated'` 下结论。`run:` 脚本被回显出来的 `::error`、名字里带 `deprecated` 的依赖、checkout 的提示都会误报；先找到真正的 annotation、失败的 step 和命令退出码。
