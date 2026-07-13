# Project Notes Brief

在当前项目里做一个 Project Notes 工具，projects 相关表和路由从这里开始建。

- `/dashboard` 列出当前用户的 projects，可创建。选中后显示其 notes。
- notes 可创建，可编辑 title 和 body，可标记 archived。默认隐藏 archived，提供切换。
- 所有变化实时出现在页面上。

数据：projects 含 `name`、`ownerId`、`createdAt`。notes 含 `projectId`、`ownerId`、`title`、`body`、`status`、`createdAt`、`updatedAt`。`status` 是 `draft`、`active` 或 `archived`。`ownerId` 用内部 `users._id`。

权限：服务端通过 `ctx.auth.getUserIdentity()` 推导内部 user。用户只能读写自己的 projects 和 notes。

UI：视觉体系见 react ref。Project Notes 专属的一点是空状态引导创建第一个 project 或 note。

完成后用浏览器走 E2E 通道确认创建、编辑、archive、切换显示流程。控制台没有 app error 或 warning。再跑 `pnpm run check`，简述改了哪些关键文件。
