# 从国内判断节点是否被墙

判据：从**国内**的探测主机直连节点的服务端口，TCP 连得上就是通，连不上就是被墙。机器本身可能还活着，换 IP 见 [bandwagonhost.md](bandwagonhost.md)。`ping` 只作辅助，ICMP 可能被单独封。

下面是片段，不是成品脚本，按实际主机组装。判定、按首次失败时间去重、告警、systemd timer 和 secret 都按 `$end-to-end-monitoring` 组装。

## 必须直连，别走代理

探测主机自己常挂着透明代理（sing-box TUN 等），默认所有出站都走代理，那样测到的是「代理可达性」，不是国内真实的可达性。三种拿到直连的办法，按现场选：

1. 主机本来就直连，没有代理：直接测。
2. 代理支持按 uid 或规则放行：让探针的 uid 走 `direct`（sing-box 加 route 规则 `{ user_id:[<probe_uid>], outbound:"direct" }`）。稳，重启后不失效。
3. 给探测包打上代理的**绕行标记**：不用改代理，但代理重配后可能失效。

**别信 `ip route get`**：透明代理常在 nft 的 nat／dnat 层拦截，不在路由层，路由看着是直连，实际仍走代理。绕行标记去 nft 里找：

```bash
sudo nft list ruleset   # 在 inet sing-box 链里找 `meta mark 0x... return`，那个 mark 即绕行出口
ip rule                 # 参考 `fwmark 0x.../0xff0000 lookup main`
```

拿到标记（记为 `M`）后，打了标就是直连。**上线前打标和不打标各测一次出口回显，确认真的直连了**：

```bash
echo_ip=$(getent hosts myip.ipip.net | awk '{print $1; exit}')
curl -s --resolve myip.ipip.net:443:"$echo_ip" https://myip.ipip.net           # 不打标：应是代理出口
sudo iptables -t mangle -I OUTPUT -d "$echo_ip" -j MARK --set-xmark "$M/0xffffffff"
curl -s --resolve myip.ipip.net:443:"$echo_ip" https://myip.ipip.net           # 打标：应变成本机国内 ISP 出口
sudo iptables -t mangle -D OUTPUT -d "$echo_ip" -j MARK --set-xmark "$M/0xffffffff"
```

## 测一个节点

```bash
ip=<node-ip>; port=<node-port>; M=<bypass-mark>    # M 为空则不打标（主机本就直连）
[ -n "$M" ] && sudo iptables -t mangle -I OUTPUT -d "$ip" -j MARK --set-xmark "$M/0xffffffff"
timeout 5 bash -c "exec 3<>/dev/tcp/$ip/$port" 2>/dev/null && r=up || r=down
[ -n "$M" ] && sudo iptables -t mangle -D OUTPUT -d "$ip" -j MARK --set-xmark "$M/0xffffffff"
echo "$ip:$port $r"
```

节点 IP 每轮从运营商 API 现取（见 [bandwagonhost.md](bandwagonhost.md)），不写死：换 IP 后会变。打标需要 root 或免密 sudo。
