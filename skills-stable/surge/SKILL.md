---
name: surge
description: "Use for non-remediating macOS network diagnosis when Surge is installed, active, or plausibly in the path: Surge CLI and profile behavior, Enhanced Mode, System Proxy or DNS failures, protocol-agnostic policy routing and smoke tests, and Tailscale coexistence. It does not switch local network state or execute repairs. Snell-specific servers, policies, transport tests, deployment, repair, and validation belong to operate-snell; REALITY+HY2-specific work belongs to sing-box-reality-hy2."
metadata:
  version: "5"
---

# Surge

本 Skill 只诊断 macOS 上 Surge 所在的网络路径，产出证据与手动计划，不切换本机网络、不改 profile、不执行修复。

## Surge CLI

CLI 语法、子命令、flag 和输出解读，先查 app 内置文档：

```bash
test -f /Applications/Surge.app/Contents/Resources/Skills/surge/SKILL.md
```

内置文档不存在时，用 `PATH` 里或 `/Applications/Surge.app/Contents/Applications/surge-cli` 实际安装的 CLI 回答。不要拿网络 triage 流程回答 CLI 问题。

## 本机 triage

故障发生在用户的 macOS 上且 Surge 活跃、被点名或位于代理与 DNS 边界时，先读 [references/macos-network-triage.md](references/macos-network-triage.md) 再下结论。Tailscale 也在路径里时留在这里处理：检查 Enhanced Mode 下 Tailscale 路由和 MagicDNS 是否保住，不要把 Linux sing-box 的 `route_exclude_address` 照搬给 Surge。

用户要本机开关或修复时，读 [references/macos-surge-operator-actions.md](references/macos-surge-operator-actions.md)，输出手动命令计划。

## 路由边界

- Snell server、systemd、端口、防火墙、Snell policy、版本、PSK、路由、v5/v6、Snell-backed Ponte NAT 和 Snell 专属 transport 测试全部归 `$operate-snell`。以当前 backing policy 判定 Ponte 初始 owner：policy 是 Snell 就先转 `$operate-snell`；协议无关或其他 policy 的 Ponte 路径诊断留在这里。
- REALITY+HY2 专属 profile、协议连通性、部署、修复与验证归 `$sing-box-reality-hy2`。
- Linux 网络问题归 `$operate-linux-servers`，exe.dev VM 上有对应 Skill 时归它。
