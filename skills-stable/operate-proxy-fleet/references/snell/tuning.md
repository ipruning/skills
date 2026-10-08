# Snell 节点调优

诊断阶段不套用这里的做法。审计的 `recommended_manual_actions` 里有对应项，或者从 `facts` 里看出确实需要调，才用。只要审计或方案时，这些是给人看的操作示例；要落地时，先记好回滚、确认目标和归属，照着证据对应的那一条做，做完重跑相关审计和 Surge policy 测试。

主机全局的 sysctl、防火墙写入和回滚走 `$linux-server` 的事务；这里给代理节点该有的目标值和验收方法。

## sysctl

只跑 Snell 的 VPS，一小组就够：

```ini
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.ip_local_port_range = 20000 65000
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_syncookies = 1
```

- 写之前确认内核支持 BBR、sysctl 可写。
- `ip_local_reserved_ports` 是整体替换的值。Snell 端口落在实际的 `ip_local_port_range` 里面时才需要预留；预留时把现有的所有预留合并进去，不要覆盖。用真实端口，不用示例里抄来的。
- `nf_conntrack_max` 不是必调项。只有 Docker、NAT、有状态防火墙规则或实测到 conntrack 压力时才提高。
- 不要抄大段 TCP buffer、`tcp_tw_reuse`、`tcp_abort_on_overflow` 或几十行的调优清单。它们藏风险，也很少解决真正的瓶颈。

## journald 和 swap

日志多的节点，在 `/etc/systemd/journald.conf.d/` 放一个 drop-in 限住大小：

```ini
[Journal]
SystemMaxUse=256M
RuntimeMaxUse=64M
```

用装好的 systemd 工具校验，在维护窗口里重启 journald，然后读实际生效的限制：

```bash
systemd-analyze cat-config systemd/journald.conf
journalctl --disk-usage
```

swap 不是提速手段，只是防 OOM 的垫子。已有 swap 且闲着就别动。加或改 swap 是整机变更，用户要求或实测到内存压力时交给 `$linux-server`。

## Surge Ponte 的 NAT 类型是 Type C

下面几条都成立时，才计划在 VPS 上放行入站的临时 UDP 端口段：

- Surge policy 用了 Surge Ponte 或别的 UDP 穿透流程。
- 这台自管的 Snell VPS 有公网地址，结果也不是 Docker 或云厂商 NAT 造成的。
- `test-policy`、`test-policy-external-ip`、`test-policy-udp` 都成功，而 `test-policy-nat-type` 返回 NAT Type C（`nat-type=3`）。
- 跑的是 Snell v6，只监听 TCP，不需要 Snell 的 UDP listener。不要开 `<snell-port>/udp`。

原因：VPS 发 STUN 用的是 IPv4 临时 UDP 源端口段（`net.ipv4.ip_local_port_range`），防火墙挡住了第三方 STUN 的回包。先读这个范围：

```bash
sysctl net.ipv4.ip_local_port_range
```

再查清是哪一层在管入站 UDP：UFW、nftables／iptables，还是云厂商的防火墙或安全组，在那一层放行这个端口段。用 UFW 管、范围是 `20000 65000` 的 VPS，加载 `$linux-server`，通过它的 UFW 事务执行 `ufw allow 20000:65000/udp comment 'surge-ponte-nat-traversal'`。下面的 Surge 检查通过之前，留着它打印的回滚状态。

在 Surge 上验证：

```bash
surge-cli --raw test-policy <policy-name>
surge-cli --raw test-policy-external-ip <policy-name>
surge-cli --raw test-policy-udp <policy-name>
surge-cli --raw test-policy-nat-type <policy-name>
```

`test-policy-nat-type` 应该变成 NAT Type A（`nat-type=1`）。还是 Type C 时，去查云厂商的防火墙或安全组的 UDP 规则，别先改 Snell。

主机防火墙收紧到最小规则时（比如同机部署 REALITY + HY2 后），普通代理照常可用，但 Ponte 的 NAT 类型可能从 A 掉到 C，按这一节处理。
