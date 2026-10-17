# 从国内判断节点是否被墙

从国内探测主机直连节点。能经过该节点完成一次认证请求（见 [monitoring.md](../reality-hy2/monitoring.md)），就是通的；这是首选判据。TCP 端口连得上只说明三层可达，协议可能照样被干扰。只在没有凭据、拿不到协议探针的主机上退回 TCP 检查。`ping` 只作辅助，ICMP 可能被单独封。

TCP 连不上不等于被墙：先按 [bandwagonhost.md](bandwagonhost.md) 排除暂停、IP 黑洞和宿主机冻结，再考虑换 IP。

## 必须直连，别走代理

探测主机自己常挂着透明代理（sing-box TUN 等），默认所有出站都走代理，那样测到的是代理的可达性。拿到直连的办法，按现场选：

1. 主机本来就直连：直接测。
2. 代理支持按 uid 放行：让探针的 uid 走 `direct`（sing-box route 规则 `{ user_id:[<probe_uid>], outbound:"direct" }`）。
3. 探测 socket 打上代理的**绕行标记**（`SO_MARK`）：不用改代理，但代理重配后可能失效。

绕行标记在 nft 里找：

```bash
sudo nft list ruleset   # 在 inet sing-box 链里找 `meta mark 0x... return`，那个 mark 即绕行出口
ip rule                 # 参考 `fwmark 0x.../0xff0000 lookup main`
```

透明代理可能在 nft 的 nat 层拦截，`ip route get` 显示直连不代表真直连。拿到标记 `M` 后，上线前打标和不打标各测一次出口回显，确认打标后变成本机国内 ISP 出口：

```bash
echo_ip=$(getent hosts myip.ipip.net | awk '{print $1; exit}')
curl -s --resolve myip.ipip.net:443:"$echo_ip" https://myip.ipip.net           # 不打标：应是代理出口
sudo iptables -t mangle -I OUTPUT -d "$echo_ip" -j MARK --set-xmark "$M/0xffffffff"
curl -s --resolve myip.ipip.net:443:"$echo_ip" https://myip.ipip.net           # 打标：应是国内 ISP 出口
sudo iptables -t mangle -D OUTPUT -d "$echo_ip" -j MARK --set-xmark "$M/0xffffffff"
```

这段 iptables 只用于这次验证。长期探针直接在 socket 上设 `SO_MARK`。

## TCP 检查一个节点

```python
import socket
with socket.socket() as s:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, M)  # 需要 root 或 CAP_NET_ADMIN
    s.settimeout(5)
    s.connect((ip, port))                                 # 超时或拒绝 = down
```

探测的地址用客户端配置里实际写的 IP 和端口，它才是用户连的地方。节点换了 IP 而客户端没跟上时，探针应该报失败，而不是悄悄改测新 IP。
