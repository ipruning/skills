# Linux 客户端

用于 Linux 客户端、Linux 工作站和 VPS 到 VPS 的测试。工作站或专用客户端的最终形态是系统级 TUN。业务 VPS 或多服务主机默认用 mixed 模式：TUN 会改变每个服务的 DNS、出口和回程，这种主机上要用户接受这个影响范围才开 TUN。

共用的 outbound、selector、DNS 基线和 mixed 冒烟见 [clients.md](clients.md)。这里只管 Linux 的安装、系统级 TUN、转发流量、systemd 和路由。从 Clash／Mihomo 迁过来，TUN 验收后读 [linux-migration.md](linux-migration.md)。

## 安装

Debian/Ubuntu 用和服务端一样的官方 APT 源，版本按 [server.md](server.md#选版本) 的「选版本」选。源配好后只装客户端要的：

```bash
: "${SINGBOX_VERSION:?select the latest stable candidate from apt-cache policy}"
apt-get install -y "sing-box=$SINGBOX_VERSION" curl jq
systemctl daemon-reload
apt-mark hold sing-box
sing-box version
```

Arch Linux 优先用发行版的包，前提是它带 `with_utls` 和 systemd 的 `sing-box@.service`：

```bash
pacman -Qi sing-box
sing-box version
systemctl cat sing-box@.service
```

Arch 上同样遵守「选版本」里的规矩：不降级，跨版本先读迁移说明、用目标版本 `sing-box check`。渲染配置前确认所选二进制的 build tag 和 REALITY 的要求（REALITY 客户端必须开 uTLS），不照搬旧版本的假设。

## TUN

mixed 冒烟通过后再上 TUN。通过 SSH 启动 TUN 之前，必须满足其一：路由排除保护了当前的 SSH 路径、有回滚办法、或者这台机器可以随便扔。

### DNS

Linux 工作站的 TUN 默认只要 IPv4 答案：

```json
"dns": {
  "servers": [
    {
      "type": "local",
      "tag": "dns-local"
    }
  ],
  "final": "dns-local",
  "strategy": "ipv4_only"
}
```

IPv6 在 DNS、路由、软件源镜像和 curl 上都验证过之前，不用 `prefer_ipv4` 当长期默认。`prefer_ipv4` 仍会返回 AAAA，应用可能挑 IPv6 然后失败，而 IPv4 其实是通的。典型症状：有 AAAA 答案、IPv6 路由不通、同一个请求 `curl -4` 能成功。

### 路由

```json
"route": {
  "auto_detect_interface": true,
  "default_domain_resolver": "dns-local",
  "rules": [
    {
      "network": "icmp",
      "action": "route",
      "outbound": "direct"
    },
    {
      "process_name": "tailscaled",
      "action": "route",
      "outbound": "direct"
    },
    {
      "action": "sniff"
    },
    {
      "protocol": "dns",
      "action": "hijack-dns"
    },
    {
      "ip_is_private": true,
      "action": "route",
      "outbound": "direct"
    }
  ],
  "final": "proxy"
}
```

没有 Tailscale 就去掉 `tailscaled` 那条。VLESS 和 HY2 都带不了 ICMP：想让 `ping` 正常就让 ICMP 直连；不能暴露工作站的直连 ICMP 路径时，把那条换成显式 reject。

### TUN inbound

```json
{
  "type": "tun",
  "tag": "tun-in",
  "interface_name": "singtun0",
  "address": [
    "172.19.0.1/30",
    "fdfe:dcba:9876::1/126"
  ],
  "mtu": 1500,
  "auto_route": true,
  "auto_redirect": true,
  "strict_route": true,
  "route_exclude_address": [
    "__SERVER_IP__/32"
  ]
}
```

有 Tailscale 时，启动 TUN 前把 tailnet 网段也排除掉：

```json
"route_exclude_address": [
  "__SERVER_IP__/32",
  "100.64.0.0/10",
  "fd7a:115c:a1e0::/48"
]
```

一条 `__SERVER_IP__` 只有在两个协议拨同一个端点时才够。多端点的 selector 或 URLTest，启动 TUN 前要把每个不同的 outbound 服务端 IP 都加进 `route_exclude_address`，否则代理可能经 TUN 递归拨自己的某个候选。

固定的 tailnet 网段不是管理路径的全部。经 Tailscale 启动 TUN 之前，查清接受的子网路由、exit node 状态、MagicDNS、当前 SSH 来源和物理底层网络：

```bash
tailscale status --json | jq '{Self, Peer}'
ip rule
ip route show table 52
ss -tnp | grep -E '(:22\b|sshd)'
```

当前管理路径用到的每条路由都要保护好。经 SSH 测 TUN 时，SSH 客户端地址没被保护就加上，并加超时：

```bash
timeout 60s sing-box run -c tun-test.json
```

TUN 默认会劫持网卡 DNS；和 Tailscale MagicDNS 一起用时，按下面「验收」里的 Tailscale 检查确认 `*.ts.net` 仍能解析。

## 虚拟机和容器的转发流量

本机发出的流量、透明转发的流量、显式走代理的流量是三条不同的数据路径。本机 curl 成功只证明第一条。在 libvirt、容器或局域网网关主机上，`auto_redirect` 可能把转发流量也截走，哪怕 NAT、DHCP、DNS 和 ICMP 都正常。

`route_exclude_address` 按目的地址匹配。把下游子网加进去，管不到**源地址**是这个子网的连接。下游要直连时，在更宽的路由规则之前放一条按源地址绕过的规则，让它在内核预匹配阶段绕开 auto-redirect（只在 Linux 且开了 `auto_redirect` 时生效）：

```json
{
  "source_ip_cidr": ["__DOWNSTREAM_CIDR__"],
  "action": "bypass"
}
```

这只恢复直连转发，不会让 guest 或容器走宿主的代理。加了之后，分别证明下游 HTTPS 和宿主 TUN 都正常。

下游要走代理时，透明路径保持直连，另加一个只绑在私网网关地址上的 mixed inbound：

```json
{
  "type": "mixed",
  "tag": "downstream-mixed-in",
  "listen": "__PRIVATE_GATEWAY_IP__",
  "listen_port": __PRIVATE_PROXY_PORT__
}
```

在主机防火墙里按实际的 bridge／网卡和源网段限制这个 listener。不要图方便绑到通配地址、局域网或公网地址。配了 mixed 用户就把凭据生成到只有属主能读的配置里；认证只是多一道门，不能代替防火墙。在 guest 里显式给包管理器或进程配代理，按需测 HTTP 和 SOCKS 两种 DNS 行为：

```bash
curl -fsS --proxy http://__PRIVATE_GATEWAY_IP__:__PRIVATE_PROXY_PORT__ \
  https://api.ipify.org
curl -fsS --proxy socks5h://__PRIVATE_GATEWAY_IP__:__PRIVATE_PROXY_PORT__ \
  https://api.ipify.org
```

保留这个 listener 前要有四样证据：socket 地址符合预期、防火墙按来源限制、一次真实的下游传输走了所选 outbound、一个未授权来源连不上。`systemctl is-active` 和监听中的 socket 只能证明控制面状态。

不同的软件源可能要走不同的路。拿实际失败的 URL 分别经下游直连和显式代理比一比，只给受影响的仓库主机换路径。APT 用它自己按主机的 `DIRECT`／代理设置，不要用全局 shell 的 `HTTP(S)_PROXY`；核对生成的实际配置和包摘要。不要因为某个大包走一条路更快，就把所有 Ubuntu、PGDG、厂商或内部仓库都塞进那条路。

## 常驻服务

启用或重启常驻服务之前，盘点已有的 sing-box、Snell、xray、Mihomo 等代理的 unit、进程和 listener。盘点读不出来或有归属不明的，就停下；别等 TUN 已经改了主机路由才发现端口冲突：

```bash
system_units="$(systemctl list-unit-files --no-pager)" || {
  echo "cannot read system proxy unit inventory" >&2
  exit 1
}
printf '%s\n' "$system_units" | grep -Ei 'sing-box|snell|xray|mihomo' || true
user_units="$(systemctl --user list-unit-files --no-pager)" || {
  echo "cannot read user proxy unit inventory" >&2
  exit 1
}
printf '%s\n' "$user_units" | grep -Ei 'sing-box|snell|xray|mihomo' || true
ps -eo pid,ppid,user,comm,args | grep -Ei 'sing-box|snell|xray|mihomo' | grep -v grep || true
ss -lntup
```

配置放在 `/etc/sing-box`，用包自带的 systemd 模板，`CAP_NET_ADMIN` 由 systemd 处理。候选校验、上线、就绪和回滚都在下面这一段里：

```bash
set -eu

sudo install -d -m 755 /etc/sing-box
candidate=/etc/sing-box/<name>.json.new
target=/etc/sing-box/<name>.json
backup="${target}.bak.$(date +%Y%m%d-%H%M%S)"
unit=sing-box@<name>.service

sudo install -m 600 -o sing-box -g sing-box client-tun.json "$candidate"
sudo sing-box check -c "$candidate"
sudo sing-box format -w -c "$candidate"
sudo sing-box check -c "$candidate"

had_target=0
was_enabled=0
was_active=0
if sudo test -f "$target"; then
  had_target=1
  sudo install -m 600 -o sing-box -g sing-box "$target" "$backup"
fi
sudo systemctl is-enabled --quiet "$unit" && was_enabled=1 || true
sudo systemctl is-active --quiet "$unit" && was_active=1 || true

rollback() {
  if test "$had_target" -eq 1; then
    sudo install -m 600 -o sing-box -g sing-box "$backup" "$target"
  else
    sudo rm -f "$target"
  fi
  if test "$was_active" -eq 1; then
    sudo systemctl restart "$unit" || true
  else
    sudo systemctl stop "$unit" || true
  fi
  if test "$was_enabled" -eq 1; then
    sudo systemctl enable "$unit" || true
  else
    sudo systemctl disable "$unit" || true
  fi
}

sudo install -m 600 -o sing-box -g sing-box "$candidate" "$target"
if ! sudo systemctl enable "$unit"; then
  rollback
  exit 1
fi
if ! sudo systemctl restart "$unit"; then
  rollback
  exit 1
fi

ready=0
for _ in {1..20}; do
  if ip link show singtun0 >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.25
done
if test "$ready" -ne 1; then
  rollback
  exit 1
fi
sudo rm -f "$candidate"
ip -brief addr show singtun0
```

## 验收

首次验收用 `log.level = info`，这样能看到选中的 outbound；路由和协议断言都过了再切回 `warn`。长期跑 `info` 会记下每个连接，探测或编译时能产生几万行 journal。

```bash
env -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
  curl -fsS4 --noproxy "*" https://api.ipify.org
env -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
  -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
  curl -fsSIL4 --noproxy "*" https://www.google.com | sed -n '1,5p'
getent ahostsv4 openai.com | head
resolvectl query --type=AAAA openai.com || true
curl -6 -m 10 --noproxy "*" https://openai.com || true
# On Arch-family hosts, repeat the getent/curl check against the actual package
# mirrors in use to confirm they resolve and fetch IPv4-only, e.g.:
#   getent ahosts <mirror-host> | awk '{print $1}' | sort -u
#   curl -fsSIL --noproxy "*" https://<mirror-host>/<db-path> | sed -n '1p'
ip addr show singtun0
systemctl is-active sing-box@<name>.service
systemctl is-enabled sing-box@<name>.service
ping -n -c 3 1.1.1.1

curl --http3-only -m 25 -fsS -o /dev/null \
  -w 'http3=%{http_code} remote=%{remote_ip}\n' \
  --noproxy "*" https://cloudflare-quic.com/
```

`ipv4_only` 下，`resolvectl query --type=AAAA` 应该报没有记录，`curl -6` 应该解析失败。不要用 `getent ahostsv6` 断言：DNS 没返回 AAAA 时，glibc 也可能打印 IPv4 映射的 `::ffff:` 地址。

selector 默认是 `vless-reality-out` 时，HTTP/3 请求必须成功，journal 里必须有 VLESS 的 packet connection。curl 不支持 HTTP/3 就换一个支持 UDP 的客户端，日志断言不变。

切回 `warn` 之前，先要有正面的路由证据：

```bash
if ! validation_log="$(journalctl -u sing-box@<name>.service --since "5 minutes ago" --no-pager)"; then
  echo "cannot read the bounded sing-box validation journal" >&2
  exit 1
fi
test -n "$validation_log" || { echo "validation journal is empty" >&2; exit 1; }
grep -F 'inbound/tun[tun-in]: started at singtun0' <<<"$validation_log" >/dev/null \
  || { echo "missing TUN startup evidence" >&2; exit 1; }
grep -E 'outbound/vless\[.*\]: outbound packet connection' <<<"$validation_log" >/dev/null \
  || { echo "missing VLESS packet evidence" >&2; exit 1; }
```

新开 Bash 和 Zsh 的登录 shell，再断言一次没有代理环境变量；只看当前 shell 不够，过时的启动 hook 可能下次登录才冒出来。然后把常驻的日志级别切回 `warn`，重启，制造一些有代表性的 TCP、UDP、DNS 和 ICMP 流量，等服务闲下来。

叫它「常驻 TUN」之前，做完稳态验证：

```bash
test -z "${HTTP_PROXY-}${HTTPS_PROXY-}${ALL_PROXY-}${http_proxy-}${https_proxy-}${all_proxy-}"
if ! recent_log="$(journalctl -u sing-box@<name>.service --since "5 minutes ago" --no-pager)"; then
  echo "cannot read the bounded sing-box journal" >&2
  exit 1
fi
unexpected_log="$(
  grep -Ei 'error|fatal|panic|UDP is not supported' <<<"$recent_log" \
    | grep -Ev 'connection upload closed: stream [0-9]+ canceled by remote with error code 0' \
    || true
)"
if test -n "$unexpected_log"; then
  printf '%s\n' "$unexpected_log" >&2
  exit 1
fi
```

前面有了 `info` 级的正面断言后，稳态的 `warn` journal 是空的也正常。受控的测试客户端拿到结果后可能取消 QUIC 流，sing-box 会以 `ERROR` 级别记 `connection upload closed: stream <n> canceled by remote with error code 0`。只忽略这一种形状，其他错误记录和命令失败照样不通过。

当前 SSH 或访问 peer 走 Tailscale 时，开了 TUN 之后再验 tailnet 路由：

```bash
ip route get <tailscale-peer-ipv4>
ip -6 route get <tailscale-peer-ipv6>
tailscale ping <tailscale-peer-ipv4>
getent hosts <tailnet-host>.ts.net
tailscale netcheck
```

正常的样子：peer 路由仍在 `tailscale0` 上，MagicDNS 可用，每条接受的子网路由都能用。配了子网路由或 exit node 时，只 ping 通一个 peer 不够。

### 常见日志

正常的日志：

```text
inbound/tun[tun-in]: started at singtun0
dns: exchanged A api.ipify.org
outbound/vless[...]: outbound connection
outbound/vless[...]: outbound packet connection
```

- 选着 VLESS 却出现 `UDP is not supported by outbound: proxy`：VLESS outbound 被限成了 `"network": "tcp"`。去掉这个限制，`sing-box check`，重启，再测 HTTP/3。用户没明确要按协议分流，就不要把所有 UDP 悄悄导到 HY2。
- `curl -I` 显示 `HTTP/1.1 200 Connection established`：测试还在走环境变量里的代理。清掉代理变量，加 `--noproxy "*"` 重测。
- ping 不通：看 ICMP 的 direct 或 reject 规则在不在。不要把 ICMP 路由给 VLESS 或 HY2。

## 性能

TUN 的 `stack` 保持所选版本文档里的默认值，只在诊断能复现的兼容问题时才设。物理底层 MTU 是 `1500` 的工作站，用这个保守基线：

```json
{
  "mtu": 1500,
  "auto_route": true,
  "auto_redirect": true,
  "strict_route": true
}
```

MTU 从物理底层的值开始，一般是 `1500`。主要的 Linux 转发路径由 `auto_redirect` 处理，调大虚拟 TUN 的 MTU 不是白送的吞吐。要保留更大的值，先测 HTTP/3、Docker、Tailscale、丢包和同一个固定下载。

### HY2 带宽参数

HY2 的 `up_mbps`、`down_mbps` 两个方向分开换算：不写 `up_mbps` 时上传用 BBR；写了正的 `down_mbps`，在服务端接受客户端带宽时下载用 Brutal。服务端的上限和 `ignore_client_bandwidth` 会改变协商结果。要用两个方向不一样的策略，先读当前版本 sing-quic 的 `hysteria2/client.go` 和 `hysteria2/service.go` 确认协商逻辑。固定的下载目标不能悄悄把上传也限住。

先读所选版本的当前文档，实测链路，再决定用自动拥塞控制还是固定的 Brutal 值。链路变了、开始丢包、或负载下延迟明显变差，就去掉固定值。从一个客户端派生到别处的配置，除非目标链路独立通过了同样的对比，否则去掉这些链路专属的带宽值。

### UDP 缓冲

不要只因为 `net.core.rmem_max` 看着小就套一段通用的 UDP sysctl。HY2 有流量时看线上 sing-box socket 和内核丢包计数：

```bash
ss -u -a -m -p | grep -A2 -B1 sing-box
nstat -asz | grep -E 'Udp(InErrors|RcvbufErrors|SndbufErrors)'
```

- sing-box socket 的收发缓冲已经接近 `16 MiB`，传输期间 UDP 错误计数也不涨，就别动 sysctl。
- 在可比的负载前后记下 PID、peer、`rb`、`tb` 和 socket 的 `d`。全局计数包含别的 socket，历史上的非零值不代表当前 HY2 有问题。socket 重建会把 `d` 清零，刚重启后是 0 什么也证明不了。两端都看负载带来的增量。
- QUIC 会主动给新 socket 申请大缓冲（约 8 MiB，`skmem` 里显示约 16 MiB）。不开混淆、进程有 `CAP_NET_ADMIN` 时（包自带的 `sing-box@.service` 就有），它能越过 `rmem_max`、`wmem_max`，调这两个上限没用。开了 Salamander 或 Gecko 混淆，或者进程没有 `CAP_NET_ADMIN`（比如手动跑的 mixed 进程）时，申请会被这两个上限限住；确认被限住后，测试调大它们，再看**新建的** socket，已有的 socket 不会变。缓冲上限不等于当前占用的内存。
- 只把能重复的改进持久化：单独一个 `/etc/sysctl.d/` 文件，带回滚。主机全局的 sysctl 写入交给 `$linux-server`。
- 不要把客户端的调整推到本来健康的服务端 inbound 上，也不要把一次测出来的缓冲大小推成机队默认值。设置只留在实际验证过的那个端点和网络路径上。

内核的 TCP BBR 影响的是外层 VLESS 的 TCP 发送端，不调 HY2 用户态 QUIC 的拥塞控制。不要仪式性地把每个客户端从 Cubic 换掉；保留主机级的拥塞控制改动之前，确认当前的发送算法、qdisc，并做上传和下载的对比。

## Linux 上的推荐默认

- sing-box TUN 跑成 systemd 服务；
- 不在 shell 里长期 export 代理变量；
- selector 默认 `vless-reality-out`，VLESS 同时承载 TCP 和 UDP；
- HY2 作为手动选择的高速备选。

UDP 干净、同一路径对比证明 HY2 更好时才用 HY2。热点或丢包的路径上，REALITY 保持为稳定的默认。
