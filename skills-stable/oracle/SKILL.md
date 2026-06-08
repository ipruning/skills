---
name: oracle
description: "Ask Oracle for one bounded external second opinion through ChatGPT browser mode after local inspection. Default for PR/repo/dirty-worktree review is a repo zip attachment built with scripts/zip.py. Browser only."
---

Oracle is not the source of truth. Treat its answer as leads, then verify important claims locally.

## Local Oracle CLI

Use the installed `oracle` command in the workflow below. On a new macOS machine,
install or update the Jihuanshe fork with mise-managed Node/npm:

```sh
mise use -g node@24
mise exec -- npm install -g https://github.com/jihuanshe/oracle/releases/download/v0.13.1/oracle-0.13.1.tgz
oracle --version
```

If a machine previously installed the early fork tarball `v0.13.0`, migrate once
by removing the old upstream-scoped package and installing the Jihuanshe package:

```sh
mise exec -- npm uninstall -g @steipete/oracle @jihuanshe/oracle || true
mise exec -- npm install -g https://github.com/jihuanshe/oracle/releases/download/v0.13.1/oracle-0.13.1.tgz
```

After that, invoke Oracle as `oracle ...`; do not use `npx -y @steipete/oracle`
unless you intentionally want the upstream package instead of the Jihuanshe fork.

## Rules

- Use browser mode only.
- For PR review, repo review, dirty-worktree review, architecture review, or "audit/review this repo/PR", prefer a repository zip attachment with `.git`. The intent is to let Pro explore the repo in its browser sandbox instead of pre-flattening the evidence.
- Do not use `--browser-inline-files` for zip packages.
- If browser automation fails before prompt submission, report that Oracle did not run; do not present it as a model result.
- Do not start duplicate Oracle runs for the same slug/prompt. Check `oracle status <slug>` and `oracle session <slug>` first.

## Workflow

Inspect the local boundary before calling Oracle:

```sh
git status --short
git diff --stat
git diff --name-only <base>..HEAD
```

For dirty worktrees, inspect `git diff` and untracked files before the run. After Oracle returns, run `git status --short` again; if the dirty scope changed, review the new diff locally and state the coverage boundary.

Create a temporary work directory:

```sh
ORACLE_WORK_DIR="${TMPDIR:-/tmp}/oracle-work"
mkdir -p "$ORACLE_WORK_DIR"
```

Write a short `$ORACLE_WORK_DIR/PROMPT.md`. Include:

- project/problem;
- exact review boundary, including base/head/branch or dirty-worktree scope, so Pro can inspect it with git in the attached repo; for PRs, tell Pro which refs to compare, for example `git diff $(git merge-base HEAD origin/main)..HEAD`;
- what to audit;
- desired output format;
- "Do not invent findings without repository evidence."

Patch/stat files are usually not needed when the attached repo has `.git`; they duplicate information Pro can derive with `git diff`. Put boundary details and any necessary external context in the prompt. The review object should still be the Git repo, not a flattened patch bundle.

Build the zip with the bundled helper, resolved relative to this `SKILL.md`:

```sh
ORACLE_SKILL_DIR="<directory containing this SKILL.md>"
uv run --script "$ORACLE_SKILL_DIR/scripts/zip.py" \
  --prompt "$ORACLE_WORK_DIR/PROMPT.md" \
  --output "$ORACLE_WORK_DIR"
```

`scripts/zip.py` creates a package zip with a root `AGENTS.md` and the repository checkout one directory below it. The checkout includes `.git`, and the original repository contents are left intact.

- `--prompt` is required and becomes the package root `AGENTS.md`;
- `--output` / `-o` selects the output directory and defaults to `<system-temp>/oracle-work`;
- no additional context directory is created.

Dry-run as an uploaded attachment:

```sh
oracle --engine browser --model gpt-5.5-pro \
  --browser-attachments always \
  --max-file-size-bytes 52428800 \
  --dry-run summary --files-report \
  --file "$ORACLE_WORK_DIR/<repo-zip>.zip" \
  --prompt 'Review the attached repository zip. Follow the package root AGENTS.md instructions first. Return concrete findings first with file/path evidence.'
```

Proceed only if the dry-run says `Attachments to upload`. If it reports inline zip content, stop and fix the command.

Run Oracle with the same attachment flags:

```sh
oracle --engine browser --model gpt-5.5-pro \
  --browser-attachments always \
  --browser-hide-window \
  --max-file-size-bytes 52428800 \
  --file "$ORACLE_WORK_DIR/<repo-zip>.zip" \
  --prompt 'Review the attached repository zip. Follow the package root AGENTS.md instructions first. Return concrete findings first with file/path evidence.' \
  --slug short-descriptive-slug \
  --write-output "$ORACLE_WORK_DIR/answer.md"
```

For long runs, wait and inspect instead of restarting:

```sh
sleep 60
oracle status <slug>
test -s "$ORACLE_WORK_DIR/answer.md" && sed -n '1,220p' "$ORACLE_WORK_DIR/answer.md"
```

## Failure Handling

If model selection fails before submission, retry once with the same zip and slug suffix plus:

```sh
--browser-model-strategy ignore
```

`current` still touches the model selector; `ignore` is the strategy that skips it. Use `ignore` only when the active ChatGPT session is already on the desired model, or when using the active model is acceptable.

If the retry reports `promptSubmitted: false`, `chrome-disconnected`, `Chrome window closed before oracle finished`, or no output file, Oracle did not complete. Stop retrying and report browser automation failure.

If the zip is too large, shrink it by building a compact Git repo, not a patch bundle:

- create a temporary repository with `.git`;
- commit the relevant files at the review base;
- commit the relevant files at the review head;
- make sure the review diff is represented by commits, so `git diff HEAD~1..HEAD` inside that compact repo is the review diff;
- zip that compact repo with `scripts/zip.py` or another zip step that preserves `.git`;
- keep the prompt small and tell Pro to inspect the attached repo with `git diff HEAD~1..HEAD`.

Avoid falling back to inline files or a standalone patch bundle for PR/repo review: that changes the task from "explore this repo" to "read this excerpt" and loses useful Git context. If you include patch/stat files, keep them as supporting context, not the primary artifact.

## Verification

Read Oracle’s answer as a review draft, not proof:

- verify file paths and line references locally;
- run focused tests or static checks when feasible;
- separate Oracle claims from locally confirmed facts;
- report limitations clearly.
