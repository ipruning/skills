#!/usr/bin/env bash
set -euo pipefail

# Check if PR argument is provided
if [ $# -eq 0 ]; then
	echo "Usage: resolve-pr-comments <pr-number-or-url>"
	echo "Examples:"
	echo "  resolve-pr-comments 123"
	echo "  resolve-pr-comments https://github.com/owner/repo/pull/123"
	exit 2
fi

PR_ARG="$1"

# Extract PR number if URL is provided
if [[ "$PR_ARG" == *"github.com"* ]]; then
	PR_NUMBER=$(echo "$PR_ARG" | grep -oE '[0-9]+$')
else
	PR_NUMBER="$PR_ARG"
fi

# Get repository info
REPO_INFO=$(gh repo view --json owner,name 2>/dev/null)
# shellcheck disable=SC2181
if [ $? -ne 0 ]; then
	echo "Error: Not in a GitHub repository or gh CLI not authenticated"
	exit 1
fi

OWNER=$(echo "$REPO_INFO" | jq -r '.owner.login')
REPO_NAME=$(echo "$REPO_INFO" | jq -r '.name')

# GraphQL query for PR and comments
read -r -d '' QUERY <<'EOF'
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      title
      number
      author { login }
      body
      url
      reviews(first: 50) {
        nodes {
          author { login }
          body
          state
          comments(first: 50) {
            nodes {
              author { login }
              body
              path
              line
              diffHunk
            }
          }
        }
      }
      comments(first: 50) {
        nodes {
          author { login }
          body
        }
      }
    }
  }
}
EOF

# Execute query
if ! RESPONSE=$(gh api graphql -f query="$QUERY" -F owner="$OWNER" -F repo="$REPO_NAME" -F number="$PR_NUMBER" 2>/dev/null); then
	echo "Error: Could not fetch PR #$PR_NUMBER"
	exit 1
fi

# Extract data
PR_DATA=$(echo "$RESPONSE" | jq -r '.data.repository.pullRequest')
if [ "$PR_DATA" == "null" ]; then
	echo "Error: PR #$PR_NUMBER not found"
	exit 1
fi

TITLE=$(echo "$PR_DATA" | jq -r '.title')
AUTHOR=$(echo "$PR_DATA" | jq -r '.author.login')
BODY=$(echo "$PR_DATA" | jq -r '.body // ""')
URL=$(echo "$PR_DATA" | jq -r '.url')

# Output formatted content
cat <<EOF
Analyze all review feedback on this pull request and turn it into concrete resolutions and an implementation plan.

# $TITLE (#$PR_NUMBER)

**Author:** $AUTHOR
**URL:** $URL

**Description:**

$BODY

## Feedback to Address

EOF

# Add general comments
echo "$PR_DATA" | jq -r '.comments.nodes[] | "**@\(.author.login):** \(.body)

"'

# Add review comments
echo "$PR_DATA" | jq -r '.reviews.nodes[] | select(.body != null and .body != "") | "**@\(.author.login) (\(.state)):** \(.body)

"'

# Add inline code comments
echo "$PR_DATA" | jq -r '.reviews.nodes[].comments.nodes[] | "**@\(.author.login)** on `\(.path)`:\(.line // ""):
\(.body)

```
\(.diffHunk)
```

"'

cat <<'EOF'
## 你的任务

你是一名资深软件工程师，正在帮助处理这次 Pull Request 的评审意见。

你的目标是把上面所有评论都转化成具体可执行的解决方案和一份有顺序的实施计划。
你自己不会直接修改代码，而是要精确描述应该改什么、怎么改、以及如何验证这些改动。

在给出命令或工具相关建议时，请遵守仓库根目录 AGENTS.md 中的规则。
例如优先使用 uv 和 mise 相关命令，而不是直接运行 python 或 pip, 并且要对测试和可观测性保持明确。

请按下面的顺序工作：

1. 搭建对 PR 的整体认知。
   - 总结这次改动的意图以及主要风险点。
   - 如果有缺失的上下文或不清晰的需求，不要猜，在后面的「Open questions」章节中列出。
2. 分析所有反馈。
   - 对每一条总体评论、评审正文以及行内代码评论，归类到一个类别中，例如：bug、correctness、design、performance、security、tests、docs、style、nit 等。
   - 标记哪些问题是合并前必须解决的阻塞项，哪些只是可选建议。
3. 为每条反馈提出解决方案。
   - 针对每条评论或一组相关评论，给出明确的解决方式：代码改动、文档更新，或者清晰说明为什么保留当前行为。
   - 如果需要代码改动，以「具体编辑行为」的粒度来描述：涉及哪些文件和符号，需要增加、删除或重构什么内容。
   - 如果一处改动可以同时解决多条评论，要明确指出这一点。
4. 制定实施计划。
   - 以编号列表的形式给出你建议的实施顺序。
   - 对每一步，写清楚：
     - 关联的评论或评审者
     - 可能需要修改的文件或模块
     - 变更类型 (重构、缺陷修复、测试、文档、风格等)
     - 如何验证 (要运行的现有测试、新增的测试、以及必要的手工检查)
5. 起草给评审者的人类回复。
   - 对重要的评论或可能有分歧的评论，提供简短的回复片段，方便 PR 作者直接粘贴到评论线程中。
   - 回复要礼貌、简洁，并且聚焦于权衡与理由。

最终输出应是一份完整的 Markdown 文档，至少包含以下章节：

- PR summary: PR 总结
- Open questions: 开放问题
- Feedback analysis: 反馈分析
- Resolution proposals (by comment): 按评论归类的解决方案
- Implementation plan: 实施计划
- Suggested reviewer replies: 建议的评审回复模版
EOF

exit 0
