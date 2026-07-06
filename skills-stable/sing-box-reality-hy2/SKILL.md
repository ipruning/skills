---
name: sing-box-reality-hy2
description: "Deploy, repair, and validate a narrow sing-box stable stack: VLESS REALITY Vision on TCP/443 plus Hysteria2 on UDP/443, with certbot and Cloudflare DNS-only records. Use when the user gives a VPS, SSH host, or domain and wants server setup, cross-platform client configs, migration off Clash/Mihomo, or REALITY/HY2 testing and diagnosis. Standalone Surge triage and Snell audits belong to the surge skill."
metadata:
  version: "2"
---

# sing-box REALITY HY2

只部署这一个窄栈，不要把它做成代理面板、全协议合集或长期环境变量代理。请求跨多个面时按顺序推进：先服务器，再 Linux mixed 烟测，再 systemd TUN，然后清掉旧代理守护进程、shell export 钩子和临时 fallback，最后 macOS 或 Windows 客户端和测速。

## 路由

识别请求面，只读对应的 reference：

- 服务器搭建或修复：[references/server.md](references/server.md)
- Linux/VPS 客户端、测试、从 Clash/Mihomo/shell export 迁移：[references/linux-client.md](references/linux-client.md)
- macOS Surge 配置或测试：[references/macos-client.md](references/macos-client.md)
- Android/SFA 与 Tailscale 共存：[references/android-client.md](references/android-client.md)
- Windows 客户端配置或测试：[references/windows-client.md](references/windows-client.md)
- 测速、性能解读、SOP 与真实服务器的比对：[references/testing.md](references/testing.md)
- 独立的 Surge 分诊、Snell 审计、Snell v6 canary 和修复计划归 `$surge`

缺输入时只问阻塞项。服务器搭建要 SSH 访问、`SERVER_IP`、DNS-only 的 `HY2_DOMAIN`，以及可达的 `REALITY_SNI` 或使用默认值的许可。客户端要服务器 secrets，或能 SSH 上去读。certbot 可以无邮箱运行，前提是用户接受这个代价，并留一条日后补邮箱的提醒。

## 硬规则

- 用官方 Sagernet APT 源的 `sing-box` stable，基线 1.13.x。不装 beta，不用文档标为 1.14.0 alpha 的字段，除非用户在 stable 支持后明确要求迁移。
- 生产环境不用面板和一键脚本，用可审计的配置文件加 systemd。
- secrets 不进聊天：REALITY 私钥、HY2 密码、PSK 一律 redact，UUID 非必要不显示。
- 每次 restart 前跑 `sing-box check`，check 通过之后才能 `sing-box format -w`。
- 防火墙、TUN 或路由变更之前保住 SSH。没有回滚手段或临时测试机时，不在 SSH 会话里直接启 Linux TUN。
- Linux 的终态是 systemd TUN。`HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 只是烟测工具，TUN 起来之后必须从默认环境里清掉。
- 对照文档验证真实服务器时，读 runtime 状态和 redacted 配置字段，不靠先前记忆。

## 关键默认值

- REALITY SNI 用 VPS 可达的稳定 TLS 1.3 站点，比如 `www.apple.com`。
- HY2 域名用 Cloudflare DNS-only 的 A 记录指向 VPS IPv4，不开橙云，IPv6 未验证就不加 AAAA。HY2 outbound 拨 `SERVER_IP`，TLS `server_name` 用 `HY2_DOMAIN`。
- Linux selector 默认 `vless-reality-out`，全设备默认 systemd 的 `sing-box@<name>.service` 跑 `/etc/sing-box/<name>.json` 的 TUN 配置。
- Linux TUN 的 DNS 默认 `ipv4_only`，除非 IPv6 在 DNS、路由和软件源三处都验证过。`prefer_ipv4` 仍会把 AAAA 暴露给应用，不够。
- Tailscale 按平台分派。Linux TUN 启用前，把 [references/linux-client.md](references/linux-client.md) 列出的 Tailscale 网段加进 `route_exclude_address`，SSH 本身走 Tailscale 时尤其如此。macOS Surge 要保住 Tailscale DIRECT 和 MagicDNS，但没做过 live route 测试就不照搬 Linux 的排除段。Android/SFA 和 Tailscale 共用 VPN service 语义，不承诺同时全设备 VPN。
- Windows 从 mixed 起步避免路由冲突，full-device TUN 按具体客户端适配并验证 Tailscale 路由。
- macOS Surge 对这个栈 HY2 优先、Snell 兜底，Surge 的协议限制不改变 Linux 和 Android 的设计。

## 验收标准

以下全部通过之前不许说部署完成：

```text
Server:
  sing-box check
  systemctl is-active sing-box
  ss shows TCP/443 and UDP/443 owned by sing-box
  certbot certificate exists for HY2_DOMAIN

Linux client:
  mixed REALITY returns VPS IP from api.ipify.org when doing a protocol smoke test
  mixed HY2 returns VPS IP from api.ipify.org when doing a protocol smoke test
  systemd TUN service is active and enabled
  fresh bash/zsh shells have no HTTP_PROXY / HTTPS_PROXY / ALL_PROXY defaults
  curl --noproxy "*" returns the VPS IP without proxy env
  Arch/Omarchy mirrors return HTTP 200 without proxy env and resolve to IPv4-only unless IPv6 is intentionally enabled
  logs show inbound/tun, dns exchanged, and outbound/vless by default
  old Clash/Mihomo services, ports, /opt/clash, and shell watch_proxy hooks are absent after migration

macOS Surge:
  surge-cli --check profile
  test-policy-external-ip returns VPS IP
  test-policy-udp returns a response for HY2
```
