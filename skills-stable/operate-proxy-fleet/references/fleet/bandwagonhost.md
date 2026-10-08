# 搬瓦工（BandwagonHost／KiwiVM）

## 读流量、配额、IP 和状态

KiwiVM API 不需要浏览器，也不受墙影响：

```text
https://api.64clouds.com/v1/getServiceInfo?veid=<VEID>&api_key=<KEY>
```

`api_key` 在 URL 里，调用时把 URL 从标准输入交给 curl，别让它出现在命令行参数和进程列表里。

用到的字段：`data_counter`（已用字节）、`plan_monthly_data`（配额字节）、`monthly_data_multiplier`（计费系数）、`ip_addresses`、`ip_nullroutes`、`suspended`、`data_next_reset`。实际已用 = `data_counter × multiplier`，配额 = `plan_monthly_data × multiplier`；算百分比时系数抵消。`error` 非 0 就是失败：`700005` 是鉴权失败，`700001` 是缺 `veid`。接口有速率限制，别高频并发。

每台调一次 `getServiceInfo`，同时拿到流量百分比和当前 IP：

```bash
printf 'url = "https://api.64clouds.com/v1/getServiceInfo?veid=%s&api_key=%s"\n' "$VEID" "$KEY" \
  | curl -s -K - | python3 -c '
import sys, json
d = json.load(sys.stdin)
pct = d["data_counter"] / d["plan_monthly_data"] * 100   # multiplier 抵消，无需乘
ip = d["ip_addresses"][0]
print(f"{pct:.0f}% ip={ip}")'
```

## 拿全部 veid 和 api_key

登录 `bandwagonhost.com` 客户区 → **Export all services with private API keys**（`whmcsExportServiceInfoCsv.php`），得到七列 CSV：`VEID,VM_TYPE,HOSTNAME,PRIMARY_IP,IS_TERMINATED,IS_2FA_ENABLED,API_KEY`。`IS_TERMINATED=1` 的行跳过。

`API_KEY` 是私钥：不写进 tracked 文件、日志和对话。探针主机上存成 `chmod 600` 的文件，用上面的写法经标准输入交给 curl。

客户区登录挂着 Cloudflare 和新设备邮箱验证码，无头 curl 过不去，要真实浏览器（Claude in Chrome 或 CDP）。只有第一次导出 key 时需要；之后全靠 `api.64clouds.com`。

## 节点被墙，换 IP

症状：国内探针连不上这个节点，但 `getServiceInfo` 显示 `suspended=false`、账单已付。这是 IP 被 GFW null-route 了，不是机器坏了或欠费。

修法：`bandwagonhost.com/ipchange.php` → 选服务 → Request IP Change。付费（$7.39），同机房换一个随机新 IP，保留 CN2 GIA 线路，数据不动。**不要**用 Migrate to another DC，那会换机房、丢线路。付款后约 24 小时内换好（实测可能几分钟），`getServiceInfo.ip_addresses` 里出现新 IP。

付了款但还没看到新 IP 时，先用 API 读回状态，不要重复下单。

换完之后：更新客户端配置里这个节点的 IP 和对应的直连规则（Surge 里还有一条 `IP-CIDR,<ip>/32,DIRECT`），并更新监控目标；监控目标从 API 派生的话会自动跟上。

## 监控目标

节点清单 = 这个账号下 `IS_TERMINATED=0` 的服务，每台取 `ip_addresses[0]` 加节点实际的服务端口。不另外手工维护一份并行清单。
