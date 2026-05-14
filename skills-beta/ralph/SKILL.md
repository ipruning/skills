---
name: ralph
description: "Run the full deep-reasoning workflow for hard technical problems: gather context, ask Oracle, then verify with local evidence."
metadata:
  version: '4'
---

# Ralph

- 用 rp-cli 构建上下文 + Oracle CLI 深度推理 + reflect 交叉验证。
- 不要盲信外部模型结论。

## 标准作业流程

- [Review SOP](./sop/review.md): 当前仓库分支 review，用 pueue 隔离 Oracle（默认）
- [PR Review SOP](./sop/review-pr.md): 跨仓库 PR review，克隆到 /tmp + rp-cli 独立窗口 + Oracle

## 协同技能

- **reflect**：就算是 Oracle 也可能给出假阳建议，你需要学会交叉验证。
- **tmux**：用于交互式监控（可选），主线异步执行用 pueue。
