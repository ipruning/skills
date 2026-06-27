## 协作方式

直接说明事实、判断和证据。

默认直接给结论和证据。不要预设用户看不懂；只有当用户明确要求教学、推导、调试、对比，或任务本身需要建立中间概念时，才展开必要解释。

不要用空泛免责声明，或「这个问题很复杂，很难一概而论」「语言难以完全表达」替代判断。如果暂时不能判断，先收窄问题，并说明缺少哪些事实。

## 表达风格

用户用中文则用中文回复。中文段落使用直角引号；纯英文段落按英文习惯使用半角符号；中文与英文单词、缩写、数字相邻时，插入 1 个半角空格，例如「大模型 LLMs」「版本 2.1」「在 Tokyo 开会」。

## 测试

写代码和测试时，优先覆盖真实业务场景。遇到 Mock，先判断它是在替代真实业务用例，还是在隔离不可控外部边界；前者必须清理并换成真实场景测试，后者要保留并注明边界。如果不确定真实用例，询问用户。

## Token 处理

用户授权你创建、复制、粘贴各类 Token。不要为了「避免回显」自作聪明，发明复杂 stdin/PTY 流程。

## 阻塞通知

仅当任务卡在等待用户的某个具体动作、且静默等待会让任务停住时，按以下流程通知：

语音提醒直接调用：

```bash
sag --voice Jessica --model-id eleven_v3 --lang en --speed 1.12 \
  --stability 0.5 --style 0.30 --similarity 0.84 --timeout 30s \
  "<blocker and action needed>"
```

1. 运行上面的 `sag` 命令发语音提醒。
2. `sleep 180`，重新检查阻塞是否解除。
3. 仍阻塞：加载 `brrr-now` 技能发 1 条 Push。若延误会造成不可逆后果或错过当天窗口，用 `critical`；其余用 `time-sensitive`。
4. Push 发出后不再重复通知。继续推进未被阻塞的部分；若全部被阻塞，收尾汇报当前状态。

## GitHub 多账号

多账号场景先用 `gh auth status --json hosts` 取已保存 login。单条 `gh` 命令按 login 注入 token，不切换 active account：

```bash
GH_TOKEN="$(gh auth token --user <login>)" gh <command>
```

## 搜索代码

搜索文件和代码时，优先使用 `fd`、`rg`、`ast-grep`，不要默认退回 `find` / `grep`。

- 找文件、目录、扩展名：用 `fd`。
- 找文本、字符串、配置 key、错误信息：用 `rg`。
- 找代码语法形状、调用模式、结构化替换点：用 `ast-grep`。

只有工具不可用、需要 POSIX 兼容示例，或用户明确要求时，才使用 `find` / `grep`。

## macOS shell 命令

编写或运行 shell 命令时，除非命令显式调用 `bash`，否则假定它在 `zsh` 中执行。

### 不与 zsh 参数名冲突

写 zsh 命令时，不要把下列名称用作临时变量、循环变量或数组名；JSON 字段名、文件内容和 API 字段名不受影响：

- `argv`
- `path`
- `commands`
- `status`
- `pipestatus`
- `UID`
- `EUID`
- `LINENO`
- `RANDOM`
- `SECONDS`
- `ERRNO`
- `signals`
- `options`
- `parameters`
- `functions`
- `aliases`
- `builtins`

常用替代名：`file_path`、`input_path`、`exit_code`、`http_status`、`cmds`、`command_list`、`user_id`。

### 命令执行策略

启动命令前，先判断它会改变什么状态：只读、本机文件、本机服务、数据库、云端资源、第三方系统。影响范围越远离当前工作区，越要先确认目标和恢复路径；远端写操作默认按不可逆处理，优先使用 dry run、plan、diff、preview 或小范围执行。

长命令或高输出命令要预先设计 stdout / stderr：

- 需要实时看进度：用 `tee`，并注意保留原命令失败状态。
- 输出可能很大：重定向到日志文件，再用 `tail`、`rg`、`sed` 查看关键片段。
- 只关心摘要：让命令自己输出简洁格式，或后接过滤器。

如果命令输出会超过可读范围，不要直接裸跑；先写入日志文件，再按需摘取关键行。

需要临时处理数据时，区分临时脚本和现有 CLI。临时脚本的目标是方便后续判断：输出简洁、结构化、可搜索，错误信息带上下文，退出码准确。组合现有 CLI 时，先看它是否提供 `--json`、`--porcelain`、`--quiet`、`--dry-run`、`--plan`、`--diff`、`--output` 等稳定接口，不要用脆弱文本解析替代机器输出。

不要把 `timeout` 当作主要安全机制。先判断命令中断后能否安全恢复、能否重复执行、运行期间能否通过日志或状态输出观察健康；`timeout` 只是最后兜底。需要运行上限时，先用 `command -v timeout` 检查；否则检查 `gtimeout`；二者都不可用时，再用后台进程、`sleep` 和 `kill` 做一次性兜底。

## Codex 浏览器

处理网页时，当前对话先用 Codex 内置 Browser；它负责交互、截图、登录态检查、用户同屏确认和最终视觉验收。只有内置 Browser 不存在、缺少必需工具，或重试后仍无法连接目标，当前对话才用 `agent-browser`。

不要让多个 sub-agent 控制 Codex 内置 Browser；并发会切换 tab、滚动视口、覆盖截图现场，制造审计假阳性。

并行网页审计、批量截图、批量页面检查和 sub-agent 界面校对使用 `agent-browser --session <unique-name>`。sub-agent 先读 `agent-browser skills get core`，结束后关闭 session。当前对话汇总并用 Codex 内置 Browser 抽样复核。

委派网页审计的 Prompt 必须写明：使用 `agent-browser --session <unique-name>`；输出 URL、截图路径、关键 DOM 事实、console 错误、broken image、横向溢出和手感问题；不控制用户正在看的页面。当前对话做最终视觉复核。

## Codex 委派

委派前先判断用户要的是「用户可见 Thread」还是「内部 sub-agent」。

用户可见 Thread 是独立对话，适合让用户在侧栏看到、继续跟进、或保留为并行研究现场。当用户说「新 Thread」「创建 Thread」「发给 Thread」「开几个 Thread」「让 Thread 自己工作」时，创建用户可见 Thread。不要把这类请求替换成内部 sub-agent。

用户可见 Thread 不会自动继承当前上下文，也不会在完成后主动把结果送回当前对话。创建它时，把目标、边界、入口文件、必要事实和输出格式写进初始 Prompt。若当前对话需要汇总结果，记录用户可见 Thread 的用途和 id，等待后再读取这些 Thread。

内部 sub-agent 是当前对话的不可见执行机制，适合并行检查、局部探索、验证或实现。只有当用户明确要求「sub-agent」「内部并行」，或明确授权你自行内部委派时，才使用内部 sub-agent。不要用内部 sub-agent 代替用户要求的用户可见 Thread。

委派类型按目的决定上下文：

- 探索：使用干净上下文。只给目标、边界、入口和输出格式，让 sub-agent 独立观察。
- 复核：使用干净上下文。给待证伪的结论、证据和约束，不给你的中间推理。
- 延续：继承当前工作现场，或复用已有用户可见 Thread 或内部 sub-agent。

默认不要把自己的判断塞给执行探索任务的 sub-agent。用户可见 Thread 和内部 sub-agent 都无法区分你验证过的事实和顺手写下的猜测。探索和复核任务只提供目标、边界和证据。
