---
name: sing-box-reality-hy2
description: >-
  Deploy, repair, test, or monitor the sing-box stable VLESS REALITY Vision on
  TCP/443 plus Hysteria2 on UDP/443 stack. Use when the user names REALITY, HY2,
  this sing-box stack, or its existing server/client artifacts; asks to migrate
  Clash/Mihomo to this stack; or asks the agent to choose a self-hosted proxy
  stack. Covers Debian/Ubuntu servers and Linux,
  macOS Surge, Android/SFA, and Windows clients, including the host preflight,
  firewall, systemd, and rollback checks required by this stack. iOS/SFI is not
  covered. Separate whole-host audits, intrusion response, and generic Linux
  operations belong to operate-linux-servers; all Snell-specific work belongs
  to operate-snell; protocol-agnostic Surge runtime, DNS, and policy routing
  belong to surge.
metadata:
  version: "12"
---

# sing-box REALITY HY2

只部署这一个窄栈，不把它扩成代理面板、全协议合集或长期环境变量代理。只读当前请求面的 reference。完整 rollout 才依次处理服务器、Linux mixed 烟测、Linux systemd TUN、旧代理清理、其他平台客户端和测速。

## 路由

先把症状定位到服务器还是某个客户端，「REALITY 连不上了」这类原话要先判断故障在哪一侧，再落到对应 reference：

- 服务器搭建或修复：[references/server.md](references/server.md)
- Linux/VPS 客户端、测试、从 Clash/Mihomo/shell export 迁移：[references/linux-client.md](references/linux-client.md)
- macOS Surge 中 REALITY/HY2 专属配置、协议连通性或测试：[references/macos-client.md](references/macos-client.md)
- Android/SFA 与 Tailscale 共存：[references/android-client.md](references/android-client.md)
- Windows 客户端配置或测试：[references/windows-client.md](references/windows-client.md)
- 测速、性能解读、SOP 与真实服务器的比对：[references/testing.md](references/testing.md)
- 独立 HY2/QUIC 证书探针的协议断言：[references/monitoring.md](references/monitoring.md)。监控契约、backend、freshness 和通知闭环同时用 `$end-to-end-monitoring`
- 版本边界与源码证据：[references/version-compatibility.md](references/version-compatibility.md)
- 任何客户端配置前先确认输入及凭据来源：[references/client-inputs.md](references/client-inputs.md)
- iOS/SFI 不在本栈覆盖内，用户点名 iPhone 时先说明这一点
- 本栈部署所需的端口、防火墙、systemd、SSH 回滚和运行态预检留在本 Skill；独立整机审计、入侵排查和非本栈 Linux 操作归 `$operate-linux-servers`
- Snell 的审计、部署、修复、迁移、canary 和客户端验证归 `$operate-snell`；协议无关的 Surge 分诊归 `$surge`

## 硬规则

- 写配置前先读 [references/version-compatibility.md](references/version-compatibility.md)。只用官方 stable 构建，不装 beta 或 prerelease。
- 生产环境不用面板和一键脚本，用可审计的配置文件加 systemd。
- secrets 不进聊天：REALITY 私钥、HY2 密码、PSK 一律 redact，UUID 非必要不显示。
- 配置先写 candidate，执行 `sing-box check`、`sing-box format -w`、再次 `sing-box check`。只有格式化后的最终 check 通过才能替换 live config 和 restart。
- 防火墙、TUN 或路由变更之前保住 SSH。没有回滚手段或临时测试机时，不在 SSH 会话里直接启 Linux TUN。
- `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 只是烟测工具，TUN 起来之后必须从默认环境里清掉。
- 对照文档验证真实服务器时，读 runtime 状态和 redacted 配置字段，不靠先前记忆。

## 验收标准

每个 reference 的 validation 是对应请求面的 canonical 门禁。只报告实际运行的门禁；未运行、失败或无法观察的层直接列出。完整 rollout 必须有外部客户端分别证明 REALITY 与 HY2 认证，不能用配置校验、监听端口或 TCP TLS 探针替代。
