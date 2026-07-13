---
name: surge
description: "Use for non-remediating macOS network diagnosis when Surge is installed, active, or plausibly in the path: generic Surge CLI and profile behavior, Enhanced Mode, System Proxy or DNS failures, policy routing, smoke tests, and Tailscale coexistence. Also use for Snell VPS evidence collection, diagnosis, repair planning, and v6 canary planning, including the first phase of a Snell repair request. It does not switch local network state, change server configuration, or execute repairs. Confirmed Snell server-side changes belong to operate-linux-servers; REALITY+HY2-specific profiles, transport connectivity, deployment, repair, and validation belong to sing-box-reality-hy2."
metadata:
  version: "3"
---

# Surge

本 Skill 有两个入口：Surge 位于网络路径时的 macOS 诊断，以及 Snell VPS 的取证、诊断、修复计划和 v6 canary 规划。两者都只产出证据和手动计划，不切换本机网络、不改服务器配置、不执行修复。VPS 采集器会在服务器上建一个临时证据目录、跑只读命令、成功后删掉目录，失败时目录可能残留，由输出的 `persistent_effects` 报告；执行前必须取得用户对这项临时远程写入的明确授权。未获授权时只跑 `--dry-run`，或改用不落盘的人工只读命令。

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

- 与 Surge 和 Snell 无关的 Linux 网络问题归 `$operate-linux-servers`，exe.dev VM 上有对应 skill 时归它。
- 审计发现需要 VPS 变更时，防火墙、sysctl、systemd 重启、装包、调优都不在这里做：这里只出证据和 `recommended_manual_actions`，执行交给 `$operate-linux-servers` 或人类操作员。修一个已坏的现有 Snell 也先在这里审计出证据，再交出去执行。
- REALITY+HY2 专属 profile、协议连通性、部署、修复与验证归 `$sing-box-reality-hy2`，这里只管通用 Surge 运行时、系统网络行为和 Snell 证据。

## Snell VPS 审计

1. 判定 VPS、Snell systemd 服务、UDP 行为、防火墙暴露、代理 sysctl 或 `Decryption failed` 之前，先读 [references/snell-vps-triage.md](references/snell-vps-triage.md)。
2. 单机用 `audit-snell`，成批用 `audit-fleet`。端点不是默认端口 `14180` 就传 `--port`：

   ```bash
   uv run --script "<surge skill dir>/scripts/snell_audit.py" audit-snell \
     --host root@203.0.113.10 \
     --port <snell-port> \
     --out /tmp/surge-snell-runs
   uv run --script "<surge skill dir>/scripts/snell_audit.py" audit-fleet \
     --hosts ./snell-hosts.txt \
     --port <snell-port> \
     --out /tmp/surge-snell-runs
   ```

3. `audit-snell` 看打印出的 `evidence_paths.audit_json`。`audit-fleet` 读 stdout 的 `results[]`，逐台打开各自的 `audit_json`。每份审计里读 `facts`、`findings`、`evidence_paths` 和 `recommended_manual_actions`。`findings` 只报结构性问题：crash fingerprint、暴露面、hardening 与可用性。性能与容量调优（sysctl、conntrack、swap、LimitNOFILE、MaxAuthTries、解密噪声）不出 finding，由你读 `facts` 现场判断。修复计划直接从 `facts` 和 `findings` 写给操作员，交给 operate-linux-servers skill 执行。
4. 本机 policy 烟测跑 `smoke-surge --policy <policy-name>`，不碰 VPS。顶层 `status=ok` 是全部探测通过，`warn` 是有探测不受支持，`issue` 是有探测失败且退出码 1。逐条看 `results[].status` 和 `results[].parsed` 再判 policy 健康。

端点 IP、PSK、profile 名和清单留在用户任务或私有配置里。payload 只脱敏 config 里的 `psk`，IP、listen 地址和 journal 原文都不脱敏，分享运行目录前先自己扫一遍 secrets，不要假定它已脱敏。Snell v6 部署或迁移请求先审计再写 canary 计划，操作员改完之后重跑 `audit-snell` 和 `smoke-surge` 验证。
