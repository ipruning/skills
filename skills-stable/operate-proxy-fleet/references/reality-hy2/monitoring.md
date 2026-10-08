# 从外部探测 HY2

要长期监控 HY2 时，和 `$end-to-end-monitoring` 一起用。那边管探测频率、新鲜度、后端、告警状态转换、secret 存放、响应人和处置手册；这里只给 HY2 专有的探测信号和 sing-box 进程的约束。

探针跑在 sing-box VPS 之外，告警通道不能只靠它正在观察的这条 HY2 路径。探针自己整个挂掉时报不出来，这种沉默要紧的话，要有独立后端检测「该来的运行没来」。

探针主机开着系统级 TUN 时，要在运行时证明发往 `SERVER_IP` 的流量确实绕过了 TUN。配置文件里写了路由排除只是意图，不是运行时证据。证明不了直连，就把这一轮记为探针本地故障，不算到远端 HY2 头上。

## 输入

```text
SERVER_IP
HY2_DOMAIN
HY2 outbound，取自用户给的客户端配置
EXPECTED_EGRESS_IPV4，直连公网的 VPS 上一般就是 SERVER_IP
CERT_MIN_SECONDS，按证书有效期和修复所需时间定
DNS_RESOLVER_IP，用户自己的或明确同意使用的外部 resolver
EGRESS_ECHO_URL，用户自己的或明确同意使用的 HTTPS IP 回显服务
```

`300s` 频率和 `1209600` 秒（14 天）证书余量只是起点，实际值由监控约定决定。同意监控这台服务，不等于同意把它的域名和出口发给第三方 DNS 或 IP 回显服务；这两个端点先写进监控约定再用。

## 专用 profile

从客户端配置里取出 HY2 outbound，单独生成一个 mixed profile。不碰正在用的 TUN profile，也不打印取出来的 outbound，里面有 HY2 密码：

```bash
umask 077
jq '{
  log: {level: "warn", timestamp: true},
  inbounds: [{
    type: "mixed",
    tag: "monitor-in",
    listen: "127.0.0.1",
    listen_port: 2089
  }],
  outbounds: [.outbounds[] | select(.tag == "hy2-h3-out")],
  route: {final: "hy2-h3-out"}
}' <authorized-client-config.json >hy2-monitor.json
sing-box check -c hy2-monitor.json
```

装成 `root:<monitor-group>`、权限 `0640`。源配置和生成的 profile 都只留在这台探针主机上。

## 信号

### 公网 DNS

只要有客户端拨的是 `HY2_DOMAIN` 而不是 `SERVER_IP`，就查外部 resolver：A 记录必须是预期的值；IPv6 不在部署约定里时，AAAA 必须为空。

```bash
dig +short A "$HY2_DOMAIN" @"$DNS_RESOLVER_IP"
dig +short AAAA "$HY2_DOMAIN" @"$DNS_RESOLVER_IP"
```

下面的 HTTP/3 检查用了 `--resolve`，覆盖不到公网 DNS。

### HTTP/3 证书

先确认 curl 支持 HTTP/3 和 `%{certs}`，不支持就失败，不悄悄退回 TCP。`%{certs}` 只有 OpenSSL、GnuTLS、Schannel、Rustls 后端能拿到证书链；macOS 自带 curl 用的 SecureTransport 拿不到，会让下面误判成 `TLS_INVALID`，探针要用前几种后端的 curl：

```bash
curl -V | grep -w HTTP3
curl -V | grep -Eiq 'OpenSSL|GnuTLS|Schannel|rustls' || exit 1
case "$(curl -sS -o /dev/null -w '%{certs}' file:///dev/null 2>&1)" in
  *"unknown --write-out variable"*) exit 1 ;;
esac
```

直连 `SERVER_IP`，按 `HY2_DOMAIN` 校验证书：

```bash
set -euo pipefail
probe_dir="$(mktemp -d)"
trap 'rm -rf "$probe_dir"' EXIT
curl_exit=0
if curl --disable \
    --http3-only \
    --head \
    --noproxy '*' \
    --resolve "$HY2_DOMAIN:443:$SERVER_IP" \
    --connect-timeout 8 --max-time 20 \
    -sS -o /dev/null -w '%{http_code}\n%{certs}' \
    "https://$HY2_DOMAIN/" >"$probe_dir/result"; then
  :
else
  curl_exit=$?
fi
http_status="$(sed -n '1p' "$probe_dir/result")"
http3_result=fail
tls_result=unknown
monitor_result=pass
cert_margin=unknown
if [ "$curl_exit" -ne 0 ]; then
  case "$curl_exit" in
    53|58|59|66|77|82) monitor_result=invalid ;;
    60) tls_result=invalid ;;
  esac
  echo "HTTP/3 probe incomplete: curl_exit=$curl_exit http_status=${http_status:-none}" >&2
else
  case "$http_status" in
    [1-5][0-9][0-9]) http3_result=pass; tls_result=pass ;;
    *) echo "HTTP/3 probe returned no valid HTTP status: $http_status" >&2 ;;
  esac
  if [ "$http3_result" = pass ]; then
    awk '
      /-----BEGIN CERTIFICATE-----/ { capture = 1 }
      capture { print }
      /-----END CERTIFICATE-----/ { exit }
    ' "$probe_dir/result" >"$probe_dir/leaf.pem"
    if ! openssl x509 -in "$probe_dir/leaf.pem" -noout; then
      tls_result=invalid
      echo "HTTP/3 probe returned no parseable leaf certificate" >&2
    elif openssl x509 -in "$probe_dir/leaf.pem" -noout \
        -checkend "$CERT_MIN_SECONDS"; then
      cert_margin=ok
    else
      cert_margin=warning
    fi
  fi
fi
```

通过的条件：HTTP/3 服务端回了 HTTP 状态码，拿到能解析的 leaf PEM，curl 的主机名和证书链校验通过，leaf 当前有效。证书还有效但进了 `CERT_MIN_SECONDS` 余量，是单独的警告，不算不可用。警告按 leaf 指纹或序列号加到期时间去重，多次看到余量之外的新证书后才解除。

masquerade 的响应不固定时，不要求 `2xx`。proxy 型 masquerade 在 QUIC 和证书都正常时也可能回上游错误。这一项看的是未认证的 HTTP/3 行为，不是 HY2 认证。

用 `HEAD` 这类有界请求；下载 masquerade 的 body 可能让正常的 QUIC 和 TLS 握手因 body 超时而误报。curl 退出码和 HTTP 状态码分开记：先看到状态码、后来 curl 失败，算探测没完成，不算成功样本。

`--disable` 让探针用户的 `.curlrc` 不生效，`--noproxy '*'` 绕开所有代理环境变量，本机客户端设置就改不了这条直连探测。curl 退出码 `53`、`58`、`59`、`66`、`77`、`82` 是探针本地故障；`60` 是对端证书校验失败；其他非零退出码下 TLS 结论记为未知，除非另有有界证据能定位是哪一端。

直连这一项在传输或 TLS 失败后，也要记下结果并继续做下面的认证探测。只有本地前提失败才能跳过后面的信号。

### 认证后的 HY2

探测要经过一个只为监控起的本地 sing-box 进程（下称 sidecar），它跑上面的专用 profile。生命周期二选一。一次性的手动或调度探测：启动专用 profile，等它的本地端口起来，结束时一定停掉：

```bash
if ss -H -ltn 'sport = :2089' | grep -q .; then
  echo "local monitor port 2089 is already owned; stop or choose another dedicated port" >&2
  exit 1
fi

sidecar_log="$(mktemp)"
echo_body="$(mktemp)"
echo_status="$(mktemp)"
sing-box run -c hy2-monitor.json >"$sidecar_log" 2>&1 &
sidecar_pid=$!
cleanup_sidecar() {
  kill "$sidecar_pid" 2>/dev/null || true
  wait "$sidecar_pid" 2>/dev/null || true
  rm -f "$sidecar_log" "$echo_body" "$echo_status"
}
trap cleanup_sidecar EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

sidecar_listening() {
  ss -H -ltnp 'sport = :2089' | grep -Fq "pid=$sidecar_pid,"
}

for _ in $(seq 1 40); do
  if ! kill -0 "$sidecar_pid" 2>/dev/null; then
    cat "$sidecar_log" >&2
    exit 1
  fi
  sidecar_listening && break
  sleep 0.25
done
sidecar_listening || {
  cat "$sidecar_log" >&2
  exit 1
}
```

然后强制走 IPv4 发一次请求：

```bash
curl_exit=0
if curl --disable \
    -4 --proxy socks5h://127.0.0.1:2089 \
    --connect-timeout 5 --max-time 15 \
    -sS -o "$echo_body" -w '%{http_code}' \
    "$EGRESS_ECHO_URL" >"$echo_status"; then
  :
else
  curl_exit=$?
fi
http_status="$(cat "$echo_status")"
observed_ip="$(tr -d '\r\n' <"$echo_body")"
```

出口必须是 `EXPECTED_EGRESS_IPV4`。VPS 在 NAT 后面时，这个值按实测出口定，不要默认等于 `SERVER_IP`。只有一个回显服务时，它挂了算外部依赖故障；要第二个端点或自己的回显服务也失败，才能说代理挂了。

回显的 body、HTTP 状态码和 curl 退出码分开记：

- 非 `2xx`：说明专用 HY2 路径带回了 HTTP 响应，但证明不了出口。
- 拿到一个合法但不对的 IPv4：明确违反约定。
- 单个回显端点没有响应：结论不确定，记为 `AUTH_OR_ECHO_UNREACHABLE`，不记为 `HY2_UNAVAILABLE`。

长期探针也可以由 `$end-to-end-monitoring` 装一个常驻的 sidecar unit。探测 unit 要对它声明启动顺序和运行依赖，curl 之前确认 `2089` 已就绪，sidecar 不在运行时算新鲜度失败。常驻 unit 占着这个端口时，不要再起一次性进程。

## 每轮的结论

独立的信号即使有一个失败也都要跑完。只有本地前提无效时才提前结束，比如证明不了直连，或 sidecar 端口不归自己。结果归成稳定的类别；curl 原始退出码、HTTP 状态码和有界日志作为证据留着，不当状态键。

先按优先级判：本地前提失败记 `MONITOR_LOCAL_FAILURE`；TLS 主机名、证书链、当前有效期或 leaf 解析失败记 `TLS_INVALID`；认证出口拿到合法但不对的 IPv4，不管 HTTP/3 结果如何都记 `AUTH_EGRESS_MISMATCH`。其余按下表：

| 直连 HTTP/3 | 认证出口 | 类别 | 含义 |
| --- | --- | --- | --- |
| pass | 预期 IPv4 | `HEALTHY` | 外部传输、TLS、认证和出口约定都通过。 |
| fail | 预期 IPv4 | `HTTP3_DEGRADED` | 认证后的 HY2 能用，不能报 HY2 全挂。 |
| pass | 有 HTTP 响应但没有可用 IP | `ECHO_DEPENDENCY_DEGRADED` | HY2 带回了 HTTP 响应，但回显没证明出口。 |
| pass | 没有可用的 HTTP 响应 | `MONITOR_INCONCLUSIVE` | 直连 HTTP/3 通过，但可能是 HY2 认证、sidecar 出口或回显服务出了问题。原始结果记 `AUTH_OR_ECHO_UNREACHABLE`。 |
| fail | 没有可用的 HTTP 响应 | `DIRECT_AND_AUTH_UNREACHABLE` | 两项都失败，可能是探针侧的共同路径，单凭这一行证明不了服务端宕机。 |

表里和优先级都没覆盖的组合记 `MONITOR_INCONCLUSIVE`，不要硬算成故障。证书进余量是单独的警告线，不能让一个无关的可用性事件一直挂着不恢复。

把类别和证据交给 `$end-to-end-monitoring`，由它管频率、新鲜度、触发和恢复阈值、类别切换和告警送达。它的状态机不能让几种非健康类别来回切换，每次都重置计数，最后永远不告警。未知或跳过的检查不算恢复。通知成功记为 API 已接受，不算设备已收到。

## systemd 约束

sing-box 的 mixed 进程也会通过 netlink 订阅 Linux 路由更新。加固过的 unit 用了 `RestrictAddressFamilies=` 时，必须带上 `AF_NETLINK`：

```ini
RestrictAddressFamilies=AF_INET AF_INET6 AF_NETLINK AF_UNIX
```

缺了它，sing-box 启动时退出并报：

```text
create netlink socket: address family not supported by protocol
```
