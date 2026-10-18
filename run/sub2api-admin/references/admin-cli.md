# Sub2API 管理员 CLI 参考

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `SUB2API_BASE_URL` | 站点根地址，或后台的 `/admin/...` 页面 URL，CLI 会截成根地址。只能用 HTTPS，本机回环地址才允许 HTTP；URL 里不能带用户名密码。 |
| `SUB2API_ADMIN_API_KEY` | 第一优先的凭据，以 `x-api-key` 发送。 |
| `SUB2API_JWT` | 第二优先，管理员访问令牌。 |
| `SUB2API_ADMIN_EMAIL`、`SUB2API_ADMIN_PASSWORD` | 前两个都没设时，CLI 用它们登录换 JWT。 |
| `SUB2API_LOGIN_TOTP_CODE` | 登录返回 `requires_2fa` 时用，每次给新码。 |
| `SUB2API_USER_AGENT` | 覆盖默认的 `sub2api-admin-cli/1.0`，用法见[会话绑定](auth.md#会话绑定)。 |
| `SUB2API_REQUEST_TIMEOUT_MS` | 请求加读完响应体的超时，默认 30000，范围 1–2147483647。 |

用 JWT 或密码时，同样在子 shell 里读入：

```bash
(
skill_dir="<包含此 SKILL.md 的目录>"
export SUB2API_BASE_URL='https://your-sub2api-host'
printf 'Sub2API 管理员 JWT：' >&2
IFS= read -r -s SUB2API_JWT; printf '\n' >&2; export SUB2API_JWT
# 或者让 CLI 用账号密码登录：
# export SUB2API_ADMIN_EMAIL='admin@example.com'
# printf 'Sub2API 管理员密码：' >&2
# IFS= read -r -s SUB2API_ADMIN_PASSWORD; printf '\n' >&2; export SUB2API_ADMIN_PASSWORD
# printf 'Sub2API TOTP：' >&2  # 只在登录要求 2FA 时
# IFS= read -r -s SUB2API_LOGIN_TOTP_CODE; printf '\n' >&2; export SUB2API_LOGIN_TOTP_CODE
node "$skill_dir/scripts/sub2api-admin.js" system version
)
```

写请求超时后，CLI 会提示远端可能已经生效，不要自动重试，先用读取接口查清楚。

## 路由诊断的参数

`diagnostics openai-routing` 的入口和 `--ids`、`--search` 的读取范围见主文[查路由和 Token 用量](../SKILL.md#查路由和-token-用量)。其他参数：

- `--pricing-file`：按「请求模型 → 上游模型」右边的上游模型重新计价。
- `--baseline-model`：把同一批 Token 全部按指定模型重算，用来比较候选模型的额度和成本。
- `--include-upstream-quota`、`--include-active-usage`：会碰上游，见[额度与实时用量](routing-investigation.md#额度与实时用量)。
- `--file`：报告写进 `0600` 新文件；目标已存在时不发请求。

没加两个上游参数时，报告里的 `quota`、`usage` 是 `null`。没给价格文件时 `pricing` 是 `null`；给了但没有额度或用量证据时，`pricing.used_percent` 是 `null`。

## Admin API Key

```bash
skill_dir="<包含此 SKILL.md 的目录>"
node "$skill_dir/scripts/sub2api-admin.js" admin-key status
node "$skill_dir/scripts/sub2api-admin.js" admin-key regenerate --file /secure/path/admin-api-key.txt
node "$skill_dir/scripts/sub2api-admin.js" admin-key delete
```

`regenerate` 和 `delete` 改的是生产环境，会让所有用旧 Key 的自动化失效。`regenerate` 必须带 `--file`：CLI 先以 `0600` 建好这个文件，目标已存在、父目录不存在或不可写时不发请求。

服务端轮换成功后，网络中断或写盘失败仍可能让只返回一次的新 Key 丢失。请求发出后出错时，CLI 保留预留的文件。这时先 `unset SUB2API_ADMIN_API_KEY`，改用 JWT 或账号密码跑 `admin-key status` 看远端状态，再决定删文件还是重新轮换。

## 通用 `api`

```bash
skill_dir="<包含此 SKILL.md 的目录>"
node "$skill_dir/scripts/sub2api-admin.js" api GET /admin/groups/all
```

路径写 `/admin/...` 或 `/api/v1/admin/...` 都行，出了 `/api/v1/admin` 的一律拒绝。

- 请求体用 `--json` 或 `--file`。这里的 `--file` 是读入请求体，存响应要用 `--output-file`。
- 响应不是 JSON 时加 `--raw`。
- 敏感或大的响应用 `--output-file`：CLI 发请求前以 `0600` 新建文件，目标已存在就不发；请求发出后出错也保留文件。账号导出一定走这条路。
- 支持幂等键的写接口加 `--idempotency-key`。

## 上游 Skill 没覆盖的接口

CLI 只管鉴权和 Sub2API 的 JSON 响应外壳，不知道每个接口的字段。上游 Skill 的 `references/admin-cli.md` 没列到的接口，部署方给了 Admin API 文档（如 OpenAPI 文件）就直接用；没有时：

1. `system version` 记下部署版本。语义化版本号不等于镜像摘要或 commit SHA。
2. 在已部署的管理面板里看网络请求，确认方法、路径、查询参数和请求体。
3. 在对应版本的源码（[Wei-Shaw/sub2api](https://github.com/Wei-Shaw/sub2api)，路由在 `backend/internal/server/routes/admin.go`）里找到路由，看中间件、handler、输入校验、敏感输出和副作用。
4. 用 `api <METHOD> <admin-path>` 调。

拿不到对应版本的源码时，以已部署面板的请求为准，不拿别的版本的字段猜。
