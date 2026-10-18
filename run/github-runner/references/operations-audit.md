# Runner 池的盘点和巡查

迁移宿主或 label 之前，以及定期巡查持久 runner 池时读这份。服务健康、workflow 路由、依赖完整和容量是四件事，任何一个绿灯都证明不了全部。

## workflow 和 label 盘点

从 GitHub 当前的组织 runner、runner group 和仓库 API 开始。然后读所有能触发 job 的活跃 ref 上的 workflow 源码。默认分支只是起点：还要包括受保护的发布或部署分支、reusable workflow、本地 composite action、动态 `runs-on`、matrix、组织和仓库变量，以及 workflow 输入。

GitHub 代码搜索只用来发现候选，不能当完整清单：

- 以前所有搜到过的候选路径原样保留，这次新搜到的并进去，作为本次盘点的全集。
- 代码搜索只覆盖默认分支，所以每个候选路径都通过 Contents API 从仓库当前默认分支读一遍；非默认的活跃 ref 按上一段另外读。搜不到不代表仓库里没有：只有读到当前内容，或得到明确的 `404`，才算关掉这个候选；其他错误留作未解决。
- 记下全集数量、读回数量、`404` 和出错的结果，以及每个没读回的候选。用集合运算算出来的数字代替不了逐个读回。

每个静态或动态的选择器，都要同时对照组织级 runner 和 group 清单、以及仓库级 runner 清单去解析。一个选择器可能只匹配某个仓库级 runner；只查组织级会把它误判成没人匹配，然后迁到错误的池。记下匹配到的是哪一级 runner；两级都查过之前，不把选择器判成无匹配。

能派到这个池的每个 job，记下：

- 组织、仓库、ref、workflow 路径和 job 名；
- 已解析和未解析的 `runs-on` 值；
- 触发事件、permissions，以及是否执行没审过的代码；
- reusable workflow 和 composite action 的调用链；
- job 用到的 custom label。

默认分支 YAML 里字面搜索结果为零，不足以删一个兼容 label。先解析动态选择器和活跃的非默认 ref。目标池用一个表达用途的 label；硬件或机房 label 只是临时兼容别名。

GitHub 能直接删组织 runner 的 custom label，不用重新注册：

```bash
gh api -X DELETE \
  "/orgs/<ORG>/actions/runners/<RUNNER_ID>/labels/<OLD_LABEL>"
```

删之前保存 runner 的 ID、名字和 label 集合，并证明旧 label 没有使用方。删之后重新做一遍 workflow 盘点和 runner label 查询。runner group 的可见范围和选中的 workflow、仓库访问是授权边界；label 只管路由。

把迁移的意图和清理条件就近写成 TODO。一个不熟悉的人要能看出：这个 label 是临时路由别名、为什么还留着、删除条件是什么——组织 workflow 盘点在所有活跃 ref 上解析和未解析的引用都为零，删完再做一次 workflow 和 runner label 盘点。有负责的 Issue 时附它的链接，不要求固定的标记格式。

## 依赖是否完整

在持久宿主上跑通的 workflow，可能依赖仓库之外的状态。把每个 job、reusable workflow 和 composite action 展开，给每个可执行文件、原生库、daemon、绝对路径、镜像、缓存和凭据来源分类。

改任何一层之前先归因：

- Runner 或 VM 的问题，来自它对外承诺的执行环境：系统包和库、内核和 cgroup 能力、网络和 CA 策略、Docker 是否可用、toolcache 布局和权限、服务生命周期、资源耗尽。修版本化的基线或池的控制面。
- workflow 或仓库的问题，来自 job 自己的约定：没声明的语言版本或依赖、跨 job 共用 `/tmp` 或工作区路径、并发下的固定端口、可变的 reusable workflow 引用、artifact 扇出，以及会改共享 builder 的清理。修 workflow、reusable workflow 或仓库声明。
- 缓存只是加速。热缓存能掩盖两类缺陷，但复制更多可变缓存状态不是修复。

一次事故可能两层都有。每条因果分开记；不要默认把 Runner 的权限缺陷变成仓库里的绕法，也不要默认把仓库没声明的依赖变成全局安装的包。持久 VM 的约定见 [persistent-vm-baseline.md](persistent-vm-baseline.md)。

- 语言工具放在仓库的工具声明和 lockfile 里，或用明确的 setup Action。
- 跨仓库都要的稳定系统能力，放进版本化的 runner 镜像基线。
- 通过 runner 的 `.path`、用户目录或可变的全局 home 找到的二进制，不算声明过的依赖。
- 预拉的镜像、宿主服务、可写缓存和以前 job 的残留，只要干净 runner 没有它们就跑不通，就算依赖。
- 网络、DNS、CA 信任、Action 和工具的下载源、架构、内核和 cgroup 特性、挂载和设备、用户和组以及 sudo 权限，虽然不是可执行文件，也是 runner 依赖。
- 共享缓存要有明确的完整性、加锁和保留约定。正确性不能依赖缓存命中。

静态盘点只产出候选，不是证明。挑有代表性的 job，在可丢弃的干净 runner 或测试环境里验证：全新 checkout，工作区、用户 home、语言和 Docker 缓存都为空，只用声明过的网络、CA、权限、设备和内核条件。另外留一份自然热缓存下的耗时样本。覆盖盘点出的每一类依赖，而不是随便挑一条绿的 workflow。保存 job 链接、runner 名、镜像或基线版本，以及提供每项依赖的命令或镜像配置。

## 宿主和 Guest 各管什么

专用 VM 池里，宿主管 libvirt 和 QEMU 生命周期、autostart、balloon 控制、网络规则和 Guest 不可达检测。它的外部通知路径不能依赖 Guest 活着。

Guest 管 runner unit、自己的 Docker 和容器运行时、工具链状态、文件系统容量、缓存策略和 Guest 内核证据。宿主上的健康探测仍要检查这些 Guest 信号，免得 Guest 死了连自己的告警也发不出来。

在用的控制面 key 和 known-hosts 放在固定的、只有 root 能读的运行时配置里。迁移证据和回滚目录不是存运行时凭据的地方。重建的 Guest 要把新的 SSH host key 固定进专用的 `UserKnownHostsFile`，并通过一次真实的管理探测，重建才算完成。

timer 只有在下面四条都成立时才算健康：

1. unit 已 enable 且 active；
2. 上一次调用真的做了该做的事，没有走一个返回成功的跳过分支；
3. 最近一次成功在约定的新鲜度窗口内；
4. 外部监控能报告调用缺失、宿主死掉或 Guest 死掉。

`OnFailure=` 只覆盖「跑了但失败」。timer 被禁用、静默 `exit 0`、宿主丢失或 timer 根本没触发，它都管不到。

GitHub runner 的生命周期 hook 按 Runner 控制面代码对待：

- `ACTIONS_RUNNER_HOOK_JOB_STARTED` 和 `ACTIONS_RUNNER_HOOK_JOB_COMPLETED` 指向的文件名必须以 `.sh`、`.ps1` 或 `.js` 结尾。runner 按扩展名选解释器，有 shebang、有可执行位都不算数。
- 先装好 hook 和每个 runner 的 drop-in，再启用任何 listener，然后逐个 unit 读回实际生效的环境。
- 启用 listener 之前先记下验收开始的时间戳，之后只认比它新的 hook 记录，免得一个马上被拒绝的 job 落在启动和取证之间。
- 直接执行 hook 只测得到它的清理逻辑。集成验收要有至少一个真实 job、一次比窗口标记新的 hook 尝试和成功，并且 Worker 日志里没有 hook 路径被拒的记录。

## 内存和存储

ballooned VM 两边都要看。宿主这边：libvirt 当前和最大内存、QEMU RSS、宿主 `MemAvailable`、swap 和 PSI。Guest 这边：`MemAvailable`、PSI、swap、内核 OOM 记录、runner slice 的 `memory.events`、残留的进程和容器、tmpfs 用量。

balloon 控制器不能把探不到的 Guest 或格式不对的探测结果当成功。扩容可以快；缩容要先安静一段时间，并证明 runner worker、子进程、容器、内存压力和 tmpfs 用量都容得下目标值。Guest 的 `/tmp` 上限要放得进空闲目标，或者改用磁盘上的路径；每个 runner 的 `TMPDIR` 管不到写死 `/tmp` 的 job。

文件系统的字节数、inode 和增长速度，按写入方逐个跟踪：

- runner 的 `_work` 和 `_diag`；
- 每个 runner 的临时目录和 mise 状态；
- 包管理器和编译器在共享 home 里的缓存；
- Docker 镜像、层、BuildKit 状态、容器和卷；
- journal 和崩溃、core 数据。

清理要有高水位策略、每个写入方各自的保留期、报告释放了多少字节，以及遇到忙碌跳过后的重试或告警。删 job 用的路径之前，要求 GitHub 上 `busy=false`、本机没有 worker，并在清理期间不让新 job 进来。只要有 job 在忙就直接返回成功的每周 timer，算不上清理保障。

Guest 内核 OOM、文件系统或 I/O 错误、反复出现的 overlayfs warning，在查清原因之前都算验收失败。不要单凭 warning 就认定是存储驱动的问题；先用已安装的内核和运行时，加上相关的 workflow 复现，再考虑换后端或删运行时状态。

容量、内核事件和故障三类信号分开：

- Guest 磁盘超过高水位是容量问题，要清理或扩容；它不证明 job 或服务挂了。
- 某一轮出现一次 overlayfs 增量，是真实的内核事件；但 runner、运行时和 systemd 检查都还是绿的、下一轮样本也恢复了，就不是故障。保留原始 warning，归到相关的 workflow 或 builder 生命周期。
- 运行时检查失败、warning 反复出现，或同时有文件系统、I/O 证据时，升级为不健康。不为了让监控变绿而压掉事件。

容量还包括需求和吞吐：从排队到开始的时间、busy 和并发饱和度、CPU 使用率、PSI 和 steal、代表性 job 的耗时回退、磁盘 I/O 和网络吞吐。这些信号和内存、存储的门槛都在约定的服务目标内，才加并发。

## 清理引用的复查

每次迁移前检查、定期巡查和下线时，在相关仓库和运行时配置里用 `rg` 搜负责的 Issue 链接或编号、旧 label，以及附近的 TODO、FIXME。每条匹配都只是候选，不代表到了该清理的时候。

给每个候选分类前，先读本地留下的意图、关联的 Issue 和当前的 workflow 盘点。只做本次任务范围内的清理，其余的连同证据位置一起报告。动态的调查过程不要复制进多份各自维护的文档。

## 交给仓库负责人的材料

交接写事实，不写一句笼统的「修一下 CI」：

- 具体的仓库、workflow、job 和活跃 ref；
- 当前和目标的 `runs-on` 解析结果；
- 没声明的依赖，以及用到它的命令；
- 该在哪里声明：仓库、reusable workflow 还是 runner 镜像；
- 需要的干净 runner 场景和验收信号；
- 明确不做的事：不改 label 或 group、不写 workflow、不重跑。

这次盘点的组织清单存一份，带时间点，之后不改。给仓库负责人的任务另外列，不在原始清单上直接改。
