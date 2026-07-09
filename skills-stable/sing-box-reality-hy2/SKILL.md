---
name: sing-box-reality-hy2
description: "Deploy, repair, and validate a narrow sing-box stable stack: VLESS REALITY Vision on TCP/443 plus Hysteria2 on UDP/443. Use for Debian/Ubuntu systemd VPS setup, Linux system-level TUN, cross-platform client configs, migration off Clash/Mihomo, REALITY/HY2 testing, or a 科学上网/翻墙/梯子 request when the user is open to this REALITY+HY2 stack. Surge-related macOS network triage and Snell audits belong to the surge skill."
metadata:
  version: "5"
---

# sing-box REALITY HY2

只部署这一个窄栈，不要把它做成代理面板、全协议合集或长期环境变量代理。只完成用户点名的请求面。用户要求完整 rollout 时，按服务器、Linux mixed 烟测、Linux systemd TUN、旧代理清理、其他平台客户端和测速的顺序推进。

## 路由

先把症状定位到服务器还是某个客户端，「REALITY 连不上了」这类原话要先判断故障在哪一侧，再落到对应 reference：

- 服务器搭建或修复：[references/server.md](references/server.md)
- Linux/VPS 客户端、测试、从 Clash/Mihomo/shell export 迁移：[references/linux-client.md](references/linux-client.md)
- macOS Surge 配置或测试：[references/macos-client.md](references/macos-client.md)
- Android/SFA 与 Tailscale 共存：[references/android-client.md](references/android-client.md)
- Windows 客户端配置或测试：[references/windows-client.md](references/windows-client.md)
- 测速、性能解读、SOP 与真实服务器的比对：[references/testing.md](references/testing.md)
- iOS/SFI 不在本栈覆盖内，用户点名 iPhone 时先说明这一点
- 非本栈的通用 Linux 服务器操作、入侵排查、防火墙、Snell 部署归 `$linux-server`
- 独立的 Surge 分诊、Snell 审计、Snell v6 canary 和修复计划归 `$surge`

缺输入时只问阻塞项。服务器搭建要 SSH 访问、`SERVER_IP`、DNS-only 的 `HY2_DOMAIN`，以及用户指定的 `REALITY_SNI`，或由 Agent 从 VPS 实测后选择目标的许可。`REALITY_HANDSHAKE_HOST` 默认同 `REALITY_SNI`，不是单独的阻塞项。客户端要服务器 secrets，或能 SSH 上去读。certbot 可以无邮箱运行，前提是用户接受这个代价，并留一条日后补邮箱的提醒。

## 硬规则

- 这套字段和行为已在 `v1.13.14` 验证。用官方 Sagernet APT 源安装 stable，不装 beta 或 prerelease。安装版本不是 stable `1.13.x` 时，先读该版本的 migration 和对应文档，不得直接套用本模板。
- 生产环境不用面板和一键脚本，用可审计的配置文件加 systemd。
- secrets 不进聊天：REALITY 私钥、HY2 密码、PSK 一律 redact，UUID 非必要不显示。
- 配置先写 candidate，执行 `sing-box check`、`sing-box format -w`、再次 `sing-box check`。只有格式化后的最终 check 通过才能替换 live config 和 restart。
- 防火墙、TUN 或路由变更之前保住 SSH。没有回滚手段或临时测试机时，不在 SSH 会话里直接启 Linux TUN。
- `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 只是烟测工具，TUN 起来之后必须从默认环境里清掉。
- 对照文档验证真实服务器时，读 runtime 状态和 redacted 配置字段，不靠先前记忆。

## 关键默认值

- REALITY 目标必须从 VPS 实测 TLS 1.3、ALPN h2、无目标域名跳转，并优先选择网络位置接近 VPS 的站点。不要把某个公共站点写成跨地域永久默认值。
- HY2 域名用 Cloudflare DNS-only 的 A 记录指向 VPS IPv4，不开橙云，IPv6 未验证就不加 AAAA。HY2 outbound 拨 `SERVER_IP`，TLS `server_name` 用 `HY2_DOMAIN`。
- Linux selector 只列 `vless-reality-out` 和 `hy2-h3-out`，默认前者。`direct` 只服务显式路由规则，不作为全局 selector 选项。VLESS outbound 不写 `network`，让 `v1.13.14` 默认启用 TCP 和 UDP。写成 `"network": "tcp"` 会让 UDP 直接失败。HY2 是可手动选择的高速备用，不默认接管全部 UDP。
- HY2 默认不写 `up_mbps` / `down_mbps`，让 `v1.13.14` 使用自动 BBR。只有固定网络在同端点完成至少 3 轮吞吐和负载延迟比较后，才按可持续带宽启用 Brutal。移动网络和不确定链路继续用自动 BBR。
- `v1.13.14` 的 REALITY 客户端源码要求 `with_utls` 和 `utls.enabled=true`。上游虽已将通用 uTLS 标为不推荐，本模板在跨 stable 版本时必须重新验证这一实现约束。
- Linux 工作站和专用客户端的终态是 systemd 的 `sing-box@<name>.service` 跑 `/etc/sing-box/<name>.json`。承载业务的 VPS 默认只做 mixed/scoped proxy，除非用户明确批准全机 TUN 的出口和回程变化。
- Linux TUN 保持 `auto_route + auto_redirect + strict_route`。不写 `stack`，沿用安装包的上游默认。不因网上调优清单盲目改 MTU、TCP 拥塞控制或 UDP buffer。先读实际接口、socket buffer、drop counter 和同路径测试结果。
- VLESS 和 HY2 不承载 ICMP。Linux TUN 把 `network = icmp` 显式路由到 `direct`，避免 `ping` 失效和日志持续告警。这是可见的直连流量，用户要求禁止 ICMP 泄漏时改为明确 reject。
- 常驻客户端日志用 `warn`。部署和故障定位时临时改为 `info`，验收后恢复，避免逐连接日志长期占用 journal 和 CPU。
- Linux TUN 的 DNS 默认 `ipv4_only`，除非 IPv6 在 DNS、路由、软件源和 curl 全部验证过。`prefer_ipv4` 仍会把 AAAA 暴露给应用，不够。
- Tailscale 按平台分派。Linux TUN 启用前，按 [references/linux-client.md](references/linux-client.md) 保护 tailnet 地址、当前管理路径和 `tailscaled`。启用后实测 peer、MagicDNS、accepted subnet routes 和当前 SSH。macOS Surge 不照搬 Linux 排除段。Android/SFA 和 Tailscale 共用 VPN service 语义，不承诺同时全设备 VPN。
- Windows 从 mixed 起步避免路由冲突，full-device TUN 按具体客户端适配并验证 Tailscale 路由。
- macOS Surge 原生使用 HY2。只有已存在并且用户要求保留 Snell 时才把它加入 fallback。Snell 的健康和修复归 `$surge`。

## 验收标准

只对实际执行的请求面应用对应门禁。完整 rollout 需要全部通过：

```text
Server:
  sing-box check
  systemctl is-active/is-enabled sing-box
  ss shows TCP/443 and UDP/443 owned by sing-box
  certbot certificate exists for HY2_DOMAIN
  certbot timer and validated renew hook exist
  an external client proves both REALITY and HY2 authentication

Linux client:
  mixed REALITY returns VPS IP from api.ipify.org when doing a protocol smoke test
  mixed HY2 returns VPS IP from api.ipify.org when doing a protocol smoke test
  systemd TUN service is active and enabled
  fresh bash/zsh shells have no HTTP_PROXY / HTTPS_PROXY / ALL_PROXY defaults
  curl --noproxy "*" returns the VPS IP without proxy env
  package mirrors return HTTP 200 without proxy env and resolve IPv4-only unless IPv6 is intentionally enabled
  an HTTP/3 request succeeds with selector default VLESS
  ping works through the explicit ICMP direct rule, or is explicitly rejected by policy
  logs show outbound/vless packet traffic and no "UDP is not supported" error
  steady-state warn logs contain no repeating route or buffer errors after test traffic stops
  Tailscale peer, MagicDNS, accepted routes, and current SSH still work when Tailscale is present
  confirmed old Clash/Mihomo services, ports, owned paths, and shell watch_proxy hooks are absent after migration; unrelated paths are explicitly retained

macOS Surge:
  surge-cli --check profile
  test-policy-external-ip returns VPS IP
  test-policy-udp returns a response for HY2

Windows and Android:
  run the validation block in the platform's own reference (windows-client.md, android-client.md)
```
