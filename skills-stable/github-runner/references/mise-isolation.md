# 每个 runner 一套 mise 目录

同一 Linux 用户下有多个 runner 服务，workflow 里用 `jdx/mise-action` 或直接跑 mise 时读这份。

## 共用目录会出什么事

以下按 `jdx/mise-action` v5.1.1 的源码（`src/index.ts`）。workflow 用的是更旧的大版本时先升级；换了版本要回到那个版本的源码重新核对。

- mise 二进制放在 `miseDir()/bin`。`miseDir()` 依次取 action 输入 `mise_dir`、`MISE_DATA_DIR`、`XDG_DATA_HOME/mise`，最后是 `~/.local/share/mise`。
- 已有的二进制和 workflow 要求的版本校验对不上时，action 先删掉它再装新的。几个 job 共用一个 data 目录、要的版本又不同，就会互相删、互相覆盖对方正在用的 `mise`。
- 下载先放进 `os.tmpdir()` 下每个 job 独有的临时目录，再挪进 `bin`。默认下载 release 压缩包解开，用 `mv` 命令挪，跨文件系统时是复制，不是原子替换。少数情况（如 `fetch_from_github: false` 从 CDN 取最新版）下载的是裸二进制，用 `rename` 挪，`TMPDIR` 和 data 目录不在同一个文件系统就报 `EXDEV`（`Invalid cross-device link`）；具体哪些输入组合会走这条路，看 `setupMise()` 里的 `installFromUrl`。

所以每个 runner 要有自己的一套 data、cache、state、config 目录和 `TMPDIR`，`TMPDIR` 和 data 目录放在同一个文件系统上。`cache: false`、`install: false`、重试，或只设 `MISE_TMP_DIR` 都解决不了共用 data 目录的问题。

日志里出现 `Invalid cross-device link` 只能说明有一次 rename 跨了挂载点。要说是哪条路径，日志里得有源和目标路径。

## 持久配置

`<HOME>` 用 `getent passwd <USER>` 取。unit 的实际名字从实例目录的 `.service` 读，再用 `systemctl show` 核对。`%N` 展开成完整 unit 名，每个实例自然拿到不同路径。

```ini
# /etc/systemd/system/actions.runner.<ORG>.<PREFIX>-.service.d/95-mise-isolation.conf
[Service]
Environment="MISE_DATA_DIR=<HOME>/.local/share/mise-runners/%N/data"
Environment="MISE_CACHE_DIR=<HOME>/.cache/mise-runners/%N"
Environment="MISE_STATE_DIR=<HOME>/.local/state/mise-runners/%N"
Environment="MISE_CONFIG_DIR=<HOME>/.config/mise-runners/%N"
Environment="TMPDIR=<HOME>/.cache/mise-runners/%N/tmp"
Environment="MISE_TMP_DIR=<HOME>/.cache/mise-runners/%N/tmp"
ExecStartPre=/usr/bin/mkdir -p <HOME>/.local/share/mise-runners/%N/data <HOME>/.cache/mise-runners/%N/tmp <HOME>/.local/state/mise-runners/%N <HOME>/.config/mise-runners/%N
```

`<HOME>/.cache` 和 `<HOME>/.local/share` 不在同一个文件系统时，把 `TMPDIR` 挪到 data 目录所在的文件系统上。

带 `-` 的前缀 drop-in 目录要先用 `systemctl cat <UNIT>` 确认本机 systemd 真的加载了它；没加载就给每个实际 unit 各放一份相同的 drop-in。不按 systemd 版本号去猜。

每个 runner 的全局 config 目录默认留空，只放 CI 真正需要的设置。仓库用的工具写在仓库的 `mise.toml` 和 lockfile 里。把人用的全局 `[tools]` 配置复制给每个 runner，会让 `mise install --locked` 拿仓库的 lock 去解析无关工具，还可能借 `ExecStartPre` 在每次重启时把它们装回来。

现有的全局配置里还有 settings、env、tasks、`conf.d`、按环境区分的配置或 lockfile 时，先把整套配置都列出来，只把 CI 需要的、不含密钥的设置挪进专用的 CI 配置，不复制凭据。

这套配置只隔离 mise 和 `TMPDIR`。uv、Go、Yarn、npm、Cargo、prek 这些包管理器和编译器还可能写共用的 `HOME` 缓存。每个都要决定：每个 runner 一份，还是共用一份并有加锁、完整性和保留策略；共用的都要算进容量巡查。

## 上线和回滚

1. 在 workflow 里搜 `with.mise_dir` 和覆盖这些环境变量的地方。
2. 建好四个父目录，owner 要让服务用户能在里面建 `%N` 子目录。
3. 装 drop-in，跑 `systemd-analyze verify <UNIT>`。目标 unit 有 warning 就算失败，即使退出码是 0。
4. `systemctl daemon-reload`。
5. drain。先重启一个实例，确认它回到 online 且环境是新的，再逐个滚完整个池。

回滚：删 drop-in、`daemon-reload`、趁空闲重启。没重启的进程保持旧环境。回到共用目录又会出现竞争，回滚只留到服务恢复为止。

## 验收

逐个实例对比配置和运行中的进程：

```bash
systemctl show <UNIT> -p Environment -p MainPID
tr '\0' '\n' </proc/<MAIN_PID>/environ | \
  rg '^(MISE_(DATA|CACHE|STATE|CONFIG|TMP)_DIR|TMPDIR)='
```

每个服务的 `MISE_DATA_DIR` 和 `TMPDIR` 都必须唯一。在不同 runner 上同时跑两个冷启动的 job，记下 runner 名、unit 名、job 链接、临时路径和二进制目标路径；再跑一次要求不同 mise 版本的 job。两次都要成功，且没有共用路径、没有 `EXDEV`。

`mise config ls` 只证明配置看得见。完整的检查要跑 workflow 真正用的 `mise install --locked` 和它后面的检查。`install_args` 故意只装一部分工具时，`mise ls` 会把仓库里没用到的工具列为 missing，按 workflow 的约定判断，不要求整体 missing 为空。
