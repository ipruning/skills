---
name: ast-grep
description: |
  Author, test, and maintain ast-grep rules and project lint gates: rule
  YAML capabilities, test-first authoring, suppression semantics, exit-code
  gating, pattern pitfalls, and version pinning. Use when writing or
  debugging ast-grep rules, wiring sgconfig/scan into pre-commit or CI,
  banning or enforcing a code pattern repo-wide (custom lint rules, even
  when the user never says "ast-grep"), or one-off structural search/replace
  that requires YAML rules, contextual or relational matching, composite
  rules, or AST debugging. Not for plain text search (use rg), one-off
  patterns that `ast-grep run -p/-r` expresses directly, or the programmatic
  APIs (napi/pyo3).
---

# ast-grep

一次性结构搜索用 `ast-grep run -p '<pattern>' -l <lang>`，结构替换加 `-r`。用户说「禁止这种写法」「把这类调用挡在合并之前」，指的就是下述 lint 引擎形态。版本敏感的断言均在 0.44.1 实测，与本机实测冲突时以实测为准。

## 项目形态

四件套：仓库根 `sgconfig.yml`（CLI 从 cwd 向上查找它定位项目）+ 规则目录（`ruleDirs`）+ 用例目录（`testConfigs: [{testDir: ...}]`）+ 可选 `utilDirs`。惯例是一条规则一个文件、文件名取 `id`——这是约定不是工具要求，工具只按 YAML 里的 `id` 字段配对；同一文件可用 `---` 放多条。每条规则写 `message`（一句现象与改法）；`severity` 不写缺省 hint，永不非零退出，门禁规则必须显式 error。规则级 `files:`/`ignores:` glob 是比行内豁免更粗的第一层豁免，**其基准是 sgconfig.yml 所在目录**，而 CLI 的 `--globs` 基准是 cwd，两者不同。给规则文件加 schema 头可让编辑器和 agent 得到字段校验：

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/ast-grep/ast-grep/main/schemas/typescript_rule.json
```

CI 和 Git hook 先跑 `ast-grep test --skip-snapshot-tests`，再跑全库 `scan`。只有 scan 没有 rule tests 时，规则字段或 AST 结构漂移可能把门禁静默变成永不命中；只有 tests 没有 scan 时，又看不到真实代码上的新增违规和过期豁免。

## 退出码即门禁

`ast-grep scan` 只在 error 级命中时非零退出；warning/info/hint 不影响退出码，在 pre-commit/CI 门禁下等于没开。要挡提交的规则一律 `severity: error`，或在命令行用 `--error=<rule-id>` 按条提升。高召回策略（规则宁可多报、误报靠豁免消化）的完整门禁是：

```sh
ast-grep scan --error=unused-suppression --error=no-suppress-all
```

两条内建诊断：`unused-suppression` 拦过期豁免，等价 eslint 的 report-unused-disable-directives，自带删除 fix。它默认只在不带 `--filter`/`--rule`/`--off` 的全量扫描下以 hint 开启，过滤扫描下默认 off，但显式 `--error=unused-suppression` 在两种扫描下都强制生效。`no-suppress-all` 拦不点名规则 id 的裸豁免，默认 off 必须显式提升。

## 豁免语义

`// ast-grep-ignore: <rule-id>` 放被豁免语句上一行或行尾，多 id 逗号分隔，任何注释风格都认。精确行为：`ast-grep-ignore` 后必须紧跟冒号再写 id，**漏掉冒号会静默变成豁免全部规则**（`no-suppress-all` 可拦）；解析器取冒号后每段第一个空格之前的部分做 id，所以 `// ast-grep-ignore: rule-id —— 原因` 的尾注原因是安全的（0.43.0 起）。文件级豁免是文件首行注释加随后一个空行；没有块级豁免。「豁免必须写原因」没有原生机制，靠约定与 review。

## 写规则：test-first

LLM 直接写规则失败率高：组合规则里单个原子的小错会滚雪球成完全错误的规则。可靠的顺序：

1. 先在 `rule-tests/<id>-test.yml` 写用例，格式 `{id, valid: [...], invalid: [...]}`，至少各一条。用例一律写块标量（`- |`）：单行代码含 `{k: v}` 会被 YAML 解析成 map 而报「expected a string」。
2. 再写规则。atomic（`pattern`/`kind`/`regex`）、relational（`inside`/`has`/`precedes`/`follows`，配 `stopBy: end` 才穿透多层）、composite（`all`/`any`/`not`/`matches`）。跨规则复用抽进 utils。
3. `ast-grep test --skip-snapshot-tests` 验证：Noisy 是 valid 被误报，Missing 是 invalid 漏报。快照测试只在需要锁定 fix 产物和报错 span 时才值得维护。
4. 全库 `ast-grep scan`，真实命中逐个判断修代码还是加豁免。

## pattern 的坑

- pattern 必须是该语言可独立解析出恰好一个 AST 根节点的完整代码。片段（对象的一个键值对、类外的方法）用 `{context: 完整代码, selector: 目标 kind}` 对象形态。
- `$VAR` 捕获单节点且同名多次出现要求文本一致；`$$$VAR` 捕获多节点；`$_VAR` 与 `$$$` 不捕获；变量名限大写、数字、下划线。0.44.0 起裸 `$$$VAR` 不能独立成 pattern。
- 纯 `regex` 不能单独成规则：推断不出候选节点 kind 会被整条拒绝（MissingPotentialKinds）。
- 表达不了的结构退到 `kind` + `has`/`inside` 组合，先看真实 AST 再写 kind。

## 调试与防幻觉

按顺序：`ast-grep run --debug-query=ast -p '<pattern>' -l <lang>` 看 pattern 解析出的结构；`ast-grep scan --inline-rules '<YAML>'` 免落盘试整条规则；`--inspect summary` 查规则为何没跑到目标文件。规则字段拿不准查 <https://astgrep.com/llms-full.txt>，不要凭训练数据猜。反序列化的严格性只覆盖 `rule:` 对象内部——编造的 rule 字段加载即报错；顶层字段（`severity`、`fix`、`message` 所在层）不校验，字段名拼错会静默丢失，schema 头就是给这层兜底的。playground（<https://ast-grep.github.io/playground.html>）是给人的调试台，agent 直接跑 CLI 更快。

## 版本

ast-grep 是 0.x，minor 版本含 breaking change，且内置 tree-sitter 语法升级可能改 node kind 名而使 `kind:` 规则静默失效。用项目现有的工具链锁精确版本（npm、mise、cargo、brew 皆有分发）；升级流程是改版本 → 跑 `ast-grep test` → 语法漂移会以 Missing/Noisy 暴露，用例即回归保险。
