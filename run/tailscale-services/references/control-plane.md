# Service 控制面

要建或改 Service 定义、审批 host、改 autoApprovers，或者需要用户在浏览器里登录控制台时读这份。

## 定义和 host 是两边

控制台或 Services API 管定义：`svc:` 名称、描述、endpoint、tags、MagicDNS 名称和 TailVIP。host 上的 CLI 管映射：把这些 endpoint 接到哪个 backend，并 advertise 出去。一边的状态不能从另一边推出来，两边都要读。

## 用 API 还是控制台

已经有一个权限够、范围合适的 API 凭据（OAuth client 或用户给的 access token）时，用 [Services API](https://tailscale.com/api#tag/services)：列出、读取、更新、删除 Service，列出 host，读写某台 host 的审批状态。没有就走控制台，不为了绕开交互登录去新建 API key，也不去浏览器里翻隐藏的 token。

## 用配置文件改 host

[配置文件格式](https://tailscale.com/docs/reference/tailscale-services-configuration-file.md)就是 `tailscale serve get-config` 的输出格式。

- `set-config` 写入后默认就 advertise，文件里写 `"advertised": false` 才不发布。想先验证再发布：drain，用带 `"advertised": false` 的文件写入，验完再 `tailscale serve advertise svc:<name>`。
- `set-config --all` 用文件内容替换这台节点上的全部 Service 和发布列表，文件里漏了谁，谁就被删、被取消发布。只改一个 Service 时用 `--service=svc:<name>`。
- `--service` 模式下 `"advertised": false` 只能不新增发布，已经在发布的不会被撤下，要另外 `drain`。
- `get-config` 导出是有损的（见 SKILL.md「改之前先看清现状」），拿它改一改再 `set-config`，会丢掉 `--set-path` 路径、`text:` 目标、`--accept-app-caps` 和 `--proxy-protocol`。
- HTTPS 端口反代 `http://` backend 时，`get-config` 把协议导出成 `http`，再 `set-config` 就变成明文 HTTP 监听（[tailscale/tailscale#18381](https://github.com/tailscale/tailscale/issues/18381)）。这类映射不要靠导出再写回，改和恢复都用 CLI。
- `set-config` 先改发布列表、再写 Serve 配置。命令失败时发布列表可能已经被换掉，别的 Service 被取消发布、映射却还在。失败后也要回读 `AdvertiseServices` 和改前对比，少了的 `tailscale serve advertise` 补回，多了的 `drain`。

流程：先确认候选文件能解析（格式是 HuJSON，带注释或尾逗号时 `jq` 不认），再和改前快照 diff，确认只动了目标 Service；写完重新导出再 diff，连同 `AdvertiseServices` 一起对比。写坏了就用改前快照恢复，再读回确认；快照里缺的部分照改前的 `serve status --json` 用 CLI 补回。候选文件和 diff 里不放 auth key 或无关身份信息。

## 审批和 autoApprovers

host 必须先是 tag 身份才能 advertise。审批有两种：

- Owner、Admin 或 Network admin 在控制台 Services 页批准待审的 host；
- policy 里的 `autoApprovers.services` 按 tag 等选择器自动批准某个 Service 或带某个 tag 的一组 Service。盘点现有规则时，审批人列表里不一定只有 tag。

autoApprovers 是整个 tailnet 的 policy 改动，以后所有符合条件的 host 都会自动通过。用户要的只是这一次部署时，不加。

改 grants 前，把能匹配到这个 Service 的规则全找出来。

## 用户在浏览器登录的交接

控制台是唯一的控制路径、又需要用户本人完成 OAuth 或 MFA 时：

1. 为这次任务开一个独立的浏览器自动化会话。要复用已登录的浏览器 profile，先复制一份再用，不直接操作用户正在用的浏览器。
2. 浏览器跑在远程主机上、用户要通过自动化工具的网页 Dashboard 看到它时，Dashboard 只监听 loopback 上一个专用端口，让用户用 SSH 本地端口转发访问，不绑局域网地址或 `0.0.0.0`。
3. 打开登录页，只请用户完成登录和 MFA。创建 Service、批准 host 由你来做，除非用户自己想做。
4. 做完从最终页面回读结果。点击成功或弹出的提示不算状态已经生效。
5. 收尾时只关这次任务的会话，停掉它的 Dashboard，删掉临时 profile 副本，让用户自己断开 SSH 隧道。

登录后的账号角色不够时就停下报告，不换账号，也不为了能操作去放宽 policy。

## 留什么证据

每次控制面写入后记一份摘要，不截整个 tailnet 的图：

- Service 名称和 endpoint；
- 控制面返回的 MagicDNS 名称和 TailVIP；
- 目标 host 的身份和 tag；
- 写入后 host 的审批和连接状态；
- 目标 Service 在 host 上改前改后的映射；
- 同一 host 上没动的 Service 名称，以及它们的映射是否完全没变。

不保存登录 cookie、auth key、device key、整份 policy 文件或无关设备清单。
