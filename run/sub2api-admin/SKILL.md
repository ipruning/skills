---
name: sub2api-admin
description: >-
  通过 Sub2API 管理员 API 查模型路由、用量、额度和计费，做后台操作，或评估候选模型时使用。
metadata:
  version: "2"
---

# Sub2API 管理

Sub2API 上游仓库自带一个同名 Skill（`skills/sub2api-admin`），管账号、分组、代理、兑换码、错误规则、TLS 指纹这些资源的增删改查，各接口的路径和请求体以它为准。本包只补它没有的：路由和额度调查、邮箱密码登录与会话绑定、Admin API Key 轮换、二次验证，以及几条安全护栏。

## 先读上游 Skill

按实例的部署版本取对应 tag 的那份，读它的 `SKILL.md` 和 `references/admin-cli.md`。`system version` 返回的 `version` 加上 `v` 前缀就是 tag：

```bash
(
set -eo pipefail
ref='v<system version 返回的 version>'
dest="$(mktemp -d)/sub2api-admin"
tree=$(gh api "repos/Wei-Shaw/sub2api/contents/skills?ref=$ref" --jq '.[] | select(.name == "sub2api-admin") | .sha')
[ -n "$tree" ] || { echo "这个 ref 下没有 skills/sub2api-admin" >&2; exit 1; }
files=$(gh api "repos/Wei-Shaw/sub2api/git/trees/$tree?recursive=1" --jq '.tree[] | select(.type == "blob") | .path')
[ -n "$files" ] || { echo "skills/sub2api-admin 是空目录" >&2; exit 1; }
while IFS= read -r f; do
    mkdir -p "$dest/$(dirname "$f")"
    gh api -H 'Accept: application/vnd.github.raw' \
        "repos/Wei-Shaw/sub2api/contents/skills/sub2api-admin/$f?ref=$ref" > "$dest/$f"
done <<< "$files"
echo "$dest"
)
```

任何一步失败都会以非零退出，不打印目录。tag 不存在时 `gh` 报 `No commit found for the ref`，多半是自编译或开发版。这时可以取最新 release（`gh release view -R Wei-Shaw/sub2api --json tagName -q .tagName`）的那份，但只当找接口路径的索引，字段和副作用按[上游 Skill 没覆盖的接口](references/admin-cli.md#上游-skill-没覆盖的接口)对照实例的面板请求和源码核实，并在结论里说明。下载的文件不在里面 `cd` 运行，用 `node "<下载目录>/scripts/sub2api-admin.js" ...` 调。

上游的做法有几处要换成本包的：

- 上游的 `accounts export --file` 用默认权限写文件，会覆盖已有文件，而导出含上游凭据。导出改用本包的 `api GET <导出路径> --output-file <新路径>`，以 `0600` 新建。
- 上游让人用 `curl` 登录拿 JWT，密码和令牌会留在 shell 历史和终端里。改用本包的邮箱密码登录，见[鉴权](references/auth.md#登录)。
- 上游遇到 `INVALID_ADMIN_KEY` 就建议重新生成 Key。这只说明当前 Key 无效，不是重新生成的理由，见下文。
- 上游脚本只认 Admin API Key 和 JWT，没有请求超时，`api` 也不带幂等键。要邮箱密码登录、要超时控制或要传 `--idempotency-key` 时，用本包的 `api` 调同一路径。

## 本包的 CLI

`scripts/sub2api-admin.js` 不带参数运行会打印全部命令：`system version`、`diagnostics openai-routing`、`admin-key` 和通用 `api`。

环境里已经配好 `SUB2API_BASE_URL` 和凭据就直接用。要现输时，凭据放在子 shell 里用 `read -s` 读入，退出后不留在当前 shell；连续几条命令放进同一个 `(...)`，省得重复输入。CLI 按 Admin API Key、JWT、邮箱密码的顺序取第一种可用的：

```bash
(
skill_dir="<包含此 SKILL.md 的目录>"
export SUB2API_BASE_URL='https://your-sub2api-host'
printf 'Sub2API Admin API Key：' >&2
IFS= read -r -s SUB2API_ADMIN_API_KEY; printf '\n' >&2
export SUB2API_ADMIN_API_KEY
node "$skill_dir/scripts/sub2api-admin.js" system version
)
```

按需读：

- [CLI 参考](references/admin-cli.md)：环境变量、各命令的参数和输出文件、`admin-key` 轮换失败后怎么恢复、上游没覆盖的接口怎么找。用 JWT 或密码登录、调 `api`、轮换 Admin API Key 时读。
- [鉴权](references/auth.md)：三种凭据各能调什么、二次验证、会话绑定、Admin API Key 的生命周期。选凭据、遇到 403 或 401、要用浏览器会话时读。
- [路由与额度调查](references/routing-investigation.md)：报告里的数据从哪来、额度参数的副作用、价格文件、各个「模型」字段的区别。解读报告、重新计价或比较候选模型时读。

## 查路由和 Token 用量

先跑 `diagnostics openai-routing`，不在后台逐页翻。它读部署版本、OpenAI 账号列表，以及 Sub2API 记下的「请求模型 → 上游模型」Token 聚合，不发推理请求。

完整报告含账号名称和原始错误，不要直接打到对话里。下面的脚本在内存里接住输出，只回传汇总字段。CLI 失败返回非零；`complete: false` 表示部署版本或某个账号的证据没取到，退出 2，这时的数字不是完整用量。报告超过 `spawnSync` 默认的 1 MiB 缓冲区时也按失败处理，不会截断后报成功；账号多时改用下面的 `--file`。

```bash
skill_dir="<包含此 SKILL.md 的目录>"
node --input-type=module - "$skill_dir/scripts/sub2api-admin.js" diagnostics openai-routing \
  --start-date YYYY-MM-DD \
  --end-date YYYY-MM-DD \
  --timezone Asia/Shanghai \
  --ids '<account-ids>' <<'JS'
import { spawnSync } from "node:child_process";

const result = spawnSync(process.execPath, process.argv.slice(2), { encoding: "utf8" });
if (result.status !== 0) {
    console.error("诊断失败；原始输出未带入对话。");
    process.exit(result.status > 0 ? result.status : 1);
}
try {
    const { summary } = JSON.parse(result.stdout);
    const counts = ["accounts", "accounts_failed", "upstream_evidence_failed",
        "requests", "total_tokens", "mismatch_requests", "mismatch_tokens"];
    if (typeof summary.complete !== "boolean" ||
        !counts.every((key) => Number.isSafeInteger(summary[key]) && summary[key] >= 0)) {
        throw new Error("invalid summary");
    }
    const selected = Object.fromEntries(["complete", ...counts].map((key) => [key, summary[key]]));
    console.log(JSON.stringify({ summary: selected }));
    process.exit(summary.complete ? 0 : 2);
} catch {
    console.error("诊断报告无法解析；原始输出未带入对话。");
    process.exit(1);
}
JS
```

要看具体哪条路由时，照上面的脚本在内存里挑出需要的路由字段，不输出账号名称、整份报告或原始错误。报告大或要留存时加 `--file <新路径>`，CLI 以 `0600` 新建，目标已存在就不发请求；不用固定的共享 `/tmp` 文件名。不许落盘时就只用上面的内存方式。

`--ids` 只筛统计和输出，CLI 还是会先读到全部 OpenAI 账号。`--search` 交给服务端过滤，也不保证只读到指定 ID。任务不允许碰其他账号时，不跑这份报告，去部署版本的源码里找按单个账号查询的接口；找不到就如实说缺这份证据。只有任务本来就是查全部账号时，才两个都不传。

普通路由调查不需要价格文件。只有重新计价或比较候选模型时才加 `--pricing-file`、`--baseline-model`，做法见[价格文件](references/routing-investigation.md#价格文件)。

## 会碰上游的两个参数

报告默认不查上游额度（`--include-upstream-quota`），也不查账号实时用量（`--include-active-usage`）。这两个查询走的是 `GET`，却会请求供应商，并可能触发自动重置额度：账号开了自动重置且达到阈值时，后台会保存账号状态并消耗 reset credit。只在任务确实需要上游证据、而且能接受这些副作用时才加。细节见[额度与实时用量](references/routing-investigation.md#额度与实时用量)。

## 浏览器什么时候用

管理面板调的也是这套 HTTP API，没有更高权限的后门。浏览器只用来过 CAPTCHA、passkey、OAuth 授权和回调、TOTP 输入、插件界面，核对部署版本是否漂移，以及看渲染或只在面板上出现的问题。

## 容易出事的地方

- 不能只凭 HTTP 方法判断安全。上面两个额度查询是 `GET`；`POST .../quota/refresh` 会存快照并写审计日志。
- 管理员凭据、账号导出和诊断报告不贴进聊天、不提交 Git。敏感或大的响应用本包 `api` 的 `--output-file` 写进 `0600` 新文件。
- 写请求超时后不自动重试，远端可能已经生效。
- `INVALID_ADMIN_KEY` 只说明当前 Key 无效，不是去重新生成的理由。全站只有一个 Admin API Key，重新生成会让旧 Key 立刻失效，所有在用它的自动化一起断。
- 部署开了会话绑定时，复用浏览器的 JWT 但出口 IP 或 User-Agent 对不上，会把浏览器那个会话的刷新令牌全部吊销。复用前读[会话绑定](references/auth.md#会话绑定)。
