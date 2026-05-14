---
name: oracle
description: "Ask an external long-reasoning model for a second opinion on hard code, architecture, research, and debugging questions."
---

Oracle is not the source of truth. Treat its answer as leads and arguments. Verify important claims yourself against local code, tests, docs, command output, or the web.

Before calling Oracle, inspect the local scope and decide what context actually bears on the question. Send only relevant files. Do not include lockfiles, generated artifacts, vendored dependencies, or whole long documents. For long documents, summarize the relevant passages into $TMPDIR/context.md and send that summary.

Use this exact command shape:

npx -y @steipete/oracle --engine browser --model gpt-5.4-pro --browser-inline-files

Always run a dry run first:

--dry-run summary --files-report

Read the output. Proceed only if it says Inline file content. If it says Bundled upload, the context is too large; reduce the file set or summarize more context.

Write the Oracle prompt as a self-contained brief:

- what the project or problem is;
- what question you want answered;
- what context and constraints matter;
- what output format you want;
- whether you want critique, options, risk analysis, design guidance, or implementation review.

When using Oracle for a dirty-worktree review, first inspect git status, git diff, and untracked files. After Oracle returns, run git status --short again. If the dirty scope changed while Oracle was running, do not blindly reuse the result; locally review the new diff and state the coverage boundary.

If a browser run hangs, do not re-run the same command. Check oracle status and oracle session <slug> first. If the cause is an oversized inline payload, kill the old process, shrink the context, and start a fresh slug.
