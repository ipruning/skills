---
name: operating-jetkvm-tailscale
description: >-
  运维 JetKVM 上的 Tailscale 远程访问，或诊断其 HTTPS Certificates、Serve、证书签发、精简固件兼容和重启持久化。用户提到 JetKVM 与 Tailscale 的安装、升级、故障、远程访问或 HTTPS 时使用。不用于普通 Tailscale 节点、JetKVM 视频或 USB 硬件故障，也不用于主动配置 Funnel 公网发布。
metadata:
  version: "1"
---

# 运维 JetKVM 上的 Tailscale

把 JetKVM 作为 tailnet 内的普通终端节点运行，通过 Tailscale Serve 将本机 Web UI 的 HTTP 80 转为 tailnet-only HTTPS。默认不启用子网路由、出口节点、App Connector 或 Funnel。

普通 Linux Tailscale 节点不使用本 Skill。JetKVM 的视频采集、USB HID、HDMI 或受控主机故障也不使用本 Skill。用户要把 JetKVM 公开到公网时停止，不要把下文的 Serve 安全结论套到 Funnel。

## 先守住控制路径

- 任何会停止或重启 `tailscaled`、替换二进制、修改 netfilter 模式或重启 JetKVM 的动作，都从 LAN SSH 执行。先证明另一个连接能通过 LAN IP 登录；只有 Tailscale 路径可用时保持只读。
- 登录态只提供身份。启用 tailnet 级 HTTPS、修改管理后台、安装、升级、重启、清空状态或切换节点角色，需要用户明确要求对应结果。
- `tailscale serve` 是 tailnet-only 入口。不要运行 `tailscale funnel`。发现 Funnel 时先报告公网暴露，再取得授权后定点关闭对应端口。
- 官方安装器的 `--clean` 会删除 `/userdata/tailscale`，使节点身份、状态、CA 和证书缓存丢失。普通重装、升级和故障恢复禁止使用。
- JetKVM 的 BusyBox `wget` 不能可靠验证 TLS。二进制、安装器和 CA bundle 在可信操作机下载并校验，再经 SSH 标准输入传输。
- ACME 失败后停止重复请求。先读取日志和 `Retry-After`；频繁签发会触发 Let’s Encrypt 限流。

## 先路由，再收集证据

从用户给出的 LAN 地址开始，不根据历史设备名或旧 IP 猜。先按用户任务或首个故障现象进入 [references/runbook.md](references/runbook.md) 的最窄章节：

| 任务或现象 | 入口 |
| --- | --- |
| 首次安装、固定版本安装、升级 | 「安装与更新」 |
| `unknown authority` | 「持久 CA trust store」；先分诊，不能见错就装 |
| `Protocol not supported`、netfilter 告警 | 「精简内核与 netfilter」；先证明节点是纯终端 |
| HTTPS Certificates 已开但网页失败 | 先验证本机 `http://127.0.0.1:80`；正常才进「Tailnet-only HTTPS Serve」和「证书分诊」 |
| ACME order 很快 `invalid` | 停止重试；先完成「证书分诊」 |
| Ghostty terminfo 安装失败 | 「Ghostty terminfo」；它不影响 Tailscale 或 HTTPS |
| 固件升级、回退、重启后失联 | 「更新、回滚与固件」和「验收」 |

只收集所选章节要求的证据，不默认执行整套调查。跨所有写操作的最小前置证据是 LAN SSH、设备时间、`/userdata` 挂载与可写状态，以及将被修改文件的当前内容。需要综合分诊时再读取版本、节点健康、prefs、Serve 状态和相关时间窗口日志。不要输出节点私钥、ACME account key、证书私钥、完整 tailnet 节点清单或无关身份信息。

只有日志、CA、网络、限流窗口和精确版本证据都把问题收窄到 Tailscale v1.102.2 的 DNS-01 传播竞态时，才读取 [references/acme-v1.102.2-recovery.md](references/acme-v1.102.2-recovery.md)。其他版本不能套用历史补丁。

## 做变更时保持单一事实源

- `/userdata` 承载持久二进制、节点 state、证书缓存、CA bundle 和 init 脚本。rootfs 中的 `/etc/ssl` 或 `/root/.terminfo` 只作为启动时投影，不保存唯一副本。
- 先读当前 `/oem/usr/bin/RkLunch.sh`，证明它仍按顺序执行 `/userdata/init.d/S??*`。需要 CA 投影时，`S21persistent-data` 必须在官方 `S22tailscale` 前运行。
- 变更现有文件时先写 `.new`、检查语法和权限，再在同一文件系统内 `mv`。不要直接截断正在使用的二进制、init 脚本或 CA 文件。
- 保留 `tailscaled.state` 和 `var/certs`。回滚版本只替换明确备份的 CLI、daemon 和 `S22tailscale`。
- 当前安装器、CLI 和固件行为高于本 Skill。命令或路径与现场不一致时停止写入，查当前官方文档或源码，不用旧配方猜。

## 每次写入都要验收

验收不能停在命令退出码或安装器的 `SUCCESS`：

1. LAN Web UI 返回成功。
2. `BackendState` 为 `Running`、节点 `Online`，且 `Health` 为空。
3. CLI 与运行中 daemon 版本完全一致。
4. Serve handler 指向 `http://127.0.0.1:80`，整台节点不存在 `AllowFunnel: true`。
5. 从 tailnet 客户端验证 SSH 和 HTTPS；线上证书主机名、有效期和 TLS 校验正确。
6. 当前实现能观察到 443 socket 时，它不绑定 wildcard 或 LAN IP；安全结论仍以 Serve／Funnel 状态和可达性为主。
7. 采用 CA、netfilter 或 terminfo 条件修复时，分别验证其持久路径和 prefs。

安装、升级、init 或持久化变更只有在用户允许重启、设备重启后完整复验仍通过，才能报告为持久有效。不要仅凭 load average 把问题归因于 Tailscale；缺少 Tailscale 健康或日志证据时转入 JetKVM 系统诊断。

收尾报告当前入口范围、改动对象、重启是否实际执行、上述验收证据、没有验证的管理后台或证书续期状态，以及需要用户保留的 LAN 恢复路径。
