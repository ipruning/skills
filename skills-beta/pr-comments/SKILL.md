---
name: pr-comments
description: 'Fetch and triage PR review feedback. Triggers: fix PR comments, address review, read PR comments, check PR review, triage review.'
metadata:
  version: '2'
---

# Resolve PR Comments

Fetch all review feedback from a GitHub PR and generate structured resolution proposals.

## Prerequisites

Requires `gh` CLI installed and authenticated.

## Usage

Run from the skill directory:

```bash
bash scripts/resolve-pr-comments.sh <pr-number-or-url>
```

## Arguments

- `<pr-number-or-url>`: PR number or full URL

## Examples

```bash
bash scripts/resolve-pr-comments.sh 123
bash scripts/resolve-pr-comments.sh https://github.com/owner/repo/pull/123
```

## Output

The script fetches PR details and all review feedback, then outputs a guidance prompt that directs the agent to:

1. Build an overall understanding of the PR
2. Analyze all feedback and categorize it (bug, design, performance, security, tests, etc.)
3. Propose a resolution for each piece of feedback
4. Create an implementation plan
5. Draft reply templates for reviewers

The final output includes:

- PR summary
- Open questions
- Feedback analysis
- Resolution proposals (by comment)
- Implementation plan
- Suggested reviewer replies

## gh API Pitfalls

Watch out for these gotchas when manually calling gh CLI to handle PR reviews:

### Two Separate Comment APIs

GitHub has two independent comment systems. You **must fetch both** to get complete review data:

| API | Returns | Purpose |
|-----|---------|---------|
| `gh pr view --comments --json comments` | Issue-level comments (discussion below the PR body) | General comments |
| `gh api repos/{owner}/{repo}/pulls/{number}/comments` | Inline review comments (code-line-level reviews) | Code review |

> ⚠️ Using only one will miss the other half of comments. This skill's GraphQL script fetches both.

### Replying to a Review Comment

```bash
# ✅ Correct: create a new comment with in_reply_to
gh api repos/{owner}/{repo}/pulls/{number}/comments \
  -f body="..." -F in_reply_to={comment_id}

# ❌ Wrong: /pulls/comments/{id}/replies (404, does not exist)
gh api repos/{owner}/{repo}/pulls/comments/{comment_id}/replies \
  -f body="..."

# ❌ Wrong: PATCH the comment directly (this edits, not replies)
gh api repos/{owner}/{repo}/pulls/comments/{comment_id} \
  -X PATCH -f body="..."
```

### Resolving a Review Thread

REST API **does not support** resolving review threads. You must use GraphQL.

> ⚠️ **node_id prefix matters**: comment `node_id` starts with `PRRC_` (PullRequestReviewComment), thread `node_id` starts with `PRRT_` (PullRequestReviewThread). The `resolveReviewThread` mutation only accepts `PRRT_`-prefixed IDs — using `PRRC_` returns NOT_FOUND.

```bash
# First, get the thread node_id
gh api graphql -f query='
  query($owner: String!, $repo: String!, $number: Int!) {
    repository(owner: $owner, name: $repo) {
      pullRequest(number: $number) {
        reviewThreads(first: 100) {
          nodes { id isResolved comments(first: 1) { nodes { body } } }
        }
      }
    }
  }' -F owner=OWNER -F repo=REPO -F number=NUMBER

# Then resolve
gh api graphql -f query='
  mutation($threadId: ID!) {
    resolveReviewThread(input: {threadId: $threadId}) {
      thread { isResolved }
    }
  }' -F threadId=THREAD_NODE_ID
```

### General Comments Cannot Be Resolved

Issue-level comments (`IC_` prefix) have no resolve mechanism. The closest alternative is `minimizeComment`:

```bash
# Collapse an issue-level comment (e.g., bot noise)
gh api graphql -f query='
  mutation($id: ID!) {
    minimizeComment(input: {subjectId: $id, classifier: RESOLVED}) {
      minimizedComment { isMinimized }
    }
  }' -F id=IC_NODE_ID

# Available classifiers: SPAM, ABUSE, OFF_TOPIC, OUTDATED, DUPLICATE, RESOLVED
```
