# React Convex AuthKit Base UI

初始化一个 React Web app。按顺序执行：

```bash
pnpm create better-t-stack@latest my-app \
  --frontend tanstack-router \
  --backend convex \
  --runtime none --api none --auth none --payments none \
  --database none --orm none --db-setup none \
  --package-manager pnpm --git --install \
  --web-deploy none --server-deploy none \
  --addons vite-plus --examples none

cd my-app && pnpm --filter @my-app/backend exec convex ai-files install
```

`--addons vite-plus` 就是栈里说的 Vite+。这套 flag 随 Better-T-Stack 版本漂移，某个 flag 报错就跑 `pnpm create better-t-stack@latest --help` 看当前值，以实测为准。

命令里的 `my-app`、`--filter @my-app/backend` 都是占位。先读生成后的 `package.json`、`packages/backend/package.json` 和 `packages/ui/package.json`，拿到实际的目录名、web package 名、backend package 名和 UI package 名，再执行 package filter，别照抄这里的名字。

当前 Better-T-Stack 生成物已经自带 shadcn + Base UI：`packages/ui/components.json` 通常是 `style: "base-lyra"`，`packages/ui/package.json` 有 `@base-ui/react` 和 `shadcn`，`apps/web/src/index.css` 只导入 workspace UI 的 globals。不要再把 Cloudflare Kumo 当默认 UI 依赖加进去。

Base UI 的包名是 `@base-ui/react`，不是旧的 `@base-ui-components/react`，看到旧名不要往回改。`-b base` 选组件底座，`-p nova` 是 shadcn preset，生成后 `components.json` 的 `style` 值是 `base-lyra`，三者是不同层级不同取值。

WorkOS 依赖按实际 import 位置安装。通常是 web package 加 `@workos-inc/authkit-react`，backend package 加 `@convex-dev/workos`。

如果不是 Better-T-Stack，而是普通 Vite 项目，需要让 shadcn 自己初始化，已测过的非交互命令是：

```bash
pnpm dlx shadcn@latest init -t vite -b base --no-monorepo -p nova -n my-app
```

`-b base` 才是 Base UI。不要写 `-p base-nova`，CLI preset 名是 `nova`。缺 `--no-monorepo` 或 `-p nova` 会进入交互提示。

在 Better-T-Stack 里加新组件时，对 `packages/ui` 操作：

```bash
pnpm --filter @my-app/ui exec shadcn add dialog select badge --yes --overwrite
pnpm run format
```

`--yes` 仍可能在已有依赖组件如 `button.tsx` 上提示是否覆盖，新 scaffold 可用 `--overwrite`。已有项目先 `--dry-run` 或看 diff，别无意覆盖用户改过的 UI 组件。`shadcn add` 生成后先 format，再跑 UI package typecheck 和 web build。

`ai-files install` 装出的 guidelines 和 skills 是写 Convex 代码的第一资料源。资料优先级是：本地生成的 guidelines 和 skills，`node_modules` 里包的 README 和 `.d.ts`，再到网络搜索。Convex-managed WorkOS AuthKit 较新，同一问题搜一次没有答案就转本地资料，不要反复搜。

跑 `pnpm run dev:setup` 之前，先按 `ai-files install` 装出的 `convex-setup-auth` skill 写好 `packages/backend/convex.json` 的 `authKit` 段。AuthKit 的自动 provision 由这个文件触发，没有它 `dev:setup` 不会碰 WorkOS。`localEnvVars` 用 `"VITE_WORKOS_CLIENT_ID": "${authEnv.WORKOS_CLIENT_ID}"`。端口对齐 web dev server 的实际端口。

然后跑 `pnpm run dev:setup`。若出现 Convex device login，立刻把 login URL 和 code 发给用户。等待期间继续写不依赖登录态的代码。Team 有多个时问用户。Project name 不接受默认值 `backend`，用真实项目名。provision 完成后 AuthKit 相关配置已就位，不要手工重做。

UI 用 `packages/ui` 里的 shadcn + Base UI 组件，图标用 `lucide-react`。视觉体系：内容居中有最大宽度，层级靠间距和字号，不堆卡片和 badge，列表默认只读、点击才进编辑态。Base UI 的 `Select` 触发器实际 role 是 `combobox`，测试定位不要把它当普通 button。`Dialog` 打开后确认焦点落在第一个可编辑控件。

Kumo 只进 web app，不进 Convex backend。

跑通最小闭环：未登录用户看到登录入口，登录后进 `/dashboard` 并显示当前用户。首次登录创建内部 user，用 `authIdentities` 表把 WorkOS identity 映射到 `users._id`。业务表引用内部 `users._id`。服务端由登录身份推导内部 user 再做读写。

同时建一条 E2E 通道：dev-only 的登录绕过，前端 `VITE_E2E_AUTH_ENABLED` 与 Convex env 双开关，仅 dev deployment 可开启。E2E 身份走与真实用户登录相同的内部 user 创建路径。配一个 `testing:resetE2EData` mutation 清理测试数据。

完成前做这些事：

- `pnpm run check` 通过。
- 用浏览器走 E2E 通道确认登录态、`/dashboard` 渲染和控制台状态。
- 把端口约定、check 命令、E2E 通道用法、过程中发现的组件库坑写进项目根 `AGENTS.md`。
- 列出还需要用户手动完成的步骤。
