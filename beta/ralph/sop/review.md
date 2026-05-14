# Review SOP

## 第一步：检查环境

```bash
rp-cli -e 'windows'
rp-cli -w <id> -e 'tree --type roots'
```

确认当前分支：`rp-cli -w <id> --raw-json -c git -j '{"op":"status","repo_root":"<绝对路径>"}'`

同步 main 分支（不切换当前分支）：

```bash
git fetch origin main --quiet
git branch -f main origin/main
```

## 第二步：确认 Review 范围

如果人类没有明确提出指令，则自行决定范围：

- 不在 main 分支 → 对比当前 branch 与 main
- git status 不干净 → 审查 unstaged 代码

## 第三步：执行 Review

```bash
TASK_ID="$(date +%Y%m%d-%H%M%S)"
WORK_DIR="/tmp/review-$TASK_ID"
mkdir -p "$WORK_DIR"
```

### 路线一：Repo Prompt 全流程

```bash
rp-cli -w <id> -e 'builder "Your Task Description" --response-type review'
```

可选追问：`rp-cli -w <id> -t '<tab_id>' -e 'chat "Your Question" --mode chat'`

### 路线二：Builder 构建提示词 → Oracle 审查

#### Builder 构建上下文

```bash
rp-cli -w <id> -e 'builder "Your Task Description" --response-type clarify'
```

#### 导出 prompt

```bash
rp-cli -w <id> -t $TAB -q -e "prompt export $WORK_DIR/prompt.md --copy-preset codeReview"
```

#### Token 检查

```bash
uv run --script ../templates/ttok.py "$WORK_DIR/prompt.md"
```

读取 token 数。超过 65000 应缩小上下文重新跑 builder。

#### 提交 Oracle

```bash
bash ../templates/submit-oracle.sh "$WORK_DIR" "$WORK_DIR/prompt.md" "review-$TASK_ID"
```

#### 等待并收集

```bash
source "$WORK_DIR/pueue-env.txt"
pueue wait "$PUEUE_ID"
pueue log "$PUEUE_ID" > "$WORK_DIR/pueue-task.log" || true
```

⚠️ 不要 kill 任务。Oracle browser 引擎思考 30 分钟是正常的。Agent 超时后重跑 `pueue wait` 即可。

### 路线三：用户已在 Repo Prompt 手动选上下文

用户手动选好文件后，用 `rp-cli -w <id> -q -e "prompt export $OUT --copy-preset codeReview"` 导出。

## 第四步：解读结果

读 `$WORK_DIR/review-result.md`。如果内容不是有效审查（如 Oracle 未收到文件），改为自己审查代码。

如果有效，加载 `reflect` skill，对每条建议逐一验证。

如果审查对象是 PR，将验证后的审查结果通过 `gh pr comment "$PR_NUMBER" --repo "$OWNER/$REPO" --body "<验证后的审查结果>"` 发回 PR comment。
