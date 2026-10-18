# REALITY + HY2 服务端

适用于 Debian 12/13 或 Ubuntu 24.04 的 systemd VPS，跑 sing-box 稳定版：TCP/443 上的 VLESS REALITY Vision，加 UDP/443 上带 HTTP/3 masquerade 的 Hysteria2。非 APT、非 systemd、只有容器、或防火墙已经很复杂的主机，先改造这份流程再用。

## 输入

完整的 REALITY + HY2 部署要：

```text
SERVER_IP
HY2_DOMAIN
REALITY_SNI
REALITY_HANDSHAKE_HOST，一般和 REALITY_SNI 相同
REALITY_HANDSHAKE_PORT，一般是 443
MASQUERADE_URL，proxy 模式用的稳定 HTTPS 源站，用户自己的或特意选定的
DNS_RESOLVER_IP，这次 DNS 检查用的外部 resolver；直接查权威 nameserver 时不需要
```

`HY2_DOMAIN` 由用户指定。长期使用的 `REALITY_SNI`、`REALITY_HANDSHAKE_HOST` 和 proxy 模式的 `MASQUERADE_URL` 也要用户指定或已经选定过，不从「部署一台」的要求、别的服务器或全局默认值推出来。缺哪个，就只停下依赖它的配置，说清缺口，其余诊断照做。

公开域名的一次性 DNS 取证，可以自己挑合适的 resolver 或权威 nameserver，记下用的是哪个。私有、敏感域名不发给用户没认可的第三方 resolver。长期用的 DNS 和 IP 回显目标见 [monitoring.md](monitoring.md)。

一次性的 HY2 验收可以用自带响应的 string masquerade，不需要 `MASQUERADE_URL` 或第三方源站；它只证明 HTTP/3 masquerade 的行为，不能当长期掩护源站。

`REALITY_SNI` 和 `REALITY_HANDSHAKE_HOST` 定不下来、用户又明确接受只上 HY2 时，可以只上 HY2（下称 HY2-only）：不建 REALITY inbound、不生成 REALITY 密钥、不开 TCP/443。REALITY 报为未配置、未验证，不能把这次部分验收写成完整的 REALITY + HY2。

Cloudflare 上的 DNS 记录：

```text
Type: A
Name: chosen host, for example vps-1
Content: SERVER_IP
Proxy status: DNS only
TTL: Auto
AAAA: omit unless server and client IPv6 are verified
```

## 动手前先看

```bash
set -eu
. /etc/os-release
printf 'os=%s %s\n' "$ID" "$VERSION_ID"
systemctl --version | sed -n '1p'
timedatectl show -p NTPSynchronized -p Timezone
sshd -T | awk '$1 ~ /^(port|listenaddress|permitrootlogin|passwordauthentication|pubkeyauthentication)$/ { print }'
ss -lntup
ufw status verbose 2>/dev/null || true
nft list ruleset 2>/dev/null || true
```

选安装路径之前，记下装着的 sing-box 版本、相关 unit 名、配置路径、运行中的进程、listener 归属和防火墙由谁管。已有的 sing-box、Snell、xray、Mihomo 或别的代理是审计对象，不是默认要替换掉的。listener 或 unit 归属不明时，停下，不部署、不清理、不抢端口。

遇到这些情况，停下，不要杀不认识的进程：

- TCP/443 或 UDP/443 已经有主人。
- 计划用 Certbot standalone，但 TCP/80 被占了。
- 不知道当前的 SSH 端口或管理来源。
- 主机上已有归属不清的防火墙规则。
- 改防火墙之前没有第二个 SSH 会话或云厂商控制台。

申请证书前，从外部 resolver 确认公网 DNS：

```bash
dig +short A "$HY2_DOMAIN" @"$DNS_RESOLVER_IP"
dig +short AAAA "$HY2_DOMAIN" @"$DNS_RESOLVER_IP"
```

A 必须包含 `SERVER_IP`；不打算支持 IPv6 时 AAAA 必须为空。云厂商安全组要放行和主机防火墙一样的端口，只看 UFW 证明不了公网可达。

几个容易看错的地方：

- 在开着 Surge、Mihomo 或别的 Fake IP 实现的客户端上，落在 `198.18.0.0/15` 里的答案是合成的，不是公网 DNS 证据。按上面的一次性 DNS 规则查外部 resolver，或直接查该域名权威委派里的 nameserver，记下来源。
- macOS 开着 Surge 增强模式时，`nc -z` 可能报 TCP 连接成功：本机透明代理接住了 socket，哪怕 VPS 上根本没有对应的 listener 或防火墙规则。这个结果不能当公网端口的证据，要看协议认证结果，加上服务端 listener 和防火墙计数器。

在 VPS 上验证 REALITY 目标：

```bash
openssl s_client \
  -connect "$REALITY_HANDSHAKE_HOST:$REALITY_HANDSHAKE_PORT" \
  -servername "$REALITY_SNI" \
  -tls1_3 \
  -alpn h2 </dev/null 2>/dev/null \
  | grep -E 'Protocol|ALPN protocol|Verify return code'

curl -fsSI "https://$REALITY_SNI/" | grep -Ei '^(HTTP/|location:)'
```

要求 TLS 1.3、ALPN `h2`、证书校验成功、没有跳到别的主机名。优先选网络位置和延迟都离 VPS 近的目标，不用一个固定的全局默认。

单独验证选定的 masquerade 源站：

```bash
curl -fsS -o /dev/null --connect-timeout 8 --max-time 20 "$MASQUERADE_URL"
```

## 选版本

用操作当时官方源里的最新稳定版，不写死补丁版本。渲染配置前，先看装着的和源里的候选：

```bash
sing-box version | sed -n '1p'
apt-cache policy sing-box
```

装源里报的候选版本。`SINGBOX_VERSION` 可以显式写成那个确切版本以便复现，但不能借它悄悄降级已经装着的二进制：装着的比候选还新，就停下先理清源或迁移状态。

任何有计划的升级（包括补丁版本）：先读目标版本的迁移说明和配置文档，渲染候选配置，用目标版本的 `sing-box check` 校验，再去掉 hold 升级。源里有新包不代表配置兼容。

## 安装

这次部署里不做整机发行版升级，那是另一个维护决定。

```bash
apt-get update
apt-get install -y curl ca-certificates dnsutils jq openssl certbot

# Install only the selected firewall owner when it is not already present:
# apt-get install -y nftables
# apt-get install -y ufw

mkdir -p /etc/apt/keyrings
curl -fsSL https://sing-box.app/gpg.key -o /etc/apt/keyrings/sagernet.asc
chmod a+r /etc/apt/keyrings/sagernet.asc
cat >/etc/apt/sources.list.d/sagernet.sources <<'EOF'
Types: deb
URIs: https://deb.sagernet.org/
Suites: *
Components: *
Enabled: yes
Signed-By: /etc/apt/keyrings/sagernet.asc
EOF
apt-get update
candidate_version="$(apt-cache policy sing-box | awk '/Candidate:/ { print $2; exit }')"
SINGBOX_VERSION="${SINGBOX_VERSION:-$candidate_version}"
: "${SINGBOX_VERSION:?select the latest stable candidate from apt-cache policy}"
test "$SINGBOX_VERSION" != "(none)" || exit 1
apt-get install -y "sing-box=$SINGBOX_VERSION"
systemctl daemon-reload
apt-mark hold sing-box

version_text="$(sing-box version | sed -n '1p')"
printf '%s\n' "$version_text"
```

hold 防止无人值守时被换掉版本。

## 防火墙

全新的单用途 VPS 选 UFW 时，启用前先放行每个生效的 SSH 端口：

```bash
sshd -T | awk '$1 == "port" { print $2 }' | sort -u \
  | while read -r ssh_port; do ufw allow "$ssh_port/tcp" comment ssh-management; done
ufw allow 80/tcp comment certbot-http
ufw allow 443/tcp comment sing-box-reality
ufw allow 443/udp comment sing-box-hy2
ufw --force enable
ufw status verbose
```

HY2-only 时去掉 `443/tcp` 那条。启用 UFW 后新开一个 SSH 连接确认能进。主机已经在用 nftables、iptables、云厂商防火墙代理或按来源限制的 SSH 规则时，改造现有防火墙，不要在上面再启用 UFW。装依赖时不能引入第二个防火墙管理者：nftables 主机上不要因为这里写了 UFW 就去装、去开 UFW。

用户要保留同机的 Snell 作备用时，才留它的 listener，并在防火墙里保留它实际的端口和传输。改完防火墙重跑它的 policy 测试。最小化的 UFW 规则可能让 Snell 支撑的 Ponte NAT 从 Type A 变成 Type C，普通代理却照常能用；怎么判断、要不要放行临时 UDP 端口，见 [snell/tuning.md](../snell/tuning.md#surge-ponte-的-nat-类型是-type-c)。

## 证书

Certbot standalone 要求 TCP/80 空着且公网可达。Let's Encrypt 不发到期提醒邮件，也不保存 ACME 账号的邮箱，所以不要向用户要邮箱，到期告警交给监控：

```bash
certbot certonly \
  --standalone \
  --preferred-challenges http \
  -d "$HY2_DOMAIN" \
  --register-unsafely-without-email \
  --agree-tos \
  --non-interactive
```

deploy hook 不能重启一份无效的配置：

```bash
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat >/etc/letsencrypt/renewal-hooks/deploy/restart-sing-box.sh <<'EOF'
#!/bin/sh
set -eu
sing-box check -c /etc/sing-box/config.json
systemctl try-restart sing-box.service
EOF
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/restart-sing-box.sh
find -L /etc/letsencrypt/renewal-hooks/deploy -maxdepth 1 -type f -perm /111 -printf '%f\n'
```

Certbot 按可执行位挑 deploy hook，文件名带 `.bak` 后缀也照样会跑。备份挪出这个目录，或者去掉可执行位；上面的清单里只能有预期的 hook。

timer 负责续期，不负责到期告警。启用它，并把包括 deploy hook 在内的整条续期路径验一遍：

```bash
systemctl enable --now certbot.timer
systemctl is-enabled certbot.timer
systemctl is-active certbot.timer
systemctl list-timers certbot.timer --no-pager
certbot renew --dry-run --run-deploy-hooks --no-random-sleep-on-renew
```

`--no-random-sleep-on-renew` 只用在这次手动验证；timer 保留 Certbot 默认的随机延迟，免得很多主机同时续期。

TCP/443 归 REALITY，普通的 TCP/443 TLS 探测看不到 HY2 的证书。要长期监控，用 `$monitoring` 配 [monitoring.md](monitoring.md) 里的协议断言；没配就报未配置。

### 一次性 REALITY 夹具

要做协议端到端测试、又没有外部握手源站时，用 [testing.md](testing.md#一次性-reality-源站) 里的一次性源站：把 `REALITY_HANDSHAKE_HOST`／`REALITY_HANDSHAKE_PORT` 指向它，按下面「暂存和上线」换配置，测完用同一段的备份恢复。

## Secret

```bash
install -d -m 700 /etc/sing-box
UUID="$(sing-box generate uuid)"
KEYS="$(sing-box generate reality-keypair)"
REALITY_PRIVATE_KEY="$(printf '%s\n' "$KEYS" | awk -F': ' '/PrivateKey/ {print $2}')"
REALITY_PUBLIC_KEY="$(printf '%s\n' "$KEYS" | awk -F': ' '/PublicKey/ {print $2}')"
REALITY_SHORT_ID="$(openssl rand -hex 8)"
HY2_PASSWORD="$(openssl rand -hex 32)"
```

`short_id` 是偶数长度、最多 16 位的十六进制串（也可以为空）；`openssl rand -hex 8` 正好 16 位。奇数长度会被 `sing-box check` 拒绝，超过 16 位会让它直接 panic，报不出清楚的原因。

HY2-only 只生成 `HY2_PASSWORD`。不生成、不保存没有 inbound 用的 UUID、REALITY 密钥对或 short ID。

写 `/root/sing-box-secrets.txt`，权限 `600`，包含这些键：

```text
SERVER_IP
HY2_DOMAIN
REALITY_SNI
REALITY_HANDSHAKE_HOST
REALITY_HANDSHAKE_PORT
UUID
REALITY_PRIVATE_KEY
REALITY_PUBLIC_KEY
REALITY_SHORT_ID
HY2_PASSWORD
```

HY2-only 的 secrets 文件只有 `SERVER_IP`、`HY2_DOMAIN`、`HY2_PASSWORD`。服务端和客户端都确实要开混淆时，才生成和保存混淆密码。

## 服务端配置

HY2-only 整个去掉 VLESS inbound，只渲染 Hysteria2 inbound、direct outbound 和 route；线上配置里不留占位或没用的 REALITY 字段。

TCP/443 上的 VLESS REALITY：

```json
{
  "type": "vless",
  "tag": "vless-reality-in",
  "listen": "0.0.0.0",
  "listen_port": 443,
  "users": [
    {
      "name": "<user>",
      "uuid": "__UUID__",
      "flow": "xtls-rprx-vision"
    }
  ],
  "tls": {
    "enabled": true,
    "server_name": "__REALITY_SNI__",
    "reality": {
      "enabled": true,
      "handshake": {
        "server": "__REALITY_HANDSHAKE_HOST__",
        "server_port": __REALITY_HANDSHAKE_PORT__
      },
      "private_key": "__REALITY_PRIVATE_KEY__",
      "short_id": ["__REALITY_SHORT_ID__"],
      "max_time_difference": "1m"
    }
  }
}
```

UDP/443 上的 Hysteria2：

```json
{
  "type": "hysteria2",
  "tag": "hy2-h3-in",
  "listen": "0.0.0.0",
  "listen_port": 443,
  "users": [
    {
      "name": "<user>",
      "password": "__HY2_PASSWORD__"
    }
  ],
  "tls": {
    "enabled": true,
    "server_name": "__HY2_DOMAIN__",
    "certificate_path": "/etc/letsencrypt/live/__HY2_DOMAIN__/fullchain.pem",
    "key_path": "/etc/letsencrypt/live/__HY2_DOMAIN__/privkey.pem"
  },
  "masquerade": {
    "type": "proxy",
    "url": "__MASQUERADE_URL__",
    "rewrite_host": true
  }
}
```

一次性协议测试、没有选定外部源站时，把 proxy masquerade 换成固定响应。它不是生产用的掩护源站：

```json
{
  "type": "string",
  "status_code": 200,
  "content": "temporary Hysteria2 endpoint\n"
}
```

完整配置用 direct outbound 和 `route.final = direct`。只有一个 IP 时，普通 TCP HTTPS 访问 `HY2_DOMAIN` 进的是 REALITY，不是 Hysteria2 的 masquerade；只有 UDP/443 上的 HTTP/3 才会走到 masquerade。

proxy masquerade 的源站只影响未认证的 HTTP/3 掩护流量。优先用用户自己控制的源站；选了公共源站就从 VPS 上验一下，它回 `2xx` 不能当 HY2 认证通过的证据。

生产配置用 `log.level = warn`。验证或诊断要看连接级证据时临时切到 `info`，看完切回 `warn`；否则公网扫描和逐连接的 info 日志会把 journal 撑大。

服务端和客户端的 HY2 `up_mbps`、`down_mbps` 默认留空。服务端留空不等于一定用 BBR：客户端带了带宽，仍可能协商出 Brutal，协商规则见 [linux-client.md](linux-client.md#hy2-带宽参数)。固定的客户端可以在实测后选用 Brutal 值，但这个客户端专属的速率不能变成服务端模板的默认值。

## 暂存和上线

渲染出的配置先写到 `/etc/sing-box/config.json.new`，不直接覆盖线上文件。校验、格式化、再校验，留好回滚副本：

```bash
set -eu
candidate=/etc/sing-box/config.json.new
target=/etc/sing-box/config.json
backup="${target}.bak.$(date +%Y%m%d-%H%M%S)"
unit=sing-box.service

sing-box check -c "$candidate"
sing-box format -w -c "$candidate"
sing-box check -c "$candidate"

had_target=0
was_enabled=0
was_active=0
if test -f "$target"; then
  had_target=1
  install -m 600 -o root -g root "$target" "$backup"
fi
systemctl is-enabled --quiet "$unit" && was_enabled=1 || true
systemctl is-active --quiet "$unit" && was_active=1 || true

rollback() {
  if test "$had_target" -eq 1; then
    install -m 600 -o root -g root "$backup" "$target"
  else
    rm -f "$target"
  fi
  if test "$was_active" -eq 1; then
    systemctl restart "$unit" || true
  else
    systemctl stop "$unit" || true
  fi
  if test "$was_enabled" -eq 1; then
    systemctl enable "$unit" || true
  else
    systemctl disable "$unit" || true
  fi
}

install -m 600 -o root -g root "$candidate" "$target"

if ! systemctl enable "$unit"; then
  rollback
  exit 1
fi
if ! systemctl restart "$unit"; then
  rollback
  exit 1
fi
# `systemctl restart` can return while a simple service is active but its sockets
# are not ready. Poll the expected listener set while the same MainPID remains
# active; do not turn one immediate ss sample into a failed deployment.
EXPECTED_TCP_443=1 # use 0 for an HY2-only rollout
main_pid="$(systemctl show sing-box -p MainPID --value)"
test "$main_pid" -gt 1
ready=0
for _ in $(seq 1 100); do
  test "$(systemctl show sing-box -p MainPID --value)" = "$main_pid" || break
  tcp_ready=0
  udp_ready=0
  ss -H -ltn 'sport = :443' | grep -q . && tcp_ready=1
  ss -H -lun 'sport = :443' | grep -q . && udp_ready=1
  if test "$udp_ready" -eq 1 \
    && { test "$EXPECTED_TCP_443" -eq 0 || test "$tcp_ready" -eq 1; }; then
    ready=1
    break
  fi
  sleep 0.1
done
if test "$ready" -ne 1; then
  rollback
  exit 1
fi
rm -f "$candidate"
```

这个 rollback 覆盖配置安装、unit 启用和本机 listener 就绪。外部协议验证期间留着备份，作手动恢复用；本机这一步回滚了，不代表远端协议状态也验过或恢复了。

## 验收

```bash
sing-box check -c /etc/sing-box/config.json
systemctl is-active sing-box
systemctl is-enabled sing-box
ss -lntup | grep -E ':443\b'
openssl x509 \
  -in "/etc/letsencrypt/live/$HY2_DOMAIN/fullchain.pem" \
  -noout -subject -enddate
systemctl is-enabled certbot.timer
systemctl is-active certbot.timer
test -x /etc/letsencrypt/renewal-hooks/deploy/restart-sing-box.sh
certbot renew --dry-run --run-deploy-hooks --no-random-sleep-on-renew
```

预期的 listener：

```text
tcp 0.0.0.0:443 sing-box
udp 0.0.0.0:443 sing-box
```

HY2-only 只预期 UDP/443 的 sing-box listener；TCP/443 上要是有 listener，必须另外查清是谁的。

要说这次部署完成，必须有外部客户端：

- 认证后的 REALITY 请求返回 `SERVER_IP`，服务端日志里出现预期的 VLESS 用户；
- 认证后的 HY2 请求返回 `SERVER_IP`，服务端日志里出现预期的 Hysteria2 用户；
- 对 `HY2_DOMAIN` 的 HTTP/3 请求返回配置的 masquerade 响应；
- HY2 不通时，云厂商和主机防火墙的计数器显示 UDP/443 到了主机。

REALITY + HY2 的范围要两种协议都测过。HY2-only 要认证后的 HY2 测试和 HTTP/3 masquerade 断言，REALITY 报为未配置、未验证。

外部探测前后各记一次 `MainPID` 和 `NRestarts`：PID 不变，重启次数不增。改完防火墙后从控制机新开 SSH 连接确认。看一段有界的 journal，把下面这些受控探测产生的记录和其他 `error`、`fatal`、`panic` 分开：

- 公网扫描器随机的无效 REALITY 握手是正常的。受控的未认证 TLS 回落探测，能完成 TLS、ALPN 和证书校验，然后以 `ERROR` 级别记一行 `REALITY: processed invalid connection`。这一行要和那次有界的回落探测对得上；认证客户端测试期间出现同样的行就是失败。
- 有界的 Surge 或 HTTP/3 探测读完结果会立即关流，sing-box 可能以 `ERROR` 级别记 `connection upload closed: stream <n> canceled by remote with error code 0`。在探测窗口内、服务在运行且没重启时，这一行不是崩溃；其他形状的错误照样要查。
- systemd 正常停止、退出状态 0，是外部停掉的，不是 sing-box 崩溃。
- 整机 journal 审计时，`[UFW BLOCK]` 记录先归为防火墙丢包，不要算成内核故障。需要边缘证据时保留有上限的底层防火墙日志；关掉它是有意放弃证据，不是日志健康的通用修法。

## 性能基线

不装通用的网络调优包。先读当前的 TCP 拥塞控制、qdisc、HY2 实际的 socket buffer 和 UDP 丢包计数：

```bash
sysctl net.ipv4.tcp_congestion_control net.ipv4.tcp_available_congestion_control
sysctl net.core.default_qdisc net.core.rmem_max net.core.wmem_max
ss -u -a -m -p | grep -A2 -B1 sing-box
nstat -az | grep -E 'Udp(InErrors|RcvbufErrors|SndbufErrors)|TcpRetransSegs'
```

长 RTT 的 VLESS 服务端，BBR 加 `fq` 是合理的目标，但要实测，不是无条件的部署步骤。已有能用的 BBR/fq 就保持。没有同一路径的前后对比，不换内核或拥塞控制。

Hysteria 建议 Linux 上 UDP 收发缓冲上限设 `16 MiB`。全局 sysctl 显示的值更小时，进程也可能已经拿到了大缓冲，所以以 `ss` 里的 `skmem` 为准。只有线上 sing-box socket 确实偏小、并且有 UDP 错误或能重复的 HY2 瓶颈时，才在 `/etc/sysctl.d/` 单独写一个覆盖文件，写完再看 socket 和计数器。
