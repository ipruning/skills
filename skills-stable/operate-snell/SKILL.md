---
name: operate-snell
description: >-
  Deploy, audit, repair, migrate, and validate Snell v5/v6 on Linux VPSes and
  macOS Surge clients. Use whenever the user names Snell, snell-server, a Snell
  policy, Snell v5/v6, Decryption failed, Snell UDP/QUIC crashes, Surge Ponte
  NAT behavior backed by Snell, or asks to set up or fix a Snell server. Covers remote evidence
  collection, evidence-backed server changes, v6 canaries, and Snell-specific
  Surge policy smoke tests. Generic macOS Surge runtime and DNS diagnosis
  belong to surge; unrelated whole-host Linux work belongs to
  operate-linux-servers; REALITY+HY2 belongs to sing-box-reality-hy2.
metadata:
  version: "1"
---

# Operate Snell

Snell 的协议、服务端和客户端验证只有一个 owner。先判定请求是审计、部署、修复、迁移还是客户端烟测，再读对应 reference；不要因为客户端运行在 Surge 或服务端运行在 Linux，就同时加载 `$surge` 或 `$operate-linux-servers`。

## 路由

- 现有服务器故障、版本识别、`Decryption failed`、UDP crash、暴露面或 fleet 审计：[references/snell-vps-triage.md](references/snell-vps-triage.md)
- 新部署、服务器侧修复、systemd、端口、防火墙和回滚：[references/snell-vps.md](references/snell-vps.md)
- 审计证据明确要求 sysctl、journald、Ponte NAT 或 v5 unit 变更：[references/snell-operator-action-patterns.md](references/snell-operator-action-patterns.md)
- Snell policy 的 profile、版本、PSK、路由、连通性、UDP relay、出口 IP 和 Snell-backed Ponte NAT 类型仍由本 Skill 负责，并用 `smoke-surge` 验收。Ponte 当前 backing policy 是 Snell 就足以从本 Skill 开始，不要求先证明故障因果；只有证据证明故障与 Snell 无关，属于通用 Surge Enhanced Mode、DNS、System Proxy 或非 Snell Ponte 路径，才转 `$surge`
- Snell service 的 systemd、端口、listener、防火墙和资源影响仍由本 Skill 负责。只有证据证明需要独立整机健康审计、入侵响应或与 Snell 修复无关的 Linux 变更，才转 `$operate-linux-servers`
- VLESS REALITY 与 Hysteria2 归 `$sing-box-reality-hy2`
- macOS Surge 可以由 `smoke-surge` 自动验收；iOS 只生成配置并要求用户在设备上返回语法、TCP、UDP relay 和出口 IP 的人工验收证据，不能把未执行的 iOS 门禁写成通过

## 默认工作流

1. 唯一确定目标 VPS、SSH 身份来源、Snell 端口、预期版本和客户端 policy，并按 [references/credentials.md](references/credentials.md) 确定 PSK 来源与交付路径。缺失项会改变行为时才询问；不继承其他主机的值。
2. 现有部署先审计。审计默认不改本机网络或服务器配置；远程 collector 会创建并删除临时证据目录，必须先取得这项临时远程写入授权。未获授权时只跑 `--dry-run` 或不落盘的人工只读命令。
3. 从 `audit.json` 的 `facts`、`findings`、`recommended_manual_actions` 和证据文件判断问题。不要把 `systemctl active`、端口监听或单条 `Decryption failed` 当成端到端结论。
4. 用户明确要求部署、修复、迁移或应用已确认方案时，才写服务器。写前保存 binary、config、unit、firewall 的回滚面并保住当前 SSH；写后验证 runtime、监听、重启计数和外部 Snell policy。
5. 只有 VPS 与本次请求明确包含的客户端都通过才报告完整端到端完成。macOS Surge 可自动验收；iOS 或其他无法自动运行的客户端门禁直接列为未验证，直到用户返回设备侧证据。不要为 iOS-only 任务自行扩大到未点名的 Mac。

默认从取证到端到端验收只加载本 Skill。发现 Snell 之外的独立问题时才增加相邻 Skill；不要在证据出来前预加载它们，也不要把 Snell 专属的 systemd、防火墙或 Surge profile 工作移交出去。

## 审计命令

脚本使用 `uv`，不把 Python 环境或依赖装进仓库：

```bash
uv run --script "<operate-snell skill dir>/scripts/snell_audit.py" audit-snell \
  --host root@203.0.113.10 \
  --port <snell-port> \
  --remote-base /var/tmp/snell-runs \
  --out /tmp/snell-runs

uv run --script "<operate-snell skill dir>/scripts/snell_audit.py" audit-fleet \
  --hosts ./snell-hosts.txt \
  --port <snell-port> \
  --remote-base /var/tmp/snell-runs \
  --out /tmp/snell-runs
```

`audit-snell` 看 stdout 的 `evidence_paths.audit_json`；`audit-fleet` 逐台打开 `results[].evidence_paths.audit_json`。传输或采集失败才默认非零；要让结构性 finding 也阻断，显式传 `--fail-on-issue`。
脚本默认发现唯一的 `*snell*.service` unit；找不到候选、发现多个候选或 systemd 查询失败时，用 `--service <unit.service>` 明确选择，不按 unit 名猜运行实例。

Snell policy 烟测不碰 VPS，也不创建或切换 Surge profile。先按
[references/snell-vps-triage.md](references/snell-vps-triage.md) 激活并验证临时 policy，再执行：

```bash
uv run --script "<operate-snell skill dir>/scripts/snell_audit.py" \
  smoke-surge --policy <policy-name>
```

逐条检查 `results[].status` 与 `results[].parsed`。UDP relay、出口 IP 与 NAT 类型是不同断言，不能互相替代。

旧入口 `surge/scripts/snell_audit.py` 仅是迁移兼容 wrapper。新调用必须使用本 Skill 的脚本路径。`audit.json` / `result.json` 的 evidence `schema_version` 保持整数 `2`；run 的 `manifest.json` / `input.json` 保持 `surge-snell.audit-run.v2`；远端 `audit_summary.kv` 保持 `surge-snell.audit.remote.v1`。这些名字与值为兼容既有消费者而保留，不表示 ownership。

## Secrets 与验收

- PSK、私钥和凭据不进聊天、命令行历史、unit、journal、host 清单或 run ID。profile 名、端点 IP 和 journal 原文也可能敏感，分享审计目录前单独扫描。
- payload 只保证脱敏已识别的 `psk = ...` 配置行，不保证整个证据目录无 secrets。
- 新建或替换 PSK 时使用独立高熵值，不跨节点或 v5/v6 复用。
- Snell v5/v6 的 transport、配置键和防火墙形状从实际 server binary、`--help`、官方 release notes、listener 与客户端 profile 共同确定，不按旧教程猜。
- 完整验收包括：服务版本符合计划、systemd active 且无重启循环、实际 listener 与 firewall 一致、journal 无新增结构性错误、Surge profile 语法通过、policy TCP/出口 IP 通过，并按请求验证 UDP relay 或 NAT。
