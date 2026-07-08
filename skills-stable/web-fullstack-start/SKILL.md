---
name: web-fullstack-start
description: Start or continue a practical Web full-stack app such as a React dashboard, SaaS, internal tool, or product prototype, where the user needs a coherent stack choice, scaffold command, auth/data boundary, and first usable feature. Not for narrow edits inside an already established stack.
metadata:
  version: "1"
---

# Web Full-Stack Start

这个技能用于把「我要做一个 Web app」翻译成可执行的启动路线。先确定用户是在启动新项目，还是在已有项目里加第一批真实功能。

默认路线是 React、TanStack Router、Convex、Convex-managed WorkOS AuthKit、shadcn + Base UI、Vite+ 和 pnpm。它适合需要登录、数据读写、实时同步和少量后端胶水代码的 dashboard、SaaS 原型和内部工具。Cloudflare Kumo 只在用户明确想要 Cloudflare 风格成品设计系统时加到 web app。

如果用户明确要 Next.js SSR、SEO 内容站、React Native native、付款闭环、公司既有 Auth/DB 标准，先按用户的既有约束工作，不要强行套默认路线。

## 启动新项目

读 `references/react-convex-authkit-baseui.md`，按里面的顺序做到跑通最小闭环。

关键边界是：WorkOS identity 只作为登录身份，业务表引用内部 `users._id`。Convex functions 通过 `ctx.auth.getUserIdentity()` 推导内部 user，再做数据读写。

## 添加第一批功能

如果用户要一个真实可用的小功能，读 `references/starter-feature-project-notes.md`。这是当前默认 starter feature。

这个 brief 可以作为形状参考。用户给了别的产品目标时，保留同样的边界：内部 user、服务端授权、Convex 实时数据、UI 组件只进 web/UI package、简单逻辑保持直接。

## 运行与交接

AuthKit 的自动 provision 依赖 `convex.json` 的 `authKit` 配置。需要 Convex 登录或 deploy key 时，给出具体阻塞项。等待用户登录时继续完成不依赖登录态的代码。

完成后运行项目自己的检查命令。把端口约定、检查命令、E2E 通道、组件库坑写进项目根 `AGENTS.md`，给后续会话复用。
