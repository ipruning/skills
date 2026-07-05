---
name: explain-diff-html
description: "Build a rich, self-contained interactive HTML explainer for a code change, diff, branch, or PR: layered background, intuition with diagrams, a code walkthrough, and a self-check quiz. Use when the user wants a durable, shareable explanation page. Not for a quick in-chat summary of a small diff."
metadata:
  version: "2"
---

# Explain Diff HTML

把一个代码变更讲成一页可交互的 HTML。动笔之前先广泛探索变更周边的代码，讲解的深度取决于对现有系统的理解，不取决于 diff 本身。

## 四个板块

- Background：讲与变更相关的现有系统。读者水平未知，先给一段初学者能读的深背景，标注熟悉者可跳过，再收窄到与本变更直接相关的部分。
- Intuition：讲变更的核心直觉，重在本质不在细节。用玩具数据举具体例子，大量使用图示。
- Code：高层代码走读，按可理解的方式给改动分组和排序。
- Quiz：五道中等难度的交互选择题，难到需要真正理解变更才能答对，但不出脑筋急转弯。点击后判对错并给反馈，帮读者确认自己真的看懂了。

## 交付形态

- 单个自包含 HTML 文件，内联全部 CSS 和 JavaScript。整页长文加节标题和目录，顶层结构不用 tab。加基础响应式样式，手机能看。
- harness 有自己的 HTML 交付机制时用它交付，比如 Claude Code 的 Artifact。没有就写到仓库外的全局位置，文件名以当天日期开头，按 `YYYY-MM-DD-explanation-<slug>.html` 命名，方便按时间排序且不进版本控制。
- 行文要 Martin Kleppmann 式的清晰流畅，classic style，节与节之间过渡自然。
- 关键概念、定义和重要边界情况用 callout 突出。

## 图示

- 挑少数几个图示家族全文复用，用同一族图解释不同情形。常用两类：解释 UI 变更用极简版的产品 UI 示意，讲数据流用组件间的系统图，系统图里必须带示例数据。
- 不用 ASCII 图。图示用简单 HTML 结构画，列表用 HTML 列表。
- 代码块用 `<pre>`。改用自定义 div 时，CSS 必须含 `white-space: pre-wrap`，否则浏览器会把换行压成一行。保存前扫一遍源码里的每个代码块，确认这条都满足。
