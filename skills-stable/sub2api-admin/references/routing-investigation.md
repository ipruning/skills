# Sub2API 路由与额度调查

## 报告的数据从哪来

先定好准确的日期范围和时区。上游额度按滚动窗口计算，没核对账号实时用量里的 7 天窗口 Token（`window_stats.tokens`）和上游重置时间，就不要按日历日期去推这个窗口。

默认报告只用 Sub2API 自己存的数据：

- `GET /admin/system/version`：部署暴露的语义化版本。
- `GET /admin/accounts?platform=openai`：OpenAI 账号列表，`--ids` 在这之后才筛选。
- `GET /admin/dashboard/models?model_source=mapping`：每个账号按「请求模型 → 上游模型」聚合的 Token。

读部署版本失败，或某个账号的路由聚合失败时，`summary.complete` 变成 `false`；后者还会留下该账号的 `routing_error`，并让 `summary.accounts_failed` 加一。开了额度或实时用量查询后，任何一项上游证据失败也会让 `complete` 变成 `false`，计入 `summary.upstream_evidence_failed`。这时汇总只含取到的部分，不能当作全部目标账号的用量。

## 额度与实时用量

`--include-upstream-quota` 调 `GET /admin/openai/accounts/:id/quota`。它同步查询供应商，再把自动重置额度的评估交给后台任务；账号开了自动重置并达到阈值时，后台会保存账号状态并消耗 reset credit。

`--include-active-usage` 调 `GET /admin/accounts/:id/usage`。OpenAI 账号不支持 `source=passive`（只有 Anthropic OAuth 和 Setup Token 账号支持），只能走实时查询。对 OpenAI OAuth 账号，它可能探测上游并异步写回用量快照；写回成功后同样会触发自动重置额度的评估。非 OAuth 的 OpenAI 账号不支持这个查询，会记成上游证据失败。

开了实时用量时，报告用 7 天的 `window_stats.tokens` 去缩放所选日期的聚合；没开时，报告假定所选日期就是额度窗口。两个都没开时，额度百分比和整窗口推算值都是未知。

## 价格文件

只有重新计价时才准备私有价格文件，传 `--pricing-file`；比较候选模型再加 `--baseline-model`。单位是 USD／百万 Token，价格以事件发生日期适用的官方价格页为准，`as_of` 和 `source_urls` 记下出处：

```json
{
  "as_of": "YYYY-MM-DD",
  "source_urls": ["https://provider.example/pricing"],
  "models": {
    "model-id": {
      "input": 1,
      "cached_input": 0.1,
      "output": 5,
      "cache_creation": 1.25
    }
  }
}
```

请求日志显示用了长上下文、区域处理、priority、batch 或写缓存时，核对 `long-context`、`regional-processing`、`priority`、`batch` 和 `cache-write` 的加价。后台的聚合行不一定还原得出这些按请求计的附加费。

只有额度或实时用量的响应给出了利用率，才能粗算整窗口的等价成本：所选周期的实际上游成本除以观测到的额度百分比；开了实时用量时，先按 `window_tokens / period_tokens` 缩放。所选周期和额度窗口一致时最可靠。这个数只能看出模型之间的价格差够不够解释额度掉得快，证明不了供应商真按 API 美元价扣额度。

## 证据怎么取舍

从强到弱：

1. 请求用量日志，或 `model_source=mapping` 聚合：确认请求模型和实际上游模型。
2. 实时上游额度（有上面的副作用）：确认当前余量和重置窗口。
3. 部署版本的源码：确认字段含义和路由行为。
4. 面板上的标签：只说明怎么显示。

下面几个「模型」和「成本」各是各的，不要拿一个推另一个：请求模型、写进出站请求的上游模型、响应里的模型、Sub2API 计费用的模型、Sub2API 存下的成本、供应商额度或 API 价格的等价值。
