# React Convex AuthKit Kumo

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

pnpm --filter web add @cloudflare/kumo lucide-react @workos-inc/authkit-react @convex-dev/workos

cd my-app && pnpm --filter @my-app/backend exec convex ai-files install
```

如果用户给了真实项目名，把命令里的 `my-app` 和 `@my-app/backend` 换成生成后的目录名和 backend package 名。先读生成后的 `package.json` 和 `packages/backend/package.json`，再执行 package filter。

`ai-files install` 装出的 guidelines 和 skills 是写 Convex 代码的第一资料源。资料优先级是：本地生成的 guidelines 和 skills，`node_modules` 里包的 README 和 `.d.ts`，再到网络搜索。Convex-managed WorkOS AuthKit 较新，同一问题搜一次没有答案就转本地资料，不要反复搜。

跑 `pnpm run dev:setup` 之前，先按 `ai-files install` 装出的 `convex-setup-auth` skill 写好 `packages/backend/convex.json` 的 `authKit` 段。AuthKit 的自动 provision 由这个文件触发，没有它 `dev:setup` 不会碰 WorkOS。`localEnvVars` 用 `"VITE_WORKOS_CLIENT_ID": "${authEnv.WORKOS_CLIENT_ID}"`。端口对齐 web dev server 的实际端口。

然后跑 `pnpm run dev:setup`。若出现 Convex device login，立刻把 login URL 和 code 发给用户。等待期间继续写不依赖登录态的代码。Team 有多个时问用户。Project name 不接受默认值 `backend`，用真实项目名。provision 完成后 AuthKit 相关配置已就位，不要手工重做。

UI 用 Cloudflare Kumo，只进 `apps/web`。`src/index.css` 引入 `@cloudflare/kumo/styles`，保留脚手架已有的 workspace UI globals import。图标用 `lucide-react`。页面内容居中，有最大宽度。层级靠间距和字号表达。避免卡片套卡片、badge 堆砌。列表默认只读，编辑态点击才出现。

跑通最小闭环：未登录用户看到登录入口，登录后进 `/dashboard` 并显示当前用户。首次登录创建内部 user，用 `authIdentities` 表把 WorkOS identity 映射到 `users._id`。业务表引用内部 `users._id`。服务端由登录身份推导内部 user 再做读写。

同时建一条 E2E 通道：dev-only 的登录绕过，前端 `VITE_E2E_AUTH_ENABLED` 与 Convex env 双开关，仅 dev deployment 可开启。E2E 身份走与真实用户登录相同的内部 user 创建路径。配一个 `testing:resetE2EData` mutation 清理测试数据。

完成前做这些事：

- `pnpm run check` 通过。
- 用浏览器走 E2E 通道确认登录态、`/dashboard` 渲染和控制台状态。
- 把端口约定、check 命令、E2E 通道用法、过程中发现的组件库坑写进项目根 `AGENTS.md`。
- 列出还需要用户手动完成的步骤。
