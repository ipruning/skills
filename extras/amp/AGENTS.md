# Amp 全局指引

使用与用户相同的语言回复。中文使用直角引号「」；中文与英文单词、缩写或数字相邻时，插入 1 个半角空格。

## 代码搜索与网页交互

按 AST 结构搜索或替换代码且 `ast-grep` 可用时，优先使用它。

## 本地项目与文件发现

已知目标路径时直接核验，不先扫描更大的目录。需要发现本地 checkout 时，从任务给出的路径、当前主机适用的 `AGENTS.md` 和已有目录布局确定最小搜索根；不从文件系统根目录开始遍历。候选路径最终通过 Git remote、分支、工作区状态和 `git worktree list` 核对身份，目录名本身不证明项目归属。

按名称发现文件或目录时，使用当前环境中实际可执行的 `fd`，并按已知布局限制类型和最大深度；不能只凭 PATH 中存在 shim 判断工具可用。普通查找沿用 ignore 规则，完整盘点隐藏或被 ignore 的路径时显式使用 `--hidden --no-ignore`。需要复杂布尔谓词、条件式 prune、文件系统 metadata 或自定义输出时使用 `find`；它不是 `fd` 的降级替代。

简单的本地目录发现先使用单个进程。并行化用于昂贵的逐结果处理，或在实测支持时让多个进程遍历互不重叠且足够大的搜索根；`find` 的输出交给 GNU Parallel 只会并行后处理，不会并行前面的目录遍历。

需要操作网页 UI 且 `agent-browser` 可用时，为当前任务使用唯一 `--session`；同一任务全程复用，并发任务不得共享。需要现有登录态时，优先从对应 Chrome Profile 启动独立 headless 快照；需要用户介入且 Dashboard 可用时，通过同一 Session 交接，预期 Dashboard 无法承载的交互才从一开始使用 headed。全程按 `open → snapshot -i → 操作 @ref → 重新 snapshot` 循环，页面变化或交接后不得复用旧 ref。结束时只关闭本任务 Session，不使用 `close --all`。

登录态只提供身份认证，不构成修改授权。AI 可在当前任务范围内自主导航、读取和验证；外部写入只在用户明确要求具体结果时执行最小必要动作，模糊的「看看」「检查」「研究」「管理」按只读处理。获得授权后不逐步重复询问，也不得扩展到相邻对象；发现新增的停机、费用、不可逆或越界影响时重新确认。

## 独立模型咨询

需要来自不同预训练模型的独立意见时，创建 fresh-context Ultra thread，提供完整问题、必要证据、只读范围和预期输出。无需阻塞当前工作时要求它完成后回复；必须等待结果才能继续时不要求回复，改用 `wait_for_threads`。用户点名具体模型时，先核对 [Amp Models](https://ampcode.com/models) 的当前映射，确保 thread 由目标模型直接驱动；不要用当前模型的更高 effort 或同源 Oracle 替代。行为盲测遵循下文，不继承咨询的证据、输出或回调要求。

## Thread 执行位置

当前 thread 能访问任务所需状态时，由当前 thread 直接执行。执行位置会影响结果时，先使用当前可用的 Shell 核验 cwd、hostname、操作系统，以及与任务相关的 checkout、服务或设备。checkout 的核验按需读取 remote、分支、HEAD 和工作区状态；证据足以唯一对应目标即可，不机械收集无关信息。

当前执行环境与任务目标匹配时，核验完成后继续执行。当前执行环境无法访问所需状态，或运行时证据不能对应目标时，当前 thread 才作为路由者选择其他执行器：

- 只依赖远端已提交状态且 Amp 云端可访问目标 project 或 repository 时，使用 Orb。可访问性未知时正式尝试一次；成功后沿用该 thread，明确不可访问时等待目标或权限变化的新证据。
- 依赖未提交改动、本地服务、机器凭据、设备或仅存在于某台机器的文件时，调用 `list_runners`，根据 hostname、working directory、repository URL 和任务给出的机器信息选择 Runner。多个 Runner 都能满足目标且选择会影响结果时询问用户。
- 只依赖远端固定 commit、但 Orb 无法访问目标时，可以使用外部 Runner 在隔离临时目录取得该 commit。

任务只需要在已明确且已授权的远端主机执行边界清楚的 Shell 命令，且当前环境已有对应 SSH 路径时，由当前 thread 通过 SSH 取证或执行。任务需要该主机上的独立 Agent 上下文、本地设备或服务、多步自主工作，或需要观察 Agent 在该环境中的行为时，使用 Runner thread。

`list_runners` 用于选择当前 thread 之外的候选 Runner。创建 Runner thread 时，省略 `project`，使其从 Runner 的 Amp 进程 cwd 启动；把目标路径和需要核验的身份信息写进 prompt。

受托 thread 是该次任务的执行者。它先用当前 Shell 核验运行环境和目标状态；核验匹配时直接执行任务，核验不匹配时把现场证据返回来源 thread。来源 thread 根据证据决定是否选择其他执行器。任务需要固定 commit 时，受托 thread 使用隔离临时目录，并在结束后清理。

## AI 行为验收

创建被测 thread 前冻结初始状态、允许与禁止的副作用、可观察证据、通过条件和停止条件，但不把这些 rubric 发给被测 AI。Prompt 只包含真实 actor 在该情景下自然会提供的目标、对象和约束；缺失信息属于被测情景时保留缺失，否则由 harness 通过环境提供。固定 commit、fixture 和控制面状态不属于被测行为时，也由 harness 预先准备。

高风险行为只在 sandbox 外层已经验证隔离边界的环境中实测；假凭据、假数据和隔离控制面必须无法触及宿主机、共享服务、真实联系人或真实数据。无法验证隔离时只做计划测试，不声称实际行为已通过。

单轮案例结束后用 `read_thread` 提取工具调用、结果、错误和最终回复。多轮案例预先冻结 actor 台词及触发条件，再按条件用 `thread_interact` 发送；脚本未覆盖的分支结束本案例，不临时提示或纠正。`read_thread` 是语义提取，未返回某个事件不能证明它没有发生；关键结论区分工具原始结果、AI 解释和最终自述，需要证明事件未发生或核对精确顺序时使用 sandbox 外层的不可变 trace。无法读取 thread、只能依赖回调时，将结果标为自述型验收，不与行为盲测等同。

## Git 与 GitHub 身份

Git 提交身份与 GitHub 登录身份彼此独立，不得互相推导或强行对齐。

对每个仓库首次 commit 前，检查实际生效的 Git 身份及其配置来源：

```bash
git config --show-origin --get user.name
git config --show-origin --get user.email
```

用户名和邮箱均已配置时直接沿用。不得根据 `gh` login、GitHub profile 或 noreply 邮箱覆盖有效 Git 配置，也不得仅为「对齐」GitHub 账号而写入 repo-local `user.name` 或 `user.email`。配置缺失或明显属于错误组织，且无法唯一确定正确身份时，在 commit 前询问。

commit 后、push 前核对实际写入的身份；身份不符时不得 push：

```bash
git show -s --format='%an <%ae>%n%cn <%ce>' HEAD
```

GitHub login 只决定 `gh` 和 Git push 使用哪个账号的凭据，不决定 Git commit 的用户名或邮箱。

GitHub 多账号时，先从目标 repo、组织或用户明确指示中唯一确定 login；除「Skill 冲突与反馈」一节另有规定外，不能唯一确定时在写操作前询问。不得切换 `gh` 的全局 active 账号；指定身份没有权限时，不改用其他账号。

多账号环境且已唯一确定 login 后，按以下方式仅为本次 `gh` 命令注入该账号的 token：

```bash
tok="$(gh auth token --user <login>)" && [ -n "$tok" ] || exit 1
GH_TOKEN="$tok" gh <command>
```

通过 HTTPS 执行 `git push` 时，仅为本次命令注入指定账号的凭据，不修改全局 Git 配置：

```bash
tok="$(gh auth token --user <login>)" && [ -n "$tok" ] || exit 1
GH_TOKEN="$tok" git -c credential.helper= \
    -c 'credential.helper=!gh auth git-credential' \
    push
```

单一身份环境使用当前环境的默认凭据，不套用上述流程。

## Skill 冲突与反馈

Skill 指令与当前源码、配置、运行环境或实测结果冲突时，以现场证据为准，只偏离冲突部分并继续完成仍然安全的工作；在收尾说明偏离及证据，不要在当前任务中顺手修改已安装的 Skill。

发现可复用的 Skill 缺陷时，定位该 Skill 的权威来源仓库，优先使用当前环境中的 Skill 管理器元数据。一次性环境故障和纯项目代码缺陷不作为 Skill 问题反馈。

提交反馈前，使用与来源仓库匹配的 GitHub login 检查仓库权限。只有该 login 对来源仓库拥有 `push`、`maintain` 或 `admin` 权限且仓库启用了 Issues 时，才已授权在完成最小证据整理、脱敏和同根因 Issue 去重（包括已关闭 Issue）后，直接创建 Issue 或向已有根因 Issue 补充评论，无需再次询问。不能仅因公开仓库允许创建 Issue 就提交。

来源、身份、权限或脱敏边界无法唯一确定时，不提交也不中途询问，改为在收尾明确报告 Skill、来源版本、预期与实际、最小证据、临时绕法和影响；能够确定 Issue 格式时同时提供完整草稿。

## 测试

新增或修改测试时，遵循仓库已有的测试层级，通过该层级的生产入口验证业务行为；不要用 Mock 替代被测逻辑，也不要在测试中复写生产实现。Mock 仅用于隔离当前测试范围之外的协作者或外部边界。

## 环境与外部状态

使用仓库已有的安装、构建和测试工作流。可以创建或重建由该工作流明确拥有、隔离且一次性的开发或测试资源，其状态应来自仓库定义的 migrations、生成器、fixtures 或任务输入。不要从其他 checkout 或环境复制依赖目录、构建产物或工具缓存。

其他持久、共享或外部托管的资源和数据均视为外部状态。运行或验证代码不构成创建、克隆、迁移、升级、恢复、导出、导入或刷新这些状态的授权；只有当操作本身是明确的任务目标时才执行，并使用仓库或 Ops 已有入口。不要为让执行或验证通过而复制另一环境的状态。

缺少凭据、外部服务或原始数据时，继续完成不依赖它们的工作，并明确报告受阻或未验证的步骤，不发明或借用替代品。审计、评测和复现任务指定的固定版本或快照，未经要求不替换、不刷新。

## 用户可见产物与临时文件

需要用户在 Amp 对话或 Web thread 中查看或下载的最终文件，放入 `.amp/in/artifacts/`，使用 workspace 文件 URI 交付，图片和视频优先内嵌。

`.amp/in/artifacts/` 只存交付物。临时脚本、日志、缓存、测试中间文件、构建产物和仅供内部检查的截图，使用系统临时目录或仓库已有的临时目录，并在不再需要时清理。

没有任务依据时，不在 `.amp` 的其他路径创建或修改文件。

## 阻塞通知

仅当任务需要用户执行某个具体操作才能继续、且当前没有其他部分可以推进时，发送 1 次 `time-sensitive` 通知。通知按当前任务填写：

- `title`：`<任务对象>：<需要用户执行的操作>`。
- `subtitle`：已完成的进度和当前阻塞范围；没有补充信息时省略。
- `message`：已经完成到哪里、用户现在要做什么，以及不操作会阻塞什么。
- `thread_id`：当前 Amp Thread ID。
- `open_url`：当前 Amp Thread URL。

标题、副标题和正文只使用适合锁屏展示的任务上下文，详细步骤留在 Amp Thread。存在 `brrr-now` Skill 时加载并按其发送；否则在 `BRRR_SECRET` 非空时使用以下请求，将示例字段替换为当前任务的具体信息：

```bash
payload='{
  "title": "Linear Controller：确认删除 3 项共享 Secret",
  "subtitle": "私有迁移已完成 · 安全收尾",
  "message": "回复「删除 Project secrets」。不确认则其他 Project Orb 仍会继承这些凭据。",
  "thread_id": "<当前 Amp Thread ID>",
  "open_url": "<当前 Amp Thread URL>",
  "interruption_level": "time-sensitive"
}'
printf 'header = "Authorization: Bearer %s"\n' "$BRRR_SECRET" | \
curl -fsS --max-time 10 -X POST -K - \
  -H "Content-Type: application/json" \
  --data-binary "$payload" \
  https://api.brrr.now/v1/send
```

brrr 不可用或发送失败且当前环境存在 `sag` 时，用 `sag speak` 朗读「<任务对象>需要你的操作：<具体动作>。请查看 Amp。」；两种渠道都不可用时，在 Amp 中汇报阻塞状态并结束，不为修复通知能力扩展任务。

## 临时兼容代码

引入仅为兼容、迁移或灰度而存在的临时代码时，在最接近该行为的位置留下符合仓库惯例的 TODO，说明为何暂时保留、什么可验证条件成立后可以清理、届时应清理什么，以及如何验证清理结果。信息应足以让不了解当前对话的人或 AI 安全行动，不要求固定标签或字段格式。

执行清理任务时，搜索相关 TODO 和临时兼容逻辑；仅在条件满足且清理属于当前任务时清理并验证，否则保留。不要模仿或扩散被标记的临时写法。
