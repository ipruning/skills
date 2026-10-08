# 测试、调优和核对

这里是按需取用的证据工具箱，不是必须全跑的验收脚本。按目标平台、怀疑点和要交付的结果，挑最小的一组检查，报告看到了什么、没看到什么。

## 别混测试面

```text
Server raw baseline:
  VPS -> Speedtest server

Protocol/client test:
  Client -> proxy protocol -> VPS -> target

Surge policy test:
  Surge policy -> target

Linux TUN test:
  system traffic -> sing-box TUN -> proxy protocol -> VPS -> target

Forwarded direct test:
  guest/container -> host forward/NAT -> direct uplink -> target

Forwarded explicit-proxy test:
  guest/container -> private mixed inbound -> selected outbound -> target
```

不能拿服务端裸测速推客户端的代理性能。环境变量代理测出来的不算 Linux TUN 的最终证据；最终证据要清掉代理变量并加 `--noproxy "*"`。

## 调优 HY2 的顺序

1. **先认清每个实际用这份配置的客户端**：客户端名称、版本、配置源、生成的产物、运行中进程实际加载的路径和当前出口。用 CLI、服务启动参数和请求记录取证，不靠截图；文件改了不等于设备已加载。只盘点这次涉及的客户端，不扩散凭据。
2. **先复现实际失败的应用请求**，再固定节点做受控对比。把「客户端到 VPS」和「VPS 到目标」两段的瓶颈分开。单流 TCP、服务端测速或自动选组里的最好成绩，都不是整条路径的理论上限。
3. **Linux sing-box 先看负载下实际的 UDP socket 和丢包增量**，再决定动不动缓冲，见 [linux-client.md](linux-client.md#udp-缓冲)。客户端的问题不自动要求改服务端；服务端健康也不代表每个客户端都最优。
4. **固定链路才测方向独立的带宽参数**：一次只改一项，基线和候选交替重复，同时看吞吐、负载下延迟、并发和失败率。留下实测的折中，不承诺所有场景同时达到物理上限。方法见下面「吞吐、延迟和故障切换」。
5. **Surge、Surfboard 和 sing-box 是不同的实现。** 核对各自版本的官方字段和不写时的行为，不能把 sing-box 的 sysctl 绕法或带宽值照搬到原生客户端。Surge 和 Surfboard 的 `download-bandwidth` 是可选字段，不写不代表证明了用的是同一种拥塞控制。字段依据：[Surge HY2](https://manual.nssurge.com/policies/hysteria2.html)、[Surfboard HY2](https://getsurfboard.com/docs/profile-format/proxy/external-proxy/hysteria2/)。
6. **改了源头配置，就重建已有的派生产物**，分别记下发布、加载和真实协议验收的状态。只传播协议必需的参数；链路专属的调优要在接收端重新验证，临时绕法写明删除条件和回滚。

## 转发流量的数据路径

宿主 TUN 的测试证明不了 guest／容器的流量。对和怀疑点相关的每条路径——宿主 TUN、下游直连、下游显式代理——用同一个真实对象、同一时间窗、同样的字节范围和超时。优先用实际失败的包或 API URL；小的 GitHub 资源或公共测速端点可能掩盖某个仓库特有的路径问题。

判断通不通，每条路径一个有界样本就够。报告是「慢」或「时好时坏」，或者要比较 selector 候选时，每条比较路径至少三个样本，结果都留着，这时设 `RUNS=3`：

```bash
TEST_URL='https://<actual-repository>/<actual-object>'
RUNS="${RUNS:-1}"
for run in $(seq 1 "$RUNS"); do
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
    -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
    curl --noproxy '*' --range 0-10485759 \
    --connect-timeout 5 --max-time 30 \
    -fsSL -o /dev/null \
    -w "path=host-tun run=$run code=%{http_code} bytes=%{size_download} speed=%{speed_download} time=%{time_total}\n" \
    "$TEST_URL" || true
done
```

在下游主机上，直连和私网 mixed inbound 用同一个 `RUNS`：

```bash
RUNS="${RUNS:-1}"
for run in $(seq 1 "$RUNS"); do
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
    -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
    curl --noproxy '*' --range 0-10485759 \
    --connect-timeout 5 --max-time 30 -fsSL -o /dev/null \
    -w "path=guest-direct run=$run code=%{http_code} bytes=%{size_download} speed=%{speed_download} time=%{time_total}\n" \
    "$TEST_URL" || true

  curl --proxy http://<private-gateway>:<mixed-port> --range 0-10485759 \
    --connect-timeout 5 --max-time 30 -fsSL -o /dev/null \
    -w "path=guest-proxy run=$run code=%{http_code} bytes=%{size_download} speed=%{speed_download} time=%{time_total}\n" \
    "$TEST_URL" || true
done
```

除非转发的源地址明确绕过了、路由证据也证实了，「直连」样本仍可能经过宿主 TUN。curl 样本要配上有界的 sing-box 日志和防火墙计数。服务端可能无视 range 请求：记下 `size_download`，到超时就停，不要把意外变大的传输当成有效的 10 MiB 样本。

重复的性能样本比分布和失败率，不比最快的那次。一条在几 MB/s 和超时之间来回跳的路径不稳定，哪怕它最好成绩最高。每个仓库留在给它证明过的路径上，不要因为一次比较就设全局的包管理器代理。

往 URLTest 里加节点或传输之前，先让这个候选单独当 selector 默认，或者给它一个临时 mixed 端口单测：协议握手、生产 profile 实际用的 DNS 路径、一个真实的 HTTPS 对象都要过。然后加进 URLTest，在 `info` 日志里确认被选中的 outbound。远程 DNS 可能随所选 outbound 一起失败，所以 `tailscaled`／sing-box 在运行、socket 在监听，都证明不了候选的数据面健康。

## 吞吐、延迟和故障切换

缓冲大小和拥塞控制是两个变量，分开测。提高固定带宽目标之前，先按 [linux-client.md](linux-client.md#udp-缓冲) 看 socket。用同样的字节和超时比较 BBR、保守的 Brutal 目标和 REALITY，候选交替跑至少三轮。上传单独测，再测并发传输和负载下的短请求。吞吐下降、错误上升或延迟变差就停止加码。Brutal 有丢包补偿，它的目标值不是严格的线速上限。不要把某个站点测出的最佳 Mbps 抄进通用模板。

在上游服务器上起一个回环源站，排除第三方存储和 CDN 的波动；同时也重复实际失败的那个应用请求。直连的单连接 TCP 测试不是物理带宽上限：也比较聚合吞吐，证明参照组绕开了 TUN，并报告 Wi-Fi 或底层网络的限制。任何临时开在公网的测速 listener 都要限来源、限时长，结束后清掉防火墙规则。测到的最大值不证明理论上限，也不证明每种网络场景下都最优。

长下载时 `interrupt_exist_connections` 保持 false（或不写），除非用户明确要在切换选择时断掉已有连接。URLTest 按探测延迟排序，既不是严格的主备，也不是大流量测速。对 HY2 outbound 的探测和应用流共用同一个 QUIC 会话和拥塞预算。保住健康的连接，不要追着每次延迟波动切换；跨过几个探测周期验一次长传输，但不能只凭一个周期就断定发生了切换。故障切换能服务新连接，没法把已经断掉的 TCP 下载挪到另一台服务器。同一台服务器上的多个端口不是独立的故障域。只有证据表明某个端口的 UDP 被封或被限速时才加端口跳跃，它治不了本机接收缓冲溢出。

## 一次性 REALITY 源站

用户同意在这台服务器和这个域名上做一次性协议端到端测试时，可以用域名现有的证书起一个只在回环上的 REALITY 握手源站，避开没被认可的第三方目标。它验证的是 REALITY 认证和回落机制，不是生产环境的伪装效果。

用一个单独的回环端口，handshake 永远不要指回公网的 REALITY TCP/443 listener。临时的 OpenSSL 源站能提供要求的 TLS 1.3 和 ALPN `h2`：

```bash
REALITY_SNI="$HY2_DOMAIN"
REALITY_HANDSHAKE_HOST=127.0.0.1
REALITY_HANDSHAKE_PORT=8443
ORIGIN_UNIT=reality-e2e-origin

test -z "$(ss -H -ltn "sport = :$REALITY_HANDSHAKE_PORT")"
systemd-run \
  --unit="$ORIGIN_UNIT" \
  --collect \
  --property=RuntimeMaxSec=30min \
  /usr/bin/openssl s_server \
    -accept "127.0.0.1:$REALITY_HANDSHAKE_PORT" \
    -cert "/etc/letsencrypt/live/$HY2_DOMAIN/cert.pem" \
    -cert_chain "/etc/letsencrypt/live/$HY2_DOMAIN/chain.pem" \
    -key "/etc/letsencrypt/live/$HY2_DOMAIN/privkey.pem" \
    -tls1_3 \
    -alpn h2 \
    -www
```

这种写法下 `s_server -cert fullchain.pem` 不会发送完整证书链。leaf 用 `-cert`，签发链用 `-cert_chain`。启用 REALITY 之前，用显式带 `-tls1_3 -alpn h2` 的 `openssl s_client` 确认 TLS 1.3、ALPN `h2`、主机名校验和证书校验结果为 0；HTTP/1.1 的 curl 探测不等价。

这个 OpenSSL 源站是单进程的测试夹具，不能并发服务。受控的无效 REALITY 凭据或无关的公网扫描器进入回落后，会占住它接受的那个连接，后面有效的探测就排队等着。所以在做「有效凭据恢复」断言之前，立即重启这个临时 unit，重新确认 TLS 1.3、ALPN `h2`、主机名和证书。别把排队的恢复探测诊断成 REALITY 回归。

这个源站只留到有界的外部客户端测试结束。之后恢复原来的 sing-box 配置和防火墙，停掉临时 unit，删掉生成的 REALITY 凭据。不要把这个拓扑留作生产的握手源站。

## 私有 CA 的协议端到端测试

用户同意做一次性协议测试、但没有公网域名时，可以用保留的测试域名、私有 CA 和回环 REALITY 源站验证 REALITY 和 HY2 的数据面。这验不了公网 DNS、ACME 签发、续期和生产伪装，这几项保持未验证。

这个一次性源站用 RSA-2048 的 leaf：这是对目标 sing-box 二进制、Chrome uTLS 指纹和 OpenSSL `s_server` 测过的组合；Ed25519 leaf 在这条路径上报过 `tls_choose_sigalg:no suitable signature algorithm`。这不是生产证书的通用限制。记下测试用的二进制版本。

REALITY handshake 指向一个单独的回环端口，并把这个实际端口写进 `handshake.server_port`。HY2 服务端指向私有 leaf 和私钥。客户端只拿私有 CA 的根证书，并加上 `tls.certificate_path`；不用 `insecure=true` 代替显式信任。

服务端上支持 HTTP/3 的 curl 能在不依赖 DNS 和外网的情况下证明 string masquerade：

```bash
curl --http3-only --noproxy "*" \
  --resolve "$TEST_NAME:443:127.0.0.1" \
  --cacert "$CA_CERT_PATH" \
  --connect-timeout 5 --max-time 15 \
  -fsS -w '\nhttp_version=%{http_version} code=%{http_code}\n' \
  "https://$TEST_NAME/"
```

要求返回配置的响应体、`http_version=3` 和预期的状态码。这个回环断言证明 masquerade 的行为，不证明公网 UDP/443 可达；后者要另外用外部的认证 HY2 请求和防火墙证据证明。

## 服务端裸测速

优先用已有的测速工具，Speedtest 不是部署依赖。客户端网络、目标服务器、并发和时间窗要可比；记下延迟、下载、上传、丢包和时间戳。VPS 到目标的结果只描述那一段，不代表客户端到 VPS 的容量。

原生 Surge 的测试用 `$surge` 和装着的 CLI 的 help。固定测实际的 HY2 policy，不测自动分组；用户同意改选择时，记下并恢复原来的选择。不要为了在 Mac 上测 REALITY 再装一个运行时。

## 受控的协议对比

第三方测速端点换服务器、限速或拒绝 VPS 出口时，在代理服务器的回环上起一个临时 HTTP 服务。发往 `127.0.0.1:<port>` 的 SOCKS 请求必须先通过 REALITY 或 HY2 认证才能到它，载荷也不经过第二条互联网路径。

在代理服务器上建一个固定大小的临时文件和一个限时的回环服务：

```bash
install -d -m 700 /tmp/singbox-protocol-bench
truncate -s 134217728 /tmp/singbox-protocol-bench/blob.bin
systemd-run \
  --unit=singbox-protocol-bench \
  --collect \
  --property=RuntimeMaxSec=300 \
  --property=WorkingDirectory=/tmp/singbox-protocol-bench \
  /usr/bin/python3 -m http.server 18080 --bind 127.0.0.1
```

不同的 mixed 客户端各开在不同的回环端口上，每个变体至少三个样本：

```bash
curl --proxy socks5h://127.0.0.1:<mixed-port> \
  --connect-timeout 15 --max-time 90 \
  -fsS -o /dev/null \
  -w 'code=%{http_code} bytes=%{size_download} time=%{time_total} speed_Bps=%{speed_download}\n' \
  http://127.0.0.1:18080/blob.bin
```

比中位数，不比最好的样本。HY2 只在固定链路上拿「不写带宽」和一个保守的 Brutal 候选对比。每次下载时测到本地网关的延迟；吞吐涨了但延迟或丢包明显变差，就不是更好的默认。测完停掉临时 unit，删掉测试文件：

```bash
systemctl stop singbox-protocol-bench.service 2>/dev/null || true
rm -rf /tmp/singbox-protocol-bench
```

`speed_download` 单位是字节／秒，乘 8 再除以 1000000 得 Mbps。固定文件测的是这个负载，不代表每个应用的性能。

## Linux 协议测试

mixed 配置只做协议冒烟：

```bash
sing-box run -c client-mixed.json
curl -fsS4 --proxy socks5h://127.0.0.1:2080 https://api.ipify.org
```

一次性的服务端还要测认证边界，且不覆盖保留的凭据：先用有效客户端通过一次；再起一个只改错一个凭据的候选，要求拿不到受保护的响应标记；然后换回有效客户端再通过一次。错误那一轮超时或连接错误都可以，拿到受保护端点的响应就不行。用上面的 OpenSSL 源站时，有效的恢复请求之前照上文重启它，否则排队的有效请求看起来像认证回归。

TUN 的长期验收（清掉代理变量、HTTP/3、VLESS packet connection 的日志断言）见 [linux-client.md](linux-client.md#验收)。那里通过后，切到 `hy2-h3-out` 测同一个目标，要求 journal 里出现 Hysteria2 的 packet connection：

```bash
journalctl -u sing-box@<name>.service --no-pager -n 80 \
  | grep -E 'inbound/tun|dns: exchanged|outbound/vless|outbound/hysteria2|UDP is not supported'
```

本机 curl 不支持 HTTP/3、改用无头浏览器时：给浏览器一个专用的临时 `--user-data-dir` 和明确的截止时间，结束时（包括探测失败）杀掉进程、删掉目录，不杀也不复用用户正在用的浏览器。要求拿到协商为 `h3` 的 HTTP 响应；浏览器启动成功或退出码不是协议证据。到截止时间退出不影响已经拿到的响应：要求预期的响应体，加上和目标对得上的 netlog 事件——QUIC 证书校验、带预期状态码的 `HTTP3_HEADERS_DECODED`、`HTTP3_DATA_FRAME_RECEIVED`。隔离进程在截止前没产出这些证据，就把这一层报为未验证，不要推断 HY2 坏了。

响应头里有 `HTTP/1.1 200 Connection established`，说明样本走了 HTTP 代理，不算 TUN 证据。

## 怎么解读失败

- Ookla CLI 报 `Cannot read` 或 `Cannot write`：样本失败，不是吞吐证据。
- Speedtest 换了服务器能解释很大的差异。同协议同服务器再比。
- 服务端裸测几 Gbps，不代表客户端热点能跑出几 Gbps 的代理速度。
- 热点或丢包路径上，HY2 走 UDP 可能不如 REALITY，哪怕 VPS 带宽很好。
- 固定的 Brutal 值是针对一条链路的优化，不是可移植的默认值。
- 全局 UDP sysctl 值低，不证明 sing-box 的 socket 小。HY2 传输进行中看 `ss -u -a -m -p` 和 UDP 错误计数，再决定调不调。
- 选着 VLESS 时出现 `UDP is not supported by outbound: proxy`：VLESS 被限成了 TCP；改之前查一下目标版本 `network` 的默认值。
- 有界的 Surge 或 HTTP/3 探测窗口内出现 `connection upload closed: stream <n> canceled by remote with error code 0`：客户端拿到结果后取消了流。服务在运行且没重启时，这一行不是服务端崩溃；其他错误形状照常查。
- `inactive (dead)`、退出状态 0、journal 里有 `Stopped sing-box service`：是外部正常停止，不是崩溃。改配置前先查 timer、测试脚本和人工操作。

## 核对配置源和实际运行

只读的「配置源对实际运行」核对，先找出实际的服务、二进制、启动参数和配置路径，不假设示例里的名字和端口。配置源、生成或导入的产物、实际加载的运行时分开比：磁盘上的文件对得上，不代表进程重新加载了它。

只取需要的非 secret 字段：端点、端口、TLS 名、协议、带宽设置、选中的 outbound 和相关的路由排除。凭据在内存里比，只报告是否相等，不报值；「都有值」不等于相等。不要导出整份配置、路由表或未过滤的诊断输出。

listener、证书／续期和服务检查用 [server.md](server.md)；共用的 sing-box 形态用 [clients.md](clients.md)；路由和激活看对应平台。在每个要求的客户端和指定节点上跑真实协议。配置源、产物、下发、加载和协议验证分开报告；连不上的设备保持未验证。
