---
name: surge
description: "macOS network triage when Surge is installed, active, or plausibly in the network path: Surge CLI usage and output, profile syntax, Enhanced Mode / System Proxy / DNS failures, Tailscale coexistence, local policy smoke tests, and read-only Snell VPS evidence audits with repair plans. Read-only: it never applies local network or server changes. Server-side execution belongs to linux-server; REALITY+HY2 deployment belongs to sing-box-reality-hy2."
metadata:
  version: "2"
---

# Surge

macOS 网络问题的分诊台。先识别请求类型，再读 reference 或跑命令：Surge CLI 问题、本机 triage、policy 烟测、Snell VPS 审计、Snell v6 canary 规划。本 skill 只读，产出证据和手动计划，不执行本机网络切换，也不执行服务器变更。

## Surge CLI

CLI 语法、子命令、flag 和输出解读，先查 app 内置文档：

```bash
test -f /Applications/Surge.app/Contents/Resources/Skills/surge/SKILL.md
```

内置文档不存在时，用 `PATH` 里或 `/Applications/Surge.app/Contents/Applications/surge-cli` 实际安装的 CLI 回答。不要拿网络 triage 流程回答 CLI 问题。

## 本机 triage

故障发生在用户的 macOS 上且 Surge 活跃、被点名或位于代理与 DNS 边界时，先读 [references/macos-network-triage.md](references/macos-network-triage.md) 再下结论。Tailscale 也在路径里时留在本 skill 处理：检查 Enhanced Mode 下 Tailscale 路由和 MagicDNS 是否保住，不要把 Linux sing-box 的 `route_exclude_address` 照搬给 Surge。

用户要本机开关或修复时，读 [references/macos-surge-operator-actions.md](references/macos-surge-operator-actions.md)，输出手动命令计划。

## 路由边界

- 与 Surge 和 Snell 无关的 Linux 网络问题归 `$linux-server`，exe.dev VM 上有对应 skill 时归它。
- 审计发现需要 VPS 变更时，防火墙、sysctl、systemd 重启、装包、调优都不在这里做：这里只出证据和 `manual_actions`，执行交给 `$linux-server` 或人类操作员。
- REALITY+HY2 栈的部署与验证归 `$sing-box-reality-hy2`，本 skill 只管 Surge 运行时行为和 Snell 证据。

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

3. `audit-snell` 看打印出的 `evidence_paths.audit_json`。`audit-fleet` 读 stdout 的 `results[]`，逐台打开各自的 `audit_json`。每份审计里读 `facts`、`findings`、`evidence_paths` 和 `recommended_manual_actions`。
4. 需要修复计划时跑 `render-repair-plan --audit <audit.json>`。它只打印 `manual_actions`，不执行任何变更。
5. 本机 policy 烟测跑 `smoke-surge --policy <policy-name>`，不碰 VPS。顶层 `status=ok` 是全部探测通过，`warn` 是有探测不受支持。逐条看 `results[].status` 和 `results[].parsed` 再判 policy 健康。

端点 IP、PSK、profile 名和清单留在用户任务或私有配置里。审计输出不保证脱敏，redaction guard 没检查过运行目录之前不要当它已脱敏。Snell v6 部署或迁移请求先审计再写 canary 计划，操作员改完之后重跑 `audit-snell` 和 `smoke-surge` 验证。
