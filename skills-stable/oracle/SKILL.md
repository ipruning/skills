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
If `oracle` fails with a mise shim/runtime error, run `mise use -g node@24`, then
rerun the same command as `mise exec -- oracle ...`.

## Rules

- Use browser mode only.
- For PR review, repo review, dirty-worktree review, architecture review, or "audit/review this repo/PR", prefer a repository zip attachment with `.git`. The intent is to let Pro explore the repo in its browser sandbox instead of pre-flattening the evidence.
- Do not use `--browser-inline-files` for zip packages.
- If browser automation fails before prompt submission, report that Oracle did not run; do not present it as a model result.
- Do not start duplicate Oracle runs for the same slug/prompt. Before any rerun or compact fallback, inspect the existing session state with `oracle session <slug> --harvest` or `--live`; top-level `running` is not enough evidence to rerun.
- Treat the browser tab as the source of truth after a browser run starts. A local shell timeout or stale session list can leave the session metadata at `running` even when ChatGPT later completed.
- If any session for the requested review has `promptSubmitted: true`, do not start another run or compact fallback unless ChatGPT/browser explicitly rejects the uploaded file, the browser disconnects before completion, or the user asks to rerun with a smaller package.

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
  --max-file-size-bytes 104857600 \
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
  --max-file-size-bytes 104857600 \
  --file "$ORACLE_WORK_DIR/<repo-zip>.zip" \
  --prompt 'Review the attached repository zip. Follow the package root AGENTS.md instructions first. Return concrete findings first with file/path evidence.' \
  --slug short-descriptive-slug \
  --write-output "$ORACLE_WORK_DIR/answer.md"
```

Use the actual `Session: ...` value printed by the CLI for all later
`oracle session` commands. The stored session id may be a deduplicated or
shortened variant of the requested `--slug`.

For long runs, harvest the same browser session instead of restarting:

```sh
sleep 60
oracle session <slug> --harvest --write-output "$ORACLE_WORK_DIR/answer.md" || true
test -s "$ORACLE_WORK_DIR/answer.md" && sed -n '1,220p' "$ORACLE_WORK_DIR/answer.md"
```

If the foreground command is killed by the agent shell timeout, do not assume the
Oracle run failed. The browser controller may have already submitted the prompt
and the ChatGPT tab may continue generating. Reattach/harvest the existing slug:

```sh
oracle session <slug> --live --write-output "$ORACLE_WORK_DIR/answer.md"
```

If `--live` is inconvenient or times out locally, harvest the current tab without
starting a new run:

```sh
oracle session <slug> --harvest --write-output "$ORACLE_WORK_DIR/answer.md"
```

When the conversation URL is known, pass it explicitly to avoid attaching to the
wrong tab:

```sh
oracle session <slug> --harvest \
  --browser-tab 'https://chatgpt.com/c/<conversation-id>' \
  --write-output "$ORACLE_WORK_DIR/answer.md"
```

Interpret these signals as follows:

- Read session metadata with `sed -n '1,220p' "$HOME/.oracle/sessions/<slug>/meta.json"`.
- `promptSubmitted: false` in `~/.oracle/sessions/<slug>/meta.json`: prompt never reached ChatGPT. You may retry after fixing the stated browser/login issue.
- `promptSubmitted: true` plus no output file: do **not** rerun yet; use `oracle session <slug> --live` or `--harvest`.
- `browser.harvest.state: completed` in `meta.json`: the model completed even if the top-level session status still says `running`.
- `oracle session <slug> --harvest` saying the assistant is still generating: wait or use `--live`; this is not a failure.
- Local shell messages like `Command timed out after ...`: the agent-side command timed out, not necessarily the browser/model run.

## Failure Handling

If Cloudflare or a manual login/check blocks the first browser launch before
submission, the error details include a reusable browser profile. Complete the
check in the opened Chrome window if visible. If no visible check remains, still
retry once with the same zip and the printed profile directory before reporting
failure:

```sh
oracle --engine browser --model gpt-5.5-pro \
  --browser-attachments always \
  --browser-hide-window \
  --browser-manual-login-profile-dir "<printed-profile-dir>" \
  --max-file-size-bytes 104857600 \
  --file "$ORACLE_WORK_DIR/<repo-zip>.zip" \
  --prompt 'Review the attached repository zip. Follow the package root AGENTS.md instructions first. Return concrete findings first with file/path evidence.' \
  --slug <slug>-retry \
  --write-output "$ORACLE_WORK_DIR/answer.md"
```

After this retry, check the retry session's `meta.json`: if `promptSubmitted` is
`true`, keep harvesting that session until completion instead of starting another
copy. Count retries per failure branch; do not chain Cloudflare retry,
model-strategy retry, and compact fallback unless the latest session still has
`promptSubmitted: false`.

If model selection fails before submission, retry once with the same zip and slug suffix plus:

```sh
--browser-model-strategy ignore
```

`current` still touches the model selector; `ignore` is the strategy that skips it. Use `ignore` only when the active ChatGPT session is already on the desired model, or when using the active model is acceptable.

If a session has `promptSubmitted: false`, `chrome-disconnected`, or `Chrome window closed before oracle finished`, Oracle did not complete. Stop retrying after the one targeted retry above and report browser automation failure.

Do not treat "no output file" alone as failure for browser runs. First run:

```sh
oracle session <slug> --harvest --write-output "$ORACLE_WORK_DIR/answer.md"
```

Only report failure if harvest/live cannot find a completed assistant answer and
the session metadata or CLI error shows the prompt was not submitted, the browser
disconnected, or the Chrome window closed before completion.

Only fall back to a compact Git repo after checking the original slug with
`--harvest` or `--live`. A large zip plus a slow ChatGPT response is not by
itself a reason to rerun. If the original session was never submitted, failed
before submission, or ChatGPT/browser explicitly rejected the upload as too
large, shrink it by building a compact Git repo, not a patch bundle:

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
