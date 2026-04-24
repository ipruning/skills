---
name: amp-skill-smoke
description: 'Smoke-test any SKILL.md by spawning a sub-agent. Triggers: smoke-test SKILL.md, validate skill file, test skill.'
metadata:
  author: ipruning
  version: "3.0.0"
---

# Skill 冒烟测试

验证一份 SKILL.md 是否足以让一个**全新的 SubAgent** 独立完成任务，而不依赖先验知识。

## SubAgent 运行时模型

以下结论经实测探针验证，非推测。设计测试时**必须**以此为据。

### 可见上下文

| 来源 | 内容 | 对测试的影响 |
|------|------|-------------|
| **AGENTS.md / CLAUDE.md** | 项目及上级目录的所有指导文件，完整注入 | ⚠️ 可能泄漏被测 skill 的线索（如 "use Modal for deployment"） |
| **available_skills 列表** | 全部 skill 的名称、描述、文件路径（仅元数据） | ⚠️ SubAgent 知道 skill 在哪，可自行 `Read` 原版 |
| **环境信息** | OS、工作目录、仓库 URL、日期 | 低风险 |
| **磁盘文件** | 可通过 `Read`/`Grep`/`glob` 读取任意路径 | 🚨 能直接读原版 SKILL.md，绕过 mutation |
| **MCP 工具** | logfire、openai 等 MCP server | 工具集与父线程不同 |

### 不可见上下文

| 来源 | 说明 |
|------|------|
| **loaded_skill 正文** | 父线程已加载的 skill 内容不会传递 |
| **对话历史** | 父线程的全部消息不可见 |
| **附件** | 父线程 user message 中的附件不传递 |
| **父线程 ID** | 无 "continuing from" 引用 |

### 测试设计四条铁律

1. **`/tmp` 隔离无效**——SubAgent 可读磁盘任意文件。把阉割版放 `/tmp` 再说"只读这个"行不通，SubAgent 仍可能（且往往会）读原版。
2. **Mutation 必须物理替换原文件**——临时改写磁盘上的 SKILL.md，测试完恢复（见 Step 5）。
3. **task-prompt 须显式禁止路径**——告知 SubAgent 不得读取 skills 目录下的其他文件，仅用指定源。
4. **AGENTS.md 泄漏不可避免**——若 AGENTS.md 提及被测工具的关键信息，审计时应视为"已知上下文"，不计入 skill 教学效果。

## 工作流

### Step 0：选定被测 Skill

未指定时按优先级选取：

1. 刚刚编辑过的 SKILL.md（回归测试）
2. 最关键 / 最常用的 skill
3. 随机选 1 个 `**/SKILL.md`

### Step 1：设计测试用例

选 2–4 个任务，合力覆盖以下维度：

- **语法正确性**——import、函数签名、必选参数
- **行为正确性**——分页、重试、时区、错误处理
- **歧义消解**——相似命名、可选参数、属性不一致
- **约束条件**——鉴权/权限、速率限制、Decimal vs float、sync vs async

每个任务描述必须包含：

- **目标**——脚本要做什么
- **示例输入**——具体的 symbol、日期、数值
- **验收标准**——正确输出长什么样
- **至少 1 个边界情况**——测试极端或特殊场景
- **可观测性**——需要打印/记录的信息

**防泄漏规则**：用业务语言描述任务（"展示我的持仓盈亏"），禁止用 SDK 语言（"调用 `stock_positions()` 读取 `symbol_name`"）。任务描述若直接点名陷阱，测试就失去意义。

### Step 2：派发 SubAgent

为每个用例填写模板后用 `Task` tool 派发：

```
./templates/task-prompt.md
```

填入 `{{SKILL_PATH}}`、`{{REFERENCE_SOURCES}}`、`{{TASK_DESCRIPTION}}`、`{{FORBIDDEN_PATHS}}`。

多个用例可并行派发（彼此独立）。

### Step 3：审计 Self-Reflection

| 章节 | 审计要点 |
|------|---------|
| **A. 风险/陷阱检查** | 是否识别出相关风险？是否引用了原文作为依据？有无 `unknown`？ |
| **B. 来源可追溯性** | 检查 `unknown` 数量——>0 说明 skill 有缺口。核实引文是否与源文件实际内容吻合。**核查引用路径**——若引用了不在允许列表中的文件，说明隔离被突破。 |
| **C. 反事实推演** | 3 条错误是否具体、有理、有据？若"想不出 3 条"——说明任务太简单 |
| **D. 缺口** | 值得回填到 skill 中的真实缺口 |
| **E. 上下文泄漏检查** | SubAgent 是否引用了 AGENTS.md 内容、自行加载了完整 skill、或读取了允许列表外的文件？如有，相关引用不计分。 |

### Step 4：判定

| 结果 | 含义 |
|------|------|
| ✅ PASS | 代码正确，风险已缓解，`unknown` 为零，无上下文泄漏 |
| ⚠️ PARTIAL | 代码正确但有 `unknown`（依赖了先验知识）或存在上下文泄漏 |
| ❌ FAIL | 代码有误、遗漏陷阱、或引用错误 |

### Step 5：回填与加固

- 存在 ❌ 或 ⚠️：将最小必要信息补入 skill，重跑同一测试。
- 全部 ✅：选择下列**一项**加固手段：

#### Hard Mode（高难度测试）

追加一个行为密集型任务，使用纯业务语言描述（如"把我的全部交易记录导出为表格"）。任务应组合多个 skill 特性（如 web endpoint + cron + workspace image），考验集成知识。

#### Mutation Test（突变测试）

选 1 个高价值陷阱，**物理改写原文件**：

```bash
# 1. 备份
SKILL_PATH="<category>-skills/<name>/SKILL.md"
cp "$SKILL_PATH" "${SKILL_PATH}.bak"

# 2. 删除目标章节（用 edit_file）

# 3. 派发 mutation test（SubAgent 读到的就是阉割版）

# 4. 立即恢复
mv "${SKILL_PATH}.bak" "$SKILL_PATH"
```

**预期**：SubAgent 应踩坑（代码有 bug）或标记 `unknown`（诚实承认不知）。若仍写出正确代码且零 `unknown`，说明该陷阱属于 LLM 先验知识覆盖范围——skill 中对应文档的价值是**提醒**而非**教学**，可考虑精简。

**注意**：mutation 期间避免其他 agent 读取同一 skill，以免互相干扰。完成后立即恢复原文件。

## 输出格式

```markdown
| Test | Task | Result | Risks Caught | Unknowns | Leaks | Gaps Found |
|------|------|--------|--------------|----------|-------|------------|
| 1 | ... | ✅ | 3/3 | 0 | none | none |
| 2 | ... | ⚠️ | 2/2 | 1 | AGENTS.md | batch size 未文档化 |
| 3 | ... | ❌ | 1/2 | 0 | none | 遗漏 X |
```

存在 ❌ 或 ⚠️ 时，先修复再重跑。
