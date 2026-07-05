---
name: linux-server
description: "Operate Debian/Ubuntu servers over SSH: setup, hardening, audits, firewall and container port exposure, package maintenance, swap, and proxy/VPN server tuning. Not for macOS network problems — that is the surge skill. Snell evidence audits belong to surge; this skill executes the repairs surge plans. The REALITY+HY2 stack has its own skill, sing-box-reality-hy2."
metadata:
  version: "2"
---

# Linux Server

主机角色、风险状态和任务模式决定读什么证据、允许改什么状态。只在会改变这些决定时做分类。

## 保命规则

- 默认只读。用户明确要求配置、部署、修复或应用已知变更时才写。
- 改 SSH、防火墙或网络之前，保住当前 SSH 会话。有凭据和网络路径就开第二条活会话，没有就先安排好回滚，再动手。
- 验证 runtime 状态，不只看配置文件：`sshd -T`、`ss -tulpen`、`ufw status verbose`、`nft list ruleset`、`iptables -S`、`systemctl is-active`。
- 多领域请求按可达性排优先级：先 SSH 可达，再防火墙可达，然后才是包、服务和调优。单领域请求就待在请求的领域里，不顺手加固。
- 补丁只在当前发行版大版本内打，跨大版本升级要用户明示。
- 覆盖配置写进专用目录：SSH 用 `/etc/ssh/sshd_config.d/`，sysctl 用 `/etc/sysctl.d/`，fail2ban 用 `jail.local`，systemd 用 unit drop-in。只有服务没有覆盖机制时才改包管理的默认文件。

## 首招：只读体检

没有更窄的命令集时从这里开始：

```bash
whoami && id && hostname && date -Is && uptime && uname -a
df -h / /var /boot 2>/dev/null || df -h
free -h
systemctl --failed --no-pager
ss -tulpen
sshd -T | awk '$1 ~ /^(port|listenaddress|permitrootlogin|passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|maxauthtries|maxsessions|logingracetime|allowusers|allowgroups|authenticationmethods|permituserrc|x11forwarding)$/ { print }'
if command -v ufw >/dev/null 2>&1; then ufw status verbose; fi
if command -v nft >/dev/null 2>&1; then nft list ruleset 2>/dev/null; fi
iptables -S 2>/dev/null
ip6tables -S 2>/dev/null
```

## 主机角色

- 单主 VPS：用户直接管 root 的个人机、代理节点、Snell/Xray 盒子。保持 key-only root 的访问形状，只开当前需要或明确规划的端口。不默认加非 root 管理员、fail2ban、SSH 算法表或 sysctl 调优，机器没这个需要且用户没要求就不加。SSH 细节看 [references/ssh.md](references/ssh.md)，防火墙看 [references/firewall.md](references/firewall.md)，Snell 搭建或修复看 [references/snell-vps.md](references/snell-vps.md)。
- 团队管理机：多于一个人类管理员，访问要能按人吊销。一人一账号，验证过 sudo 之后才收 root SSH，`AllowUsers` 要等全部预期用户都测试过再加。看 [references/ssh.md](references/ssh.md)。
- 不明或疑似失陷机：先取证后修复。证据收齐之前不升级、不清理、不轮换、不删除、不重启、不改写持久化。看 [references/unknown-server-audit.md](references/unknown-server-audit.md)。
- 容器主机：Docker 发布的端口可能绕过 UFW 的 input 规则。改防火墙前把每个公网端口映射到进程、容器和防火墙路径，没确认真实的转发问题就不加宽路由规则。看 [references/containers.md](references/containers.md)。
- 公网 Web/应用机：80 和 443 只在有 listener 或规划服务时保留。面板和管理后台按管理端口对待，服务没有公网客户或用户确认了来源范围才收紧。看 [references/firewall.md](references/firewall.md)。

## 任务模式

- 维护窗口：noninteractive 命令用 `apt-get` 不用 `apt`，改包之前查磁盘、失败单元、listener、apt 模拟和重启需求。看 [references/maintenance.md](references/maintenance.md)。
- Swap：改之前查 RAM、现有 swap 设备、根盘空间和 `/etc/fstab`，扩容优先沿用现有路径，用户明确要多设备才建第二块。看 [references/swap.md](references/swap.md)。
- 性能调优：先有可测量的目标再写 sysctl，不往普通的 SSH 或防火墙变更里塞抄来的调优清单，用户没要求就不动 SSH 算法。看 [references/performance-tuning.md](references/performance-tuning.md)。

## 改文件六步

1. 一两句话总结计划的变更。
2. 备份要改的那个文件。
3. 能验证就先验证语法：`sshd -t`、`nft -c -f`、`systemd-analyze verify`。
4. 服务支持 reload 且语法通过时，用 reload 不用 restart。
5. SSH 或防火墙变更后，开一条全新连接确认可达。
6. 重读 runtime 状态，报告实际生效的设置。
