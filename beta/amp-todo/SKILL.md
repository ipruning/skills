---
name: amp-todo
description: 'Execute AMPDO comments in codebase. Triggers: ampdo, find ampdo.'
metadata:
  version: '1'
---

# Resolving AMPDO

搜索代码库中的 AMPDO: 注释来收集反馈和执行指令。

## 搜索过程

### 方法 1: ripgrep（推荐，更简洁）

```bash
rg "AMPDO:" -C 3
```

### 方法 2: ast-grep（精确匹配注释节点）

```bash
ast-grep scan --inline-rules '
id: find-ampdo
language: python
rule:
  kind: comment
  regex: "AMPDO:"
' packages apps
```

注意：对于简单的注释搜索，ripgrep 更快更简洁。ast-grep 适合需要区分代码/注释/字符串的场景。

## 审查过程

- 阅读每个 AMPDO 注释及其周围的代码上下文
- 根据反馈采取适当行动：实现请求的更改、解决问题或遵循指令
- 按文件和注释类型组织发现结果
- 执行任何操作项或特定更改请求

## 输出格式

- 按文件路径分组
- 显示每个 AMPDO 注释的行号和完整上下文
- 在最后总结关键主题和操作项

## 预期操作

找到 AMPDO: 注释后，agent 应该：

1. 分析每个注释中的反馈或指令
2. 实现任何请求的代码更改
3. 解决提出的任何问题或顾虑
4. 在处理完成后删除或更新 AMPDO: 注释
5. 提供所有已采取操作的摘要
