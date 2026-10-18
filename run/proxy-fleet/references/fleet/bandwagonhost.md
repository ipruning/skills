# 搬瓦工（BandwagonHost／KiwiVM）

## 读流量、配额和服务商状态

KiwiVM API 不需要浏览器，也不受墙影响：

```text
https://api.64clouds.com/v1/getServiceInfo?veid=<VEID>&api_key=<KEY>
```

要带 `User-Agent` 头，不带会被拒（HTTP 403）。`api_key` 在 URL 里，调用时把 URL 从标准输入交给 curl，别让它出现在命令行参数、进程列表和异常文本里。

`getServiceInfo` 一次给齐监控要的字段：

| 字段 | 用途 |
| --- | --- |
| `data_counter`、`plan_monthly_data` | 已用和配额（字节）。百分比直接相除；绝对值要乘 `monthly_data_multiplier` |
| `data_next_reset` | 下次流量重置的 Unix 时间，告警文案里带上 |
| `suspended`、`ip_nullroutes`、`policy_violation`、`total_abuse_points` | 服务商侧的不可用原因：暂停、IP 被黑洞、违规。任一非空或非 0 就是服务商告警，优先于流量判断 |
| `ip_addresses` | 当前 IP，换 IP 后核对用 |

`error` 非 0 就是失败：`700005` 是鉴权失败，`700001` 是缺 `veid`。接口有速率限制，`getRateLimitStatus` 可查剩余额度；每台 5 分钟调一次远远用不完。

```bash
printf 'url = "https://api.64clouds.com/v1/getServiceInfo?veid=%s&api_key=%s"\n' "$VEID" "$KEY" \
  | curl -s -A probe -K - | python3 -c '
import sys, json
d = json.load(sys.stdin)
pct = d["data_counter"] / d["plan_monthly_data"] * 100
print(f"{pct:.0f}%", "suspended" if d["suspended"] else "", d["ip_nullroutes"] or "")'
```

不必进定时监控的接口：`getLiveServiceInfo`（运行状态、负载；每次附带一整张 VNC 截图，慢，主机指标交给 Beszel 这类 agent）、`getRawUsageStats`、`getAuditLog`（换 IP、重装、登录记录），排障时临时查。

## 拿全部 veid 和 api_key

登录 `bandwagonhost.com` 客户区 → **Export all services with private API keys**（`whmcsExportServiceInfoCsv.php`），得到七列 CSV：`VEID,VM_TYPE,HOSTNAME,PRIMARY_IP,IS_TERMINATED,IS_2FA_ENABLED,API_KEY`。`IS_TERMINATED=1` 的行跳过；客户区显示「将于某日取消」的服务导出里仍是 `0`，以客户区列表为准。

`API_KEY` 是私钥：不写进 tracked 文件、日志和对话。探针主机上存成 `chmod 600` 的文件。用完删掉下载的导出文件。

客户区登录挂着 Cloudflare 和新设备邮箱验证码，无头 curl 过不去，要真实浏览器。只有导出 key 时需要；之后全靠 `api.64clouds.com`。

## 节点短时间全挂又自己恢复

同一机房几台节点同时失联十来分钟又恢复，先查是不是宿主机冻结了 VM，不要当成被墙：

```bash
journalctl --since '<UTC 开始>' --until '<UTC 结束>' -o short-unix \
  | awk '{t=int($1); if (p && t-p>120) print strftime("%T",p,1), "->", strftime("%T",t,1); p=t}'
journalctl -k | grep -E 'TX timeout|Long readout interval'
journalctl -u chronyd | grep 'Forward time jump'
```

平时几秒一条的日志（UFW、sing-box）整段空白，解冻后出现 `virtio_net ... TX timeout`、`clocksource: Long readout interval` 或 chronyd 的 `Forward time jump detected!`，就是 VM 被暂停了。这是服务商维护或迁移，节点配置不用动。BWH 节点默认 UTC，对时间要换算时区。

## 节点被墙，换 IP

症状：国内探针连不上这个节点，海外能连，`getServiceInfo` 里 `suspended=false`、`ip_nullroutes` 为空，账单已付，也不是上面的冻结。这时才是 IP 被墙。

修法：`bandwagonhost.com/ipchange.php` → 选服务 → Request IP Change。付费（$7.39），同机房换一个随机新 IP，保留 CN2 GIA 线路，数据不动。**不要**用 Migrate to another DC，那会换机房、丢线路。付款后约 24 小时内换好（实测可能几分钟），`ip_addresses` 里出现新 IP。

付了款但还没看到新 IP 时，先用 API 读回状态，不要重复下单。

换完之后：更新客户端配置里这个节点的 IP 和对应的直连规则（Surge 里还有一条 `IP-CIDR,<ip>/32,DIRECT`），协议探针跟着客户端配置走。

## 监控清单

- 服务商状态和流量：监控账号下所有在用服务（客户区 Active 列表），不论是不是代理节点。新开的机器要同时加进流量监控和主机监控（Beszel 等），服务取消前从两处删掉，否则取消后会持续报 API 错误或离线。
- 可达性：只探测客户端真正在用的出口，按客户端配置的 IP 和端口，用 [monitoring.md](../reality-hy2/monitoring.md) 的认证请求。不另外手工维护一份并行的 IP 清单。
