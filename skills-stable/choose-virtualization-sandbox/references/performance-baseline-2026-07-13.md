# Performance baseline, 2026-07-13

这份 baseline 是一次硬件与版本组合下的历史观察，用于形成选型假设，不是跨版本承诺或容量依据。原始 logs 留在当次实验工作区，没有随 Skill 分发；这里的聚合数字不能独立复算。采购、并发上限或当前性能结论必须重新基准。当前 CLI、release-tagged 官方文档或实测与本文冲突时，以当前证据为准。

## Test environment

- Host: Apple M5 Pro, 18 cores, 48 GB RAM, macOS 26.5.2.
- Apple Container 1.1.0.
- OrbStack 2.2.1, Docker 29.4.0, Docker context `orbstack`.
- Tart 2.32.1.
- exe.dev benchmark VM: 2 vCPU, 8 GiB RAM, 20 GB root filesystem, AMD EPYC 9554P, KVM x86_64, default `boldsoftware/exeuntu` image.

本地临时资源使用唯一 `codex-bench-*` 名称并在实验后删除。Tart 只从维护中的 base 创建临时 CoW clone，没有修改 base 或已有 VM。exe.dev 的两台 benchmark VM 已删除，账号恢复到实验前的 VM 数量。

## Lifecycle latency

| Operation | Mean or range |
| --- | ---: |
| Apple Container: create and exit cached Alpine | 767 ms |
| OrbStack Docker: create and exit cached Alpine | 185 ms |
| Apple Container: `exec true` | 51.8 ms |
| OrbStack Docker: `exec true` | 31.6 ms |
| OrbStack machine: first Alpine create | 11.1 s |
| OrbStack machine: stopped start and exec | 90.5 ms |
| OrbStack machine: running exec | 18.5 ms |
| Tart: APFS CoW clone of local 31 GB macOS VM | 0.05 s |
| Tart: macOS cold boot to SSH ready | 7.1–11.0 s |
| exe.dev: create default exeuntu VM | 19.2 s |
| exe.dev: create return to direct SSH ready | 1.46 s |
| exe.dev: copy about 4.2 GB guest filesystem | 20.4 s |
| exe.dev: copy return to SSH ready | 7.53 s |
| exe.dev: restart to SSH ready | 25.4 s |
| exe.dev: delete VM | 12.8–16.4 s |

OrbStack 的短命 Docker workload 约快 4.1 倍，因为它复用已运行的 VM 和 kernel。这个差异不是 Linux 代码的 CPU 差异。

## CPU and compilation

| Workload | Result |
| --- | ---: |
| Apple Container: 2 GiB SHA-256 | 6.40 s |
| OrbStack Docker: 2 GiB SHA-256 | 6.54 s |
| OrbStack machine: 2 GiB SHA-256 | 6.39 s |
| Tart macOS guest OpenSSL SHA-256 | guest 比 host 慢约 4%–8% |
| Local M5 Pro: Go crypto cold compile, 2 threads | 13.7–17.3 s, mean 15.1 s |
| exe.dev EPYC: same compile, 2 vCPU | 36.3–45.0 s, mean 39.4 s |

本地三种 Linux 方案的纯 CPU 没有实质差距。exe.dev 的这项真实编译约比本机同线程限制慢 2.6 倍，适合后台、集成和网络任务，不适合追求最短编辑—编译反馈。

## Filesystem

### 10,000 empty files: create, traverse, verify, delete

| Runtime | Internal filesystem | macOS shared filesystem | shared/internal |
| --- | ---: | ---: | ---: |
| Apple Container | 392 ms | 3.36 s | 8.6x |
| OrbStack Docker | 157 ms | 1.66 s | 10.6x |
| OrbStack machine | 61.7 ms | 1.65 s | 26.7x |
| Tart macOS VM | 1.26 s | 13.35 s | 10.6x |
| exe.dev ext4 | 270–310 ms | n/a | n/a |

shared mount 的 metadata workload 明显更慢。`node_modules`、`.venv`、Git checkout、Rust/Go cache 和 build output 应留在 guest 内部盘。

### 1 GiB synchronized sequential write

| Runtime | Time |
| --- | ---: |
| Apple Container internal | 0.50–0.60 s |
| OrbStack Docker internal | 0.46–0.93 s |
| Apple Container shared | 0.65–0.75 s |
| OrbStack shared | 0.36–0.51 s |
| Tart macOS internal | 0.27–0.54 s |
| exe.dev ext4 | 5.44–7.04 s, about 146–188 MB/s |

本地数字受 APFS cache 影响。稳定结论只有：本地 NVMe 路径明显快于这台 exe.dev VM；远程盘足够普通构建和服务，不是高吞吐 scratch disk。

## Memory density

Apple Container 无 container 时的 service RSS 约为 32 MiB。它与下面的 `phys_footprint` 不是同一指标，不参与交叉点比较。

| Runtime | Idle workloads | Scope | Approximate `phys_footprint` |
| --- | ---: | --- | ---: |
| Apple Container | 1 | VM XPC and runtime | 276 MiB |
| Apple Container | 4 | VM XPC and runtime | 1,108 MiB |
| Apple Container | 8 | VM XPC and runtime | 2,215 MiB |
| OrbStack | baseline | shared Helper | 982 MiB |
| OrbStack | 1 container | shared Helper | 1,217 MiB |
| OrbStack | 4 containers | shared Helper | 1,254 MiB |
| OrbStack | 8 containers | shared Helper | 1,291 MiB |
| Tart macOS VM | one VM configured for 8 GB | VM process | 8.21 GB |

4 个 idle workload 时 Apple 低于 OrbStack，8 个时 OrbStack 明显更低；交叉点位于这两个已测并发量之间，实验没有测出精确位置。Apple 官方文档说明当前 VM 内释放的 memory page 不会返还给 macOS；memory-intensive container 停止或重启后才会降低 host memory。[Apple Container technical overview](https://github.com/apple/container/blob/main/docs/technical-overview.md#releasing-container-memory-to-macos)

## exe.dev control plane and capabilities

| Path | Mean `true` latency |
| --- | ---: |
| Direct `<vm>.exe.xyz` SSH | 1.36 s |
| Lobby `ssh exe.dev ssh <vm> true` | 1.93 s |
| Direct SSH with ControlMaster | 1.32 s |

ControlMaster 已确认命中 master connection，但没有显著改善延迟。让 Agent 进入 VM 后完成整段任务，不从本机逐条远程调度。

该 VM 的 Docker 和 cgroup v2 可用，`/dev/kvm` 不存在。cached Alpine short-lived container 为 0.22–0.65 s。它适合 Docker/Compose，不适合 nested KVM。

默认 image 的预装工具集合会变。实际使用前在 guest 内发现所需命令；不要从这次实验推断当前 image 包含某个 Agent、language runtime 或 task runner。

价格、plan 配额、region、disk usage 和 data transfer 是易腐事实，本 baseline 不把当时账号数值作为当前容量依据。通过 exe.dev 当前控制面和 billing usage 查询。

## Recorded blocker: Apple `container machine`

Apple Container 1.1.0 在上述 M5 Pro/macOS 26.5.2 环境能以 Alpine 3.22 成功创建 machine，但第一次真实命令稳定失败：

```text
Error: The operation couldn’t be completed. Operation not supported by device
```

boot log 证明 kernel、`vminitd`、data disk 和目标 process 已启动。现有证据不能把故障唯一归因到 Alpine、M5、macOS 或 CLI。普通 Apple `container run` 不受影响。重新启用 machine 路径的判据是当前环境真实 `machine run` 成功，不是 machine create 或普通 container 成功。

## Evidence boundary and method

- Lifecycle 使用 cached image，多轮测量；首次 image pull 和 VM initialization 分开记录。表中未标样本数的聚合值只能作为方向性观察。
- CPU 使用相同 Alpine 与 2 GiB SHA-256 pipeline；Tart 比较相同 macOS host/guest 的 OpenSSL。
- Go compile 使用相同 Go 版本、`GOMAXPROCS=2`、fresh `GOCACHE` 和相同 package set。
- Filesystem 统一创建、遍历、验证并删除 10,000 个空文件。
- Memory 的 workload 行使用 macOS `footprint` 的 `phys_footprint`；Apple 统计 VM XPC 与 runtime，OrbStack 统计共享 Helper。Apple service-only baseline 使用 RSS，已从交叉点比较中分离。
- exe.dev guest workload 在单条 SSH session 内测量，避免把 control-plane latency 混入 CPU 和 disk 结果。

## Primary sources

- [Apple Container technical overview](https://github.com/apple/container/blob/main/docs/technical-overview.md)
- [Apple Container how-to](https://github.com/apple/container/blob/main/docs/how-to.md)
- [OrbStack architecture](https://docs.orbstack.dev/architecture)
- [OrbStack Docker compatibility](https://docs.orbstack.dev/docker/)
- [OrbStack Linux machines](https://docs.orbstack.dev/machines/)
- [Tart quick start](https://tart.run/quick-start/)
- [Tart FAQ](https://tart.run/faq/)
- [Tart Guest Agent and `tart exec`](https://tart.run/blog/2025/06/01/bridging-the-gaps-with-the-tart-guest-agent/)
- [exe.dev documentation](https://exe.dev/docs/all)
- [Apple Software License Agreements](https://www.apple.com/legal/sla/)
