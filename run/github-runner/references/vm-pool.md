# 专用 KVM VM 里的 runner 池

一台大裸金属宿主要常驻一池 runner，又不能让 CI 碰到宿主上的生产环境时，用一个专用 KVM VM 装这池 runner，或者要切换、下线旧池时读这份。

VM 是 CI 和宿主之间的隔离边界，也是整池的资源上限。VM 里的多个持久 runner 之间仍互相信任：共用 UID、可写缓存和 Docker daemon，job 之间没有隔离。

## 宿主这边先就绪

KVM、libvirt daemon、`qemu:///system`、固件、VM 网络和存储、资源设置、autostart、宿主和 Guest 的重启验收，都归 `$linux-server`。先按它把 VM 做到能冷启动、网络和资源上限都对，再用这份。重建 runner 的脚本包里也不复制通用的 libvirt 做法，指向那个 Skill。

在此之上，CI 还要求：

- 不把宿主的 Docker socket、生产目录、SSH key、备份 key 或生产环境变量文件传进 VM。
- VM 用自己的 libvirt 网络，出口收窄。明确拦住 VM 到宿主管理地址、生产网桥和内网的新连接，只放行 CI 真正需要的服务。
- 资源上限只设一层。VM 的 vCPU 和内存就是池的上限时，Guest 里的 `ci-runners.slice` 只记账（见 [shared-slice.md](shared-slice.md)）；每个 runner 一个硬上限或在 Guest 里再设一层，只会让共享突发更差，不增加隔离。

光看 libvirt 配置不能说已经和生产隔离。从 Guest 里实测：访问公网 GitHub 成功，到每个受保护的宿主、管理和生产地址的新连接都失败。

## 注册和服务

能直接用 `scripts/setup-runners.sh` 就用它；VM 重建脚本自己实现注册时，要守住同样的规矩：

- 从官方 release 元数据拿包，核对发布的 SHA-256，部署到全新目录。不用 `--replace` 当修复手段。
- token 只从 `0600` 文件读，不通过 `sudo` 调 `config.sh`（sudo 会把带 `--token` 的命令行写进日志），用空环境的 `runuser` 交给服务用户，保留同用户 drain 检查。原因和细节见 [deploy-and-remove.md](deploy-and-remove.md#token-怎么交给-runner)。
- 在 runner 目录里运行 `config.sh`。几个 runner 脚本按当前目录找文件，给绝对路径也一样。运行时 `PATH` 和调用 `runuser` 用的干净 `PATH` 分开：`env.sh` 会把注册时的 `PATH` 写进 `.path`，之后服务和 job 都以它为基础。
- `svc.sh install` 之后，读出实际装上的 unit 名放进数组，再把数组传给 `systemctl`。`systemctl` 不会把加了引号的通配符展开成已安装的 unit 名。
- 每个 runner 一套 mise data、cache、state、config 和临时目录，包括标准的 `TMPDIR`（见 [mise-isolation.md](mise-isolation.md)）。别的 `HOME` 缓存另外盘点，mise 隔离管不到 uv、Go、Yarn、npm、Cargo 和 prek。
- `KillMode=control-group` 只和 drain 流程一起用，它改变了停服务时怎么处理在跑的 job 子进程。

目标池用一个表达用途的 label。兼容用的 label 是临时别名，不是身份。先按 [operations-audit.md](operations-audit.md) 盘点所有活跃 ref 上字面和动态的使用方，再就近写清理条件（TODO）。GitHub 的组织 runner label API 能删 custom label，不用重新注册。

## drain 和切换

在 runner group 或仓库这一层停止调度，收不回已经派给某个 runner 的 job。两边都要 drain：

1. 停止给旧池分配新的仓库或 workflow 路由。
2. 观察 GitHub 上的 `busy` 和本机的 `Runner.Worker` 进程。
3. 空闲的 unit 立刻停，免得它再接一个已派来的 job。
4. 忙的等跑完，再逐个停。
5. 旧池保持停用，留一个写明日期的回滚窗口；到期后注销并删除。

## 清理宿主的风险

CI 搬走不等于可以在生产 Docker 宿主上清理软件包。尤其不能用 `apt-get --simulate` 判断一个 `rc` 状态的包可以放心 purge：模拟不执行维护脚本，而这些脚本的作用可能超出包剩下的配置文件。Debian 系的 `docker.io` 包在 purge 时可能执行 remove 阶段留下的 `nuke-graph-directory.sh`，删掉整个 `/var/lib/docker`，即使现在跑 daemon 的是 Docker CE。Debian 12、13 里的包无条件执行，unstable 里较新的包只在 debconf 的 `docker.io/purge-data` 为 true 时执行。以本机已安装的脚本为准。

在线上宿主 purge 旧的容器运行时包之前：

1. 找出所有曾经拥有同一个 daemon、socket、配置和数据目录的包。
2. 读 `/var/lib/dpkg/info/<package>.*` 下已安装的脚本和 trigger，递归看它们 source 或执行的每个 helper、systemd hook 和对数据目录的操作。只看四个顶层维护脚本不够。对应版本的包文件可以佐证，不能代替线上已安装的脚本。
3. 确认数据根目录和可靠的备份恢复路径。`live-restore` 只让 daemon 停掉时已有进程继续跑，保护不了被删掉的镜像、容器、网络和卷的元数据。
4. 把 Docker 包清理当作有恢复演练的生产维护，不当作删 runner 时顺手清理配置文件。

运行时元数据已经坏了时，冻结运行时这一层。在可靠的清单、应用数据、密钥、恢复材料和恢复步骤都齐全，并且维护负责人接受停机之前，不重启或 reload Docker 和 containerd，不重启宿主，不动容器运行时的包，不做破坏性修复。daemon API 还能读时把清单留下来，保留 `/run/containerd/` 下的 OCI runtime 配置、进程环境和应用自己的状态。路由还通只说明已有进程还在服务；健康检查失败或无法在容器里 exec 新进程，说明宿主已经降级。

恢复完成不只是「容器能回 HTTP」。逐个重建并验证每个负载、健康检查、持久数据路径、网络、重启策略、cgroup 位置和公网路由。然后撤掉临时的运行时保护，恢复服务和 socket 原本的 enable 状态以及 daemon 重启策略，解除包的 hold，重新打开暂停的状态检查和健康检查 timer，并证明一次安全重启或等效的持久化检查。这些收尾动作写进同一条由运行时负责人维护的 TODO。

## 控制器、timer 和重建脚本包

宿主负责 VM 可达性、libvirt 和 QEMU 状态、网络规则和 balloon 控制；Guest 负责 runner、Docker、工作区和缓存。健康检查要有一条在宿主上或宿主之外的外部通知路径，Guest 死了不能让它自己的告警也没声。timer 是否健康看四条，见 [operations-audit.md](operations-audit.md#宿主和-guest-各管什么)。

balloon 控制器的失败和缩容条件、SSH key 和 known-hosts 放在哪，见 [operations-audit.md](operations-audit.md)。

VM 重建脚本包按受管配置对待。它的注册环境、token 边界、运行时 `PATH`、label 集合、unit 和 drop-in 校验、基线软件包清单和干净 runner 测试，要和本 Skill 保持一致，或直接调用本 Skill 的脚本。下载的引导工具固定版本并核对 digest；没有版本号的安装脚本 URL 重建不出同样的结果。

## 验收

下面全部成立，池才算就绪：

- GitHub 上在线的 runner 数量、名字、label 和 group 都和预期一致。
- 每个 runner 服务都 enabled 且 active，每个实例的状态目录和临时目录都唯一。
- Docker 和需要的工具链在真实 job 里能用。
- Guest 里的网络探测证明公网放行、宿主和生产地址被拦。
- VM 重启后网络、防火墙和全部 runner unit 不用人工干预就能恢复。
- 删兼容 label 之前，组织的 workflow 盘点已经解析了新旧 label 的每个使用方、动态 `runs-on`、reusable workflow 和活跃的部署 ref。
- 干净 runner 上的 job 覆盖了盘点出的每一类依赖和预期的并发，不只是服务健康或一条顺手的 workflow。
- 宿主和 Guest 的监控能证明：timer 新鲜度、外部通知、内存、PSI、OOM、文件系统字节数和 inode，以及每个缓存和工作区的写入方。
- 在有代表性的并发负载下，Guest 内核日志里没有说不清原因的 OOM、文件系统或 I/O 错误，也没有反复出现的 overlayfs warning。

持久 runner 干不干净是另一件事。重建 VM 能清掉以前的残留，但之后不可信的 PR job 仍能把东西留给同一 VM 里后面的 job。job 之间不能互信时，把不可信代码派给 ephemeral 或单独重建的 worker。
