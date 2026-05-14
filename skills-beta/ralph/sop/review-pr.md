# PR Review SOP（自动化）

通过克隆到 `/tmp`、使用 rp-cli 在独立窗口中操作、并提交给 Oracle 来审查 GitHub PR。

与 [review.md](review.md)（手动、单仓库、基于分支）相比，本 SOP 处理**任意仓库和 PR**，具备完整的工作区隔离。

## 命名规范

```
# 工作目录
/tmp/ralph/{owner}/{repo}/{pr}/
  ├── repo/            # 浅克隆
  ├── prompt.md        # 导出的审查提示词
  ├── review-result.md # Oracle 输出
  └── pueue-env.txt    # 任务追踪

# rp-cli 工作区名称
ralph-{owner}-{repo}-{pr}
```

## 第一步：解析 PR 元数据

使用 `gh pr view` 获取标题、基础分支、变更文件数。设置变量：

- `OWNER`、`REPO`、`PR_NUMBER`
- `WORK_DIR="/tmp/ralph/$OWNER/$REPO/$PR_NUMBER"`
- `WS_NAME="ralph-$REPO-$PR_NUMBER"`
- `BASE_REF` 取自 PR 的 `baseRefName`

## 第二步：克隆 PR 到 /tmp

```bash
mkdir -p "$WORK_DIR"
git clone --depth=50 "$REPO_URL" "$WORK_DIR/repo"
cd "$WORK_DIR/repo"
git fetch origin "pull/$PR_NUMBER/head:pr-$PR_NUMBER" --depth=50
git checkout "pr-$PR_NUMBER"
git fetch origin "$BASE_REF" --depth=50
```

验证 diff：`git diff "origin/$BASE_REF...HEAD" --stat`

## 第三步：在新窗口中创建 rp-cli 工作区

使用 `rp-cli -e "workspace create ... --new-window"`。

从输出中提取 Window ID，并用 `rp-cli -w $WINDOW_ID -e 'tree --type roots'` 验证。

## 第四步：运行 builder 并导出提示词

```bash
rp-cli -w $WINDOW_ID -e "builder \"Review PR #$PR_NUMBER: $PR_TITLE. ...\" --response-type clarify"
```

从 builder 输出中提取 Tab ID，然后导出：

```bash
rp-cli -w $WINDOW_ID -t $TAB_ID -q -e "prompt export $OUT --copy-preset codeReview"
```

## 第五步：Token 检查

```bash
uv run --script ../templates/ttok.py "$OUT"
```

读取 token 数。超过 65000 应缩小上下文重新跑 builder。不要盲目继续。

## 第六步：通过 pueue 提交给 Oracle

```bash
bash ../templates/submit-oracle.sh "$WORK_DIR" "$OUT" "$WS_NAME"
```

等待并收集：

```bash
source "$WORK_DIR/pueue-env.txt"
pueue wait "$PUEUE_ID"
pueue log "$PUEUE_ID" > "$WORK_DIR/pueue-task.log" || true
```

⚠️ 不要 kill 任务。Oracle browser 引擎思考 30 分钟是正常的。Agent 超时后重跑 `pueue wait` 即可。

## 第七步：解读结果

读 `$WORK_DIR/review-result.md`。如果内容不是有效审查（如 Oracle 未收到文件），改为自己审查代码。

如果有效，加载 `reflect` skill，对每条建议逐一对照 `$WORK_DIR/repo/` 中的实际代码验证。

验证完成后，通过 `gh pr comment "$PR_NUMBER" --repo "$OWNER/$REPO" --body "<验证后的审查结果>"` 将结果发回 PR comment。

## 第八步：清理

```bash
rp-cli -w "$WINDOW_ID" -e "workspace switch Default"
rp-cli -w "$WINDOW_ID" -e "workspace delete --workspace \"$WS_NAME\""
```

```bash
source "$WORK_DIR/pueue-env.txt" 2>/dev/null || true
pueue group remove "$GROUP" 2>/dev/null || true
rm -rf "$WORK_DIR"
```

## 并发

可同时审查多个 PR。每个 PR 通过 `--new-window` 获得独立窗口，所有操作使用 `-w <window_id>`。Oracle 任务运行在各自独立的 pueue group 中。

**不要**在存在多个窗口时不带 `-w` 操作窗口。
