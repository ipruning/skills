---
name: choose-virtualization-sandbox
description: >-
  Choose or compare a disposable development and test sandbox among Apple
  Container, OrbStack Docker or Linux machines, Tart macOS or Linux VMs, and
  exe.dev. Use when the runtime is not yet decided, when isolation, Docker
  compatibility, persistence, host files, nested virtualization, location, or
  performance determines the choice, or when preparing an Apple Container,
  OrbStack, or Tart sandbox for an AI agent. Once exe.dev is selected, its VM
  lifecycle, SSH, networking, and cleanup belong to exe-dot-dev. Not for
  ordinary Docker commands in an already-chosen runtime, general Linux server
  administration, or product-specific deployment on exe.dev.
---

# Choose Virtualization Sandbox

把「给 AI 开个环境」翻译成可审计的运行时与执行边界。选型或比较本身是只读工作；只有用户明确要求运行或测试时，才创建或改变资源。

## 相邻职责

- exe.dev 已经选定后，加载 `$exe-dot-dev` 处理 VM 生命周期、SSH、HTTPS、域名、磁盘、sharing、integration 和账单。
- 目标 Linux 主机已经确定后，加载 `$operate-linux-servers` 做系统运维或安全审计。
- Convex 与 Pigsty 在 exe.dev 上的部署分别交给 `$convex-on-exe-dev` 与 `$pigsty-on-exe-dev`。其余 exe.dev 应用与 VM 操作归 `$exe-dot-dev`。
- Docker runtime 已经确定后的 Compose、镜像或容器调试，不再由本 Skill 选型。

## 提取需求

先提取决定运行时的约束：

```yaml
os: linux | macos
trust: trusted | unknown | hostile
docker_api: required | optional | forbidden
persistence: one-shot | task | long-lived
nested_virtualization: required | forbidden
location: local | remote | either
```

`unknown` 表示代码或依赖尚未审查，不能假定可信；`hostile` 表示任务主动测试恶意或对抗性代码。二者都不能因「只是临时任务」降为 `trusted`。

再提取选定运行时后的执行 policy：

```yaml
host_files: none | read-only | read-write
internet_access: forbidden | required
host_network: forbidden | required
ingress: none | private-service | public-service
cleanup: always | retain-on-failure
```

没有证据时按 `trust=unknown`、`host_files=none`、`host_network=forbidden`、`ingress=none` 处理。`internet_access` 从真实任务判断；下载依赖需要 internet access，不代表 workload 可以访问宿主网络或读取宿主文件。`cleanup=always` 只适用于本次创建且名称唯一的资源。缺失项会改变 OS、信任边界、数据位置、公开入口或破坏性操作时才询问。

## 约束交集

先淘汰不满足硬约束的候选，再在剩余候选中选择：

1. `os=macos` 淘汰 Apple Container、OrbStack 和 exe.dev，只保留 Tart macOS。`location=remote` 还要求远程 Tart-capable Mac；没有就无解。
2. `location=remote && os=linux` 淘汰本机 runtime，只保留 exe.dev。`nested_virtualization=required` 时还必须现场验证 `/dev/kvm`；当前 VM 不具备就无解。
3. `location=local` 淘汰 exe.dev。
4. `trust=hostile` 淘汰 OrbStack Docker 和 OrbStack machine。它们的 shared kernel 不是 actively malicious code 的 full-VM boundary。
5. `nested_virtualization=required` 淘汰普通 OrbStack 与未暴露 `/dev/kvm` 的 VM。候选只剩经实测的 Tart Linux `--nested`，或 Apple Container `--virtualization` 配合支持 KVM 的 Linux kernel。
6. `docker_api=required` 淘汰没有 Docker engine 的候选。remote Linux 使用 exe.dev 内的 Docker；local unknown 或 hostile workload 使用安装 Docker 的 Tart Linux；只有 local trusted workload 优先 OrbStack Docker。

硬约束过滤后再用这些偏好消除并列：

- hostile one-shot OCI workload 优先 Apple Container；需要完整 OS、独立 disk、Docker engine 或任务级持久化时选择 Tart Linux。
- trusted、长期 Linux 环境并重视 macOS 集成时选择 OrbStack machine。`--isolated` 减少文件和网络集成，不提供独立 kernel。
- 其余短命 Linux workload 选择 Apple Container。需要完整 Linux OS、可复制 VM disk 或超过 container lifecycle 的状态时选择 Tart Linux。

远程 macOS、缺少可验证 network boundary 的 hostile workload，或当前机器无法满足 nested virtualization 时，结论是「现有候选无解」。不要换成相似资源掩盖缺失能力。过滤过程中已经淘汰的候选不能被后面的偏好重新加入。

## 当前证据

用户要求性能数字、并发密度或方案比较时，读取 [performance-baseline-2026-07-13.md](references/performance-baseline-2026-07-13.md)。它是绑定到一次硬件与版本组合的历史观察，不是容量承诺；采购、并发上限或当前性能结论需要重新实测。

实际运行前读取 [operation-recipes.md](references/operation-recipes.md)。它是创建、数据暴露、验证、清理与 exe.dev handoff 的唯一执行契约。当前 CLI、release-tagged 官方文档或实测与 reference 冲突时，以当前证据为准。

Apple `container machine` 的历史故障证据只记录在 performance baseline。普通 `container run` 成功不证明 machine 路径健康；把 machine 纳入稳定路径前，必须在当前版本执行真实 `machine run`。
