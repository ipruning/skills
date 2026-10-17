# 长期探测代理协议

要长期监控 HY2（REALITY、Snell 同理）时，和 `$monitoring` 一起用。那边管探测频率、新鲜度、告警状态转换、通知和响应人；这里只给协议层的探测信号。

## 唯一的主信号：经过该代理完成一次认证请求

端口通、证书对、DNS 对都只是局部证据。要证明「这个出口能用」，就让探针真的通过它发一个请求：

1. 从授权的客户端配置里取出这一个 outbound，不打印（里面有密码）。
2. 生成临时 sing-box 配置：一个只监听 `127.0.0.1` 随机端口的 mixed inbound，`route.final` 指向这个 outbound，日志级别 `error` 写到临时文件。
3. 启动 sing-box，等端口就绪，经它请求一个返回固定状态码的地址，例如 `curl --head --max-time 10 --proxy http://127.0.0.1:<port> https://www.gstatic.com/generate_204`，拿到 `204` 才算通过。
4. 结束时一定停掉进程、删掉临时目录。

```python
config = {
    "log": {"level": "error", "output": log_path, "timestamp": False},
    "inbounds": [{"type": "mixed", "listen": "127.0.0.1", "listen_port": port}],
    "outbounds": [{**outbound, "tag": "probe", "routing_mark": BYPASS_MARK}],
    "route": {"final": "probe"},
}
```

失败时，原因看 sing-box 日志的最后一条 ERROR，不看 curl 退出码。curl 只知道本地隧道怎么断的；sing-box 知道是哪一跳失败：

```text
dial tcp 144.34.228.187:1: i/o timeout            # 节点或线路不通
authentication failed, status code: 403            # 认证错
```

把这条原因和耗时写进探针日志和告警文案，排障时不用再猜。

Snell、HY2、REALITY 用同一个探针，只换 outbound。

## 探针主机自己挂着 TUN 时

探测流量必须绕过本机代理直连节点，否则测到的是本机代理。给临时 outbound 加 `routing_mark`，值取本机代理的绕行标记（找法见 [cn-reachability.md](../fleet/cn-reachability.md)）。配置文件里写了路由排除只是意图，不是运行时证据：上线前按 cn-reachability.md 做一次出口回显对照；每轮再用 `ip route get <server> mark <mark>` 确认没进 TUN 设备，确认不了就记为探针自身故障，不算到节点头上。

## 可选信号，有明确需要才加

- **出口 IP**：只有出口和 `server` 不同（NAT、链式代理、住宅中转）时才需要。经 sidecar 请求 IP 回显服务并比对预期值。同意监控这台服务，不等于同意把它的域名和出口发给第三方 DNS 或 IP 回显服务；回显端点先写进监控约定再用。
- **证书余量**：证书过期后认证请求本身就会失败，主信号兜得住。要提前预警，就在服务端监控 Certbot 续期失败（`certbot.service` 失败即告警），或者用 `openssl x509 -checkend` 检查服务端正在用的证书。检查 sing-box 配置里 `certificate_path` 指向的那一张。
- **公网 DNS**：只有客户端拨域名而不是 IP 时才查。

## 交给 `$monitoring` 的约定

每轮每个出口给一个结果：`ok`、`protocol_err`（经代理请求失败，附原因）或 `probe_err`（探针自身没跑起来）。同一结果连续两轮才通知，短暂的宿主机冻结和单次抖动就不会推送；恢复也要两轮，并且只在之前通知过才发。同一轮里所有出口的变化合成一条通知。

## systemd 约束

sing-box 会通过 netlink 订阅路由更新。加固过的 unit 用了 `RestrictAddressFamilies=` 时，必须带上 `AF_NETLINK`：

```ini
RestrictAddressFamilies=AF_INET AF_INET6 AF_NETLINK AF_UNIX
```

缺了它，sing-box 启动时退出并报：

```text
create netlink socket: address family not supported by protocol
```

设置 `routing_mark`（`SO_MARK`）需要 `CAP_NET_ADMIN`；以非 root 用户跑探针时要单独授予。
