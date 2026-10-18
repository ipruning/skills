# REALITY + HY2 客户端

生成任何客户端配置之前先读「输入」。Linux、Android、Windows 共用下面的 sing-box mixed profile；各平台只在它上面加自己的 TUN、VPN 和路由。Linux 的安装、TUN、systemd 和转发流量见 [linux-client.md](linux-client.md)。iOS／SFI 不在本包范围。

## 输入

```text
SERVER_IP
REALITY_SNI
UUID
REALITY_PUBLIC_KEY
REALITY_SHORT_ID
HY2_DOMAIN
HY2_PASSWORD
```

macOS Surge 原生 HY2 只要 `SERVER_IP`、`HY2_DOMAIN`、`HY2_PASSWORD`。只用一个 outbound 的平台只要那一个的子集。Tailscale 排除项、网卡名、服务实例名和已有 policy 名取自这台客户端本身，不从别的机器的模板抄。

值只能来自：

- 用户为这个目标给的；
- 这次为这台服务端生成、并留了脱敏对应关系的；
- 用户让读的那份服务端 secrets 文件或客户端配置，走已经确定的那条 SSH 路径。

不翻凭据缓存，不从别的 VPS 抄，不从已有 policy 反推密码，不为拿值换 SSH 身份。拿不到就停在带占位符的配置，说清缺哪几个值。

`REALITY_PRIVATE_KEY` 和 `HY2_PASSWORD` 不打印。客户端拿 REALITY 公钥，永远不拿私钥。第一次做协议测试之前，用证书核对 `HY2_DOMAIN`，用服务端实际配置核对 `REALITY_SNI`。

## 共用的 mixed profile

mixed 模式用来做短时间的协议冒烟：不接管路由，就能证明凭据和协议通。shell 里 export 代理变量不能当成平台的长期方案。

几条规则：

- VLESS 拨 `SERVER_IP`，用 `REALITY_SNI`、`REALITY_PUBLIC_KEY`、`REALITY_SHORT_ID`，带上所选版本要求的 uTLS。
- VLESS 的 `network` 不写，除非所选版本和目标平台要求显式写。写成 `tcp` 会把 UDP 关掉。
- HY2 拨 `SERVER_IP`，TLS server name 用 `HY2_DOMAIN`。
- HY2 的 `up_mbps`、`down_mbps` 不写，除非这条链路实测过、能撑住一个固定值；不写时的行为以所选版本的当前文档为准。
- `direct` 留作路由用的 outbound，不放进给用户选的 selector。
- 写上 `route.default_domain_resolver`。

```json
{
  "log": {
    "level": "warn",
    "timestamp": true
  },
  "dns": {
    "servers": [
      {
        "type": "local",
        "tag": "dns-local"
      }
    ],
    "final": "dns-local",
    "strategy": "ipv4_only"
  },
  "inbounds": [
    {
      "type": "mixed",
      "tag": "mixed-in",
      "listen": "127.0.0.1",
      "listen_port": 2080
    }
  ],
  "outbounds": [
    {
      "type": "selector",
      "tag": "proxy",
      "outbounds": ["vless-reality-out", "hy2-h3-out"],
      "default": "vless-reality-out"
    },
    {
      "type": "vless",
      "tag": "vless-reality-out",
      "server": "__SERVER_IP__",
      "server_port": 443,
      "uuid": "__UUID__",
      "flow": "xtls-rprx-vision",
      "tls": {
        "enabled": true,
        "server_name": "__REALITY_SNI__",
        "utls": {
          "enabled": true,
          "fingerprint": "chrome"
        },
        "reality": {
          "enabled": true,
          "public_key": "__REALITY_PUBLIC_KEY__",
          "short_id": "__REALITY_SHORT_ID__"
        }
      }
    },
    {
      "type": "hysteria2",
      "tag": "hy2-h3-out",
      "server": "__SERVER_IP__",
      "server_port": 443,
      "password": "__HY2_PASSWORD__",
      "tls": {
        "enabled": true,
        "server_name": "__HY2_DOMAIN__"
      }
    },
    {
      "type": "direct",
      "tag": "direct"
    }
  ],
  "route": {
    "default_domain_resolver": "dns-local",
    "final": "proxy"
  }
}
```

这份骨架靠 `HY2_DOMAIN` 的公网证书链。私有 CA 的协议测试，在 HY2 的 `tls` 里加 `"certificate_path": "__CA_CERT_PATH__"`（私有 CA 的根证书），不用 `insecure=true` 代替显式信任。

只验用户要的那部分。最小的 mixed 冒烟：

```bash
sing-box check -c client-mixed.json
sing-box run -c client-mixed.json
curl -fsS4 --proxy socks5h://127.0.0.1:2080 https://api.ipify.org
```

HY2 在这次要交付的范围里，或者怀疑的就是它，才切到 `hy2-h3-out` 再测一次。第二个 outbound 的测试只是它自己的证据，不是每个平台都要两个都测才算完成。

### 多个端点

只有用户想在多台服务器或多种传输之间按延迟自动选，才用 `urltest`。它不是按顺序的主备切换。读所选版本的 URLTest 文档，按需要选数据面证据，不从旧版本推断重试或断连行为。`interrupt_exist_connections` 要先想清楚：保住长连接和把已有连接挪走，哪个更要紧。

## macOS（Surge 原生 HY2）

这里只负责把 HY2 输入翻成 Surge 原生的 policy 写法。Surge 的 profile、增强模式、DNS、策略选择和路由归 `$surge`。

```ini
vps-1-hy2 = hysteria2, <HY2_DOMAIN>, 443, password=<HY2_PASSWORD>, sni=<HY2_DOMAIN>
```

- 密码不进聊天、日志、历史和进程参数。可选的带宽字段，链路没实测过就不写。
- Surge 不原生支持 VLESS REALITY。要在 Mac 上跑 REALITY 就得换客户端，那是另一个设计决定。
- 不把 Linux sing-box 的路由排除项抄进 Surge。服务端 IP 在 Mac 的实际路径上必须可达；Fake IP 或本机 VIF 上的 socket 不能证明公网可达。
- 已有 Snell policy 和它的服务健康归 `references/snell/`，不顺手生成新的备用 policy。policy 名、分组、Tailscale 规则和 MagicDNS 取自当前生效的 Surge profile，运行时探查和验证用 `$surge`。

## Windows

先用 mixed 模式：`127.0.0.1:2080` mixed inbound，selector 默认 `vless-reality-out`，`hy2-h3-out` 作备选。在 Windows 上它也是和 Tailscale 共存最稳的默认：不装系统路由，不和 Tailscale 网卡抢。

主机上有 sing-box CLI 时：

```powershell
sing-box.exe check -c .\client-mixed.json
sing-box.exe run -c .\client-mixed.json
curl.exe -fsS4 --proxy socks5h://127.0.0.1:2080 https://api.ipify.org
```

协议冒烟必须有 `SERVER_IP`。HY2 在范围里或正被怀疑时，再测一次 `hy2-h3-out`。

整机代理：不要套用 Linux TUN 的服务语义。先生成 mixed 配置；用户指定了能导入 sing-box JSON 并管理 TUN 的 Windows 客户端，就改写 outbound 部分，让那个客户端管 Windows 的网络状态。用户要整机代理又没说用哪个客户端，问清楚。

和 Tailscale 共存要实测：

```powershell
tailscale status
route print
Get-NetRoute -DestinationPrefix 100.64.0.0/10 -ErrorAction SilentlyContinue
Resolve-DnsName <tailnet-host>.ts.net -ErrorAction SilentlyContinue
Test-NetConnection <tailscale-peer-ipv4>
```

正常的样子：tailnet 路由仍归 Tailscale，MagicDNS 仍经 Tailscale 解析。所选客户端支持路由排除时，排除 `100.64.0.0/10` 和 `fd7a:115c:a1e0::/48`；不支持就留在 mixed 模式。

## Android（SFA）

从上面导入共用的 outbound 和 selector。mixed inbound 只能做按应用的协议冒烟；普通的 SFA 整机 profile 换成这个 TUN 基线：

```json
{
  "type": "tun",
  "tag": "tun-in",
  "address": [
    "172.19.0.1/30",
    "fdfe:dcba:9876::1/126"
  ],
  "mtu": 1500,
  "auto_route": true,
  "strict_route": true
}
```

按应用包含或排除，在 SFA 的 Android VPN 设置里配。普通的手机上用 SFA，不写 `auto_redirect`；只有测过的热点或中继转发场景才加，加之前核对所选客户端的 schema。不要把 Linux 的 `route_exclude_address` 做法抄过来：Android 的 VPN 归平台和客户端 app 管。

原生 Android 上，SFA 整机模式和 Tailscale app 用的都是 Android VPN 服务，不能承诺两个同时作为整机 VPN 运行：

- 需要访问 Tailscale：让 Tailscale 当活动 VPN，不同时开 SFA 整机模式。
- 需要 REALITY／HY2 整机代理：让 SFA 当活动 VPN，不假设这台设备还能连 Tailscale peer 或用 MagicDNS。

用户说某个客户端、ROM 或工作资料能让两个 VPN 共存，要实测这几项再说支持：Tailscale app 状态、SFA profile 是否生效、能否访问 `100.64.0.0/10` 里的 peer、能否解析 `*.ts.net`、经所选代理的出口 IP。

验收：先确认导入的 profile 带着 Android TUN inbound，启动时没有 schema、REALITY 或 TLS 错误。出口 IP、DNS、局域网、应用排除或第二个 outbound，在请求范围里或正被怀疑时才测。只有 mixed inbound 时，验到的只是显式走代理的那些应用流量。Tailscale 要紧时，两种 VPN 模式分开测；SFA 开着时指定的 tailnet peer 和 MagicDNS 都能用，才能说共存。
