# 共享 systemd slice

一台宿主上跑着几个互相信任的 runner 实例，要给它们设一个总的 CPU 或内存上限时读这份。用一个父 slice 管总量，不给每个实例平均切硬上限：平均切会让忙的实例用不上闲着的额度。

## runner 已经在专用 VM 里

这时 VM 的 vCPU 和最大内存（在宿主上设）就是整个池的上限。Guest 里的 slice 只用来记账和把实例归到一组，不另设第二层 CPU 或内存上限，除非就是要双重限制：

```ini
# /etc/systemd/system/ci-runners.slice
[Unit]
Description=GitHub Actions CI runner pool

[Slice]
CPUAccounting=yes
MemoryAccounting=yes
TasksAccounting=yes
```

只有同一个 VM 里还有别的可信负载、需要给它们留出容量时，Guest 里的 slice 才值得设得更严。

## 动手前

任何 restart 或 remove 前先 drain。GitHub 生成的 unit 是 `KillMode=process`；改成 `control-group` 后，systemd 停服务时会连 job 的子进程一起发信号。这能避免 job 进程变孤儿，但改变了停服务的行为，不是无害的清理。

先看 cgroup 版本，再决定能用哪些指令、验收看哪些文件：

```bash
stat -fc %T /sys/fs/cgroup
test -f /sys/fs/cgroup/cgroup.controllers && echo cgroup-v2
systemctl --version | head -1
```

下面的 `MemoryHigh=`、`MemorySwapMax=` 和 `cpu.max`、`memory.high`、`memory.max`、`memory.swap.max` 都假设是 cgroup v2。cgroup v1 要按本机的 controller 布局另行设计和验证，不能照抄。

## 配置

systemd 不支持行尾注释，注释要单独一行。

```ini
# /etc/systemd/system/gharunners.slice
[Unit]
Description=GitHub Actions runner shared pool

[Slice]
# 16 cores
CPUQuota=1600%
# Soft reclaim threshold
MemoryHigh=110G
# Hard pool ceiling
MemoryMax=128G
MemorySwapMax=0
```

unit 的实际名字从实例目录的 `.service` 读。用 `actions.runner.<ORG>.<PREFIX>-.service.d` 这种前缀 drop-in 前，先用 `systemctl cat <UNIT>` 确认每个目标 unit 都加载了它；unit 名被替换字符或截断过时，可能要给每个 unit 各放一份相同的 drop-in。

```ini
# /etc/systemd/system/actions.runner.<ORG>.<PREFIX>-.service.d/80-pool.conf
[Service]
Slice=gharunners.slice
KillMode=control-group
```

重启策略和池上限是两回事。只有任务里要处理崩溃循环时才加：

```ini
[Unit]
StartLimitIntervalSec=5min
StartLimitBurst=5

[Service]
Restart=on-failure
RestartSec=15s
```

## 上线和验收

跑 `systemd-analyze verify <UNIT>`，目标 unit 有 warning 就算失败。`daemon-reload` 后，先 drain 并重启一个服务，再铺开。

```bash
systemctl cat <UNIT>
systemctl show <UNIT> \
  -p Slice -p ControlGroup -p KillMode \
  -p Restart -p RestartUSec -p StartLimitIntervalUSec -p StartLimitBurst
cat /sys/fs/cgroup/gharunners.slice/cpu.max
cat /sys/fs/cgroup/gharunners.slice/memory.high
cat /sys/fs/cgroup/gharunners.slice/memory.max
cat /sys/fs/cgroup/gharunners.slice/memory.swap.max
```

`systemctl show` 看的是 systemd 加载的属性，`systemctl cat` 看是哪些文件，进程实际在哪个 cgroup 要看 `/proc/<PID>/cgroup` 和 `/sys/fs/cgroup`。`daemon-reexec` 不会把已经在跑的服务挪进新 cgroup，要 drain 后重启服务。

## 回滚

1. drain 受影响的 runner。
2. 删掉池和重启策略的 drop-in；没有 unit 再用这个 slice 时，删掉 slice unit。
3. `systemctl daemon-reload`。
4. 重启 runner。
5. 核对 `Slice`、`ControlGroup`、`KillMode`、重启相关属性，以及进程已经离开旧 cgroup。

只删 drop-in 不改变 systemd 已加载的状态，也不挪动在跑的进程。
