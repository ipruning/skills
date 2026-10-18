# Service 验收

Service 定义和 host 映射都配好后读这份。数据面测试要从一台本该有权限的 tailnet 客户端发起，只在 host 上测不算。

## 1. backend

在 host 上请求 Serve 里配置的同一个目标：

```bash
curl -fsS --connect-timeout 5 --max-time 15 http://<backend-host>:<backend-port>/<health-path>
```

TCP 类 backend 用它自己的协议探测。端口在监听只说明有进程占着，要拿到应用层响应才算。

## 2. host 上的配置和发布

```bash
(
  set -e -o pipefail
  umask 077
  serve_verify="$(mktemp)"
  trap 'rm -f -- "$serve_verify"' EXIT
  tailscale status --json | jq '{BackendState, Health, Self: {Online: .Self.Online, ServiceHost: .Self.CapMap."service-host"}}'
  tailscale serve status --json >"$serve_verify"
  test -s "$serve_verify"
  tailscale debug prefs | jq '.AdvertiseServices'
  # 在这里和改前快照对比：目标映射对不对，别的 Service、节点 Serve 和发布列表有没有变
)
```

要看到 `BackendState` 为 `Running`、`Self.Online` 为 `true`、没有相关的 Health 报错、`service-host` 里有目标 Service（审批通过后才有），且目标映射和预期一致。

对比写在这个 subshell 里。被 SIGKILL 或主机挂掉时 trap 删不掉文件，不要说能保证清理。不在用户工作目录里写固定文件名的快照；不许落盘时按 SKILL.md 的做法放内存。

## 3. 控制面

批准后读控制台 Services 页或 API。要在 Service hosts 列表里看到目标 host 本身已批准且在线，endpoint 和预期一致，TailVIP 没变。Service 级的 Connected 只说明至少有一台 host 在发布。Pending approval、Needs configuration、Offline、Pre-approved、Draining 都不是就绪状态。

## 4. DNS 和 TailVIP

在有权限的客户端上：

```bash
getent ahosts <service-fqdn>
tailscale version
tailscale status --json | jq '{Health, Self: {Online: .Self.Online}}'
```

Service 域名必须解析到控制面给的 TailVIP，而不是某台 host 自己的 IP。解析不到时先看客户端版本，不要为此开 `accept-routes`。

## 5. TCP、TLS 和 HTTP

HTTPS Service 要分别走正常 DNS 和直连 TailVIP，两次用同一个 SNI：

```bash
curl --fail --show-error --silent \
  --connect-timeout 5 --max-time 20 \
  -o /dev/null -w 'dns code=%{http_code} verify=%{ssl_verify_result}\n' \
  https://<service-fqdn>/<expected-path>

curl --fail --show-error --silent \
  --resolve '<service-fqdn>:443:<tailvip-v4>' \
  --connect-timeout 5 --max-time 20 \
  -o /dev/null -w 'tailvip code=%{http_code} verify=%{ssl_verify_result}\n' \
  https://<service-fqdn>/<expected-path>

openssl s_client \
  -connect <tailvip-v4>:443 \
  -servername <service-fqdn> \
  -verify_return_error </dev/null
```

要看到预期的状态码和页面内容、`verify=0`、证书域名匹配且在有效期内。产品页面有自己的特征时，要看到那个特征；登录代理返回的通用 200 不算。

用 `--resolve` 时 URL 里保留域名，Host 和 SNI 才是对的。直接请求 `https://<tailvip>/` 测的是另一个证书身份，会得到假失败。

## 6. 不该开的东西

定义里故意没发布的敏感端口逐个探，比如 backend 的 HTTP 端口、数据库端口：

```bash
nc -vz -w 3 <tailvip-v4> <unpublished-port>
```

必须连不上或超时。有条件时再用一个没权限的 tailnet 身份试。端口测试和身份测试互相不能替代。

## 7. 证书签发

配了 HTTPS 会自动签证书。刚批准时 TailVIP 可能已经通了，证书还没好。在维护窗口内限定等待时间，轮询同一个带正确 SNI 的请求，同时看最近的 `tailscaled` 日志，记下第一次的错误和最后的结果。

签发过程中不要 clear 配置、不要重建 Service、不要反复开关 HTTPS：会丢掉现场，还可能触发新一轮签发。backend、映射、审批、TailVIP 都排除了，日志也指向证书，才往上报。

## 8. 重启和高可用

读到配置只说明配上了，不说明 `tailscaled` 或主机重启后真的能恢复。

- 有多台 active host：drain 一台，确认新连接走到另一台，再重启这台、重新 advertise，把上面整套重跑一遍。
- 只有一台 host：重启就是中断，放在维护窗口里做。没实测就报告「重启后恢复已配置，未验证」。
- host 没 drain 就消失时，TailVIP 不变也保不住已建立的 TCP 连接。
