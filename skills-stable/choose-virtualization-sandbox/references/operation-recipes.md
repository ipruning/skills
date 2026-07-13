# Operation recipes

本文件是执行与清理契约。选择运行时不授权创建、公开、停止或删除资源。只有用户要求实际运行、测试或清理时才执行对应动作。

## Preflight

1. 读取当前 CLI 版本与对应版本的 `help`。本文件中的配方曾在 Apple Container 1.1.0、OrbStack 2.2.1、Docker 29.4.0 和 Tart 2.32.1 上核对，不是跨版本脚本。
2. 记录原始资源列表与状态，确认本次唯一名称未被占用。
3. 确认进入 guest 的 repo、ignored config、环境变量和凭据各自来自哪里。依赖、virtualenv、`node_modules`、build output 和 cache 从项目配置重建。
4. 分别落实 `host_files`、`internet_access`、`host_network` 与 `ingress`。read-only mount 防止写入，不防止读取或外传。
5. 当前 runtime 不能证明所需 network boundary 时停止。不把「没有 published port」当成「没有 internet access」，也不把宿主专用网络当成 disconnected network。

## Apple Container

未知或 hostile workload 默认不挂载宿主 checkout。使用干净 checkout、明确上传的最小输入或不含 ignored/untracked secret 的 staging directory。

```bash
container run --rm \
  --name "ai-${TASK_ID}" \
  --cpus 2 \
  --memory 4g \
  --cap-drop ALL \
  "$IMAGE" \
  <command> [args...]
```

只有 `host_files=read-only` 时才添加显式 mount：

```bash
--mount "type=bind,source=$SOURCE_DIR,target=/workspace,readonly"
```

`host_files=read-write` 必须来自任务本身的明确需要，并只暴露用户指定目录。Apple `container machine` 不在稳定配方中；按当前版本对应的 [container machine guide](https://github.com/apple/container/blob/main/docs/container-machine.md) 做 create/run smoke test，再执行真实 workload，两者都成功才可采用。该链接指向 current branch；实际版本不同就从 release page 打开对应 tag 的同名文档。

Apple Container 1.1.0 的 `container network create --internal` 创建宿主专用网络：它禁止 internet access，但允许 guest 接触宿主网络。只有 `internet_access=forbidden && host_network=required` 时使用，并以唯一名称创建和删除：

```bash
NETWORK_NAME="ai-${TASK_ID}"
container network create --internal "$NETWORK_NAME"
container run --rm --network "$NETWORK_NAME" ...
container network delete "$NETWORK_NAME"
```

`internet_access=forbidden && host_network=forbidden` 没有经过验证的 Apple Container 配方；不要用 `--internal` 冒充 disconnected network。

需要 nested KVM 时，按 [Apple virtualization how-to](https://github.com/apple/container/blob/main/docs/how-to.md#expose-virtualization-capabilities-to-a-container) 核对 host、CLI 与 kernel 条件，使用 `--virtualization` 和支持 KVM 的 Linux kernel。仅传入 custom kernel 或普通 container 成功都不能证明 nested virtualization 可用。

## OrbStack Docker

用 command-scoped context 和 task-scoped project name，不改变用户的全局 Docker context，也不命中目录中已有的 Compose project。所有 `--file`、`--env-file` 与 `--profile` 参数必须在 config、up、down 三步保持一致：

```bash
PROJECT_NAME="ai-${TASK_ID}"
CONFIG_PATH="$(mktemp)"
chmod 600 "$CONFIG_PATH"
docker --context orbstack compose --project-name "$PROJECT_NAME" config --format yaml > "$CONFIG_PATH"
```

先从 mode-600 临时文件审查展开后的结构，不把 resolved environment values 打印到日志。`host_files=none` 禁止 bind mount 与未授权 secret；`ingress=none` 禁止 `ports` 和宿主网络模式；`host_network=forbidden` 禁止 `network_mode: host`、宿主网关与等价路径；`internet_access=forbidden` 要求所有 attached network 都是 internal。发现显式 `container_name`、外部 network/volume 或其他 global name 时停止，因为 unique project name 无法隔离它们。

审查通过后，让 `up` 与 `down` 消费这份冻结配置，不重新读取可能已经变化的原始 Compose 文件：

```bash
docker --context orbstack compose --project-name "$PROJECT_NAME" --file "$CONFIG_PATH" up --build --abort-on-container-exit
docker --context orbstack compose --project-name "$PROJECT_NAME" --file "$CONFIG_PATH" down
rm "$CONFIG_PATH"
```

启动后用真实 probe 验证 internet access、宿主网络和 ingress。config 生成或审查失败时不执行 `up`。无论后续步骤是否成功，都删除临时 config；代码块末行只表示正常路径，实际执行使用当前 harness 的错误恢复机制保证清理。

默认 cleanup 不删除 named volume。只有用户明确要求丢弃这批数据时才向 `down` 添加 `--volumes`，并在执行前核对展开后的 Compose project。

## OrbStack machine

只用于 trusted workload。默认不挂载宿主文件；`--isolate-network` 阻止 isolated machine 访问宿主 IP 和其他 machine，因此满足 `host_network=forbidden`，但不满足 `internet_access=forbidden`。

```bash
VM_NAME="ai-${TASK_ID}"

orbctl create \
  --cpus 4 \
  --memory 8G \
  --disk 20G \
  --isolated \
  --isolate-network \
  alpine:3.22 \
  "$VM_NAME"

orbctl run --machine "$VM_NAME" /bin/sh -lc "$COMMAND"
```

只有 execution policy 需要宿主文件时才在 create 阶段添加选择性 `--mount SOURCE[:DEST]`。清理前用当前 list/detail 命令确认 VM 名称属于本次任务，再执行：

```bash
orbctl delete --force "$VM_NAME"
```

## Tart macOS or Linux VM

从用户指定或已确认维护中的 base 创建 CoW clone，不修改 base。只有安装并配置 Tart Guest Agent 的 image 才能使用 `tart exec`。

```bash
VM_NAME="ai-${TASK_ID}"

tart clone "$BASE_VM" "$VM_NAME"
tart run --no-graphics "$VM_NAME"
```

`tart run` 是长运行进程，放入当前 harness 管理的长期 session。不要用裸后台进程和固定 sleep 假装 readiness。真实 `tart exec` 成功后再执行目标命令：

```bash
tart exec "$VM_NAME" /bin/sh -lc "$COMMAND"
tart stop "$VM_NAME"
tart delete "$VM_NAME"
```

依赖树、checkout 与 build cache 使用 guest internal disk。shared mount 只用于 execution policy 明确需要的输入或 artifact。Linux nested virtualization 使用 `tart run --nested`，并以 `/dev/kvm` 与目标 hypervisor workload 的实测结果验收。

网络参数在 `tart run` 阶段选择：

- `--net-host` 是 host-only，不满足 `host_network=forbidden`。
- `--net-softnet` 默认限制 private IPv4 destination，但当前 help 仍允许 gateway IP。它可以作为 internet-access policy 的起点，不能单独证明 `host_network=forbidden`；必须验证 IPv4、IPv6、host 与 private-network probes。
- `--net-softnet-block=0.0.0.0/0` 建立 IPv4 default deny。`internet_access=forbidden && host_network=forbidden && ingress=none` 时不得添加 allow/expose，并必须验证 IPv4、IPv6、host 与 inbound probes；任一成功就不满足 contract。

当前 Tart 配方没有声称提供物理断网。contract 要求 absolute disconnected network 时，缺少可验证实现就是无解。

## exe.dev handoff

不要在本文件复制 exe.dev 的 `new`、list、SSH 或 delete flags。加载 `$exe-dot-dev`，把这些已确定信息交给它：

```yaml
purpose: disposable AI test sandbox
os: linux
docker_api: required | optional | forbidden
host_files: none | explicit-upload
internet_access: forbidden | required
host_network: forbidden | required
ingress: none | private-service | public-service
cleanup: always | retain-on-failure
resource_name: unique task-scoped name
```

默认保持 private。公开 HTTPS、custom domain、sharing 和 integration 是独立外部状态变更，只在任务明确需要时执行。第三方凭据只从用户授权的 exe.dev integration 注入。

## Verification and cleanup

在目标环境执行用户的真实命令和真实测试。最小 smoke test 只证明控制链可用。结束时保留这组证据：

```text
before: original resource list and state
created: exact temporary name and limits
tested: real command and result
exported: requested patch, artifacts, and logs
deleted or retained: exact name and reason
after: temporary resource absent; original resources unchanged
```

`retain-on-failure` 只保留本次创建的资源。报告资源名称、是否仍运行、数据暴露面、预期成本和后续精确清理动作。没有看到对应最终状态时，不声称「完成」「健康」「已清理」或「已验证」。
