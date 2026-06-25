---
name: oracle
description: "Use when the user asks for one bounded outside ChatGPT Pro consultation through Chrome automation, Oracle CLI, or a manual handoff package."
---

The agent gets one outside answer, verifies it against local evidence, and gives the user only claims that survive verification.

## Rules

- The agent uses the newest visible Pro model by default.
- If several Pro models are visible, the agent chooses the highest-capability one named by the UI or CLI.
- The agent uses another model only when the user approves it or no Pro model is available.
- The agent does not use API mode.
- The agent does not click `Answer now` or any control that shortens Pro thinking.
- The agent treats visible ChatGPT activity as status, not as a chain of thought.
- The agent builds a package zip when local files affect the answer.
- The agent does not paste package contents into ChatGPT.
- The agent does not start a duplicate run after Chrome or CLI submits the prompt.
- The agent does not claim that ChatGPT Pro reviewed a package until a submitted run or the user provides the outside answer.

## Names

- `consultation type`: what kind of question the user asks.
- `delivery path`: how the prompt and package reach ChatGPT Pro.
- `package`: zip file containing local evidence.
- `prompt file`: the exact prompt submitted to ChatGPT Pro or handed to the user.
- `outside answer`: final ChatGPT Pro response before local verification.
- `answer file`: saved `outside answer`.
- `manual handoff`: local `prompt file` and `package` copied to `~/Downloads` for the user to submit.
- `Chrome automation`: automation of the user's logged-in Chrome session.
- `Codex in-app Browser`: the browser inside Codex. It can submit prompt-only requests, but it cannot upload package files.

## Consultation Type

The agent chooses one consultation type before building a prompt.

| Type                   | User request                                                                                                    | Package                                             |
| ---------------------- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `repo-diff-review`     | PR, dirty worktree, code review, or review that depends on a base ref, branch, commit range, or diff            | repo package zip from `scripts/repo_zip.py`         |
| `repo-context-consult` | Repo architecture, implementation, or design consultation that depends on scoped repo files but not Git history | artifact package zip from `scripts/artifact_zip.py` |
| `artifact-consult`     | Paper files, LaTeX, PDF, downloaded archive, folder, dataset, or non-Git files                                  | artifact package zip from `scripts/artifact_zip.py` |
| `web-consult`          | ChatGPT Pro should search or compare cited web sources                                                          | optional artifact package zip                       |
| `prompt-only`          | No local file, URL, or repository scope improves the answer                                                     | none                                                |

If the user changes the files, refs, URLs, or review base, the agent resolves the scope again before building a package.

The agent chooses the consultation type in this order:

1. If the question asks for review of current changes, a PR, a branch, a base ref, or a diff, choose `repo-diff-review`.
2. If repo implementation files control the answer and Git history does not, choose `repo-context-consult`.
3. If local non-repo files, archives, screenshots, PDFs, papers, folders, or datasets control the answer, choose `artifact-consult`.
4. If current web sources control the answer, choose `web-consult`.
5. If no local or web evidence improves the answer, choose `prompt-only`.

When web sources and local files both matter, local evidence decides the consultation type unless web sources remain the primary evidence. Non-Git files use `artifact-consult`; repo implementation files use `repo-context-consult`; diffs use `repo-diff-review`. Downloadable paper, code archive, and dataset URLs use `artifact-consult` after download unless the user asks ChatGPT Pro to compare live web claims.

## Package Scope

For package consultation types, the agent chooses the smallest package that can support the answer.

- `minimal`: exact files, screenshots, papers, or diffs named by the request.
- `scoped`: repo subtrees that own the design or bug under review.
- `broad`: multiple repos or large subtrees when the user asks for a whole-system challenge.

The package excludes secrets, generated dependencies, build output, and unrelated caches unless the user asks for them and confirms the exposure.

## Work Directory

The agent creates `ORACLE_WORK_DIR` under `${TMPDIR:-/tmp}/oracle-work/<short-slug>`. The agent writes `PROMPT_FILE` and, when needed, `ZIP_FILE` there. The agent writes `ANSWER_FILE` there after automation can harvest the final answer.

## Repo Diff Review

The agent chooses `repo-diff-review` for PRs, dirty worktrees, code reviews, and reviews that depend on a base ref, branch, commit range, or diff. The agent uses the user's PR base when present. Otherwise the agent uses `ORACLE_BASE_REF`, then `origin/main`.

```sh
BASE_REF="${ORACLE_BASE_REF:-origin/main}"
git rev-parse --verify "$BASE_REF"
BASE_SHA="$(git merge-base HEAD "$BASE_REF")"
HEAD_SHA="$(git rev-parse HEAD)"
git status --short
git branch --show-current
git diff --stat "$BASE_SHA..HEAD"
git diff --name-only "$BASE_SHA..HEAD"
```

If `git rev-parse` or `git merge-base` fails, the agent asks for the base ref. For a dirty worktree, the agent inspects `git diff` and untracked files before building the package. After saving the answer, the agent runs `git status --short`; if `git status --short` or the inspected dirty-file list changed, the agent states the covered scope.

The agent writes `PROMPT_FILE` with:

- repository name and task;
- base ref, base SHA, head branch, and head SHA;
- exact review command, such as `git diff <base-sha>..HEAD`;
- dirty-worktree scope, when present;
- review focus;
- finding-first output format;
- `Do not invent findings without repository evidence.`

The agent builds the package:

```sh
ORACLE_SKILL_DIR="<directory containing this SKILL.md>"
ZIP_FILE="$(uv run --script "$ORACLE_SKILL_DIR/scripts/repo_zip.py" \
  --prompt "$PROMPT_FILE" \
  --output "$ORACLE_WORK_DIR")"
```

`scripts/repo_zip.py` writes the zip path to stdout. The zip root contains `AGENTS.md`, and the repository checkout under the zip root includes `.git`.

## Repo Context Consult

The agent chooses `repo-context-consult` for architecture, implementation, or design consultation when scoped repo files matter but Git history and diffs do not. The agent does not include `.git` unless the user asks for history or the question depends on history.

The agent writes `PROMPT_FILE` with:

- repository name and question;
- scoped repo paths and what they contain;
- constraints and excluded assumptions;
- requested output;
- `Do not invent claims that are not supported by files inside the uploaded package zip.`

The agent builds the package with the scoped repo paths:

```sh
ORACLE_SKILL_DIR="<directory containing this SKILL.md>"
ZIP_FILE="$(uv run --script "$ORACLE_SKILL_DIR/scripts/artifact_zip.py" \
  --prompt "$PROMPT_FILE" \
  --output "$ORACLE_WORK_DIR" \
  --name "<short-slug>" \
  --file /path/to/scoped-repo-file-or-directory)"
```

The agent repeats `--file` for multiple scoped paths.

## Artifact Consult

The agent chooses `artifact-consult` when local files or directories are the evidence.

The agent writes `PROMPT_FILE` with:

- question;
- local file names and what they contain;
- requested output;
- whether web search is allowed or required;
- `Do not invent claims that are not supported by files inside the uploaded package zip or cited web sources.`

The agent builds the package:

```sh
ORACLE_SKILL_DIR="<directory containing this SKILL.md>"
ZIP_FILE="$(uv run --script "$ORACLE_SKILL_DIR/scripts/artifact_zip.py" \
  --prompt "$PROMPT_FILE" \
  --output "$ORACLE_WORK_DIR" \
  --name "<short-slug>" \
  --file /path/to/artifact-or-directory)"
```

The agent repeats `--file` for multiple inputs. The zip root contains `AGENTS.md`, `sources.md`, and `artifacts/`.

For a remote paper, code archive, or dataset URL, the agent downloads the file first, records the URL in `PROMPT_FILE`, and adds the downloaded file to the package.

## Web Consult

The agent chooses `web-consult` when ChatGPT Pro should search or compare external sources.

The agent writes `PROMPT_FILE` with:

- question;
- constraints and excluded assumptions;
- whether web search is required;
- output format;
- `Separate cited web claims from your own inferences.`

## Prompt Only

The agent chooses `prompt-only` when no local evidence improves the answer.

The agent writes `PROMPT_FILE` with:

- question;
- assumptions ChatGPT Pro may use;
- assumptions ChatGPT Pro must not use;
- output format;
- `State assumptions before conclusions.`

## Delivery Path

The agent chooses one delivery path after it writes `PROMPT_FILE` and builds any required package.

| Path             | Condition                                                        | Action                                        |
| ---------------- | ---------------------------------------------------------------- | --------------------------------------------- |
| `chrome-run`     | Chrome automation is available                                   | Submit prompt and package in logged-in Chrome |
| `in-app-run`     | Only Codex in-app Browser is available and no package is needed  | Submit `PROMPT_FILE` in the in-app Browser    |
| `cli-run`        | Chrome automation is unavailable or shell-only work is requested | Follow `references/cli.md`                    |
| `manual-handoff` | A package is needed but upload or CLI submission is unavailable  | Copy prompt and package to `~/Downloads`      |

For package consultation types, Codex in-app Browser is not a valid delivery path because it cannot upload package files.

## Browser Run

`chrome-run` uses the user's logged-in Chrome session. `in-app-run` uses Codex in-app Browser for `prompt-only` consultation.

1. The agent opens a fresh `https://chatgpt.com/` tab.
2. The agent confirms ChatGPT is logged in. If ChatGPT is not logged in, the agent returns `chatgpt_login_required`.
3. The agent confirms the composer model is the newest visible Pro model, the highest-capability visible Pro model, or another user-approved model. If the model is not an approved Pro model, the agent returns `model_not_pro`.
4. If `chrome-run` has a package, the agent opens `Add files and more` -> `Upload photos & files`, uploads `ZIP_FILE`, and confirms the attachment chip shows the zip filename.
5. If `in-app-run` has `ZIP_FILE`, the agent switches to `manual-handoff`.
6. The agent pastes `PROMPT_FILE`.
7. The agent submits the prompt.
8. The agent records the conversation URL.
9. The agent waits.

When Chrome upload fails because the visible upload menu cannot open a file chooser, the agent reconnects Chrome once and retries the visible menu.

If the active browser reports that file uploads are unsupported, the agent stops upload attempts and switches to `manual-handoff`. The agent does not try CDP file inputs, hidden file inputs, or repeated file chooser calls.

If Chrome reports `Browser is not available: extension` or `native pipe is closed` before submission, the agent reconnects the extension once. If Chrome still fails and CLI fallback is allowed, the agent uses `references/cli.md`; otherwise the agent returns `chrome_extension_unavailable`.

If upload fails with `Not allowed`, the agent returns `chrome_upload_permission_missing` and tells the user:

```text
Open chrome://extensions, click Details under the browser-control extension, and enable "Allow access to file URLs."
```

## Manual Handoff

`manual-handoff` prepares files for the user to submit.

The agent copies `PROMPT_FILE` and `ZIP_FILE` to `~/Downloads` with short descriptive names:

```sh
cp "$PROMPT_FILE" "$HOME/Downloads/<slug>-oracle-prompt.md"
cp "$ZIP_FILE" "$HOME/Downloads/<slug>-oracle-package.zip"
```

The agent gives the user both file paths and tells the user to upload the package zip and paste the prompt. The agent waits for the user to provide the outside answer before verification.

## Wait

After submission, the agent polls every 3-5 minutes. The agent does not press page controls while the answer is generating.

The agent records:

- conversation URL;
- generating or complete state;
- visible progress labels;
- whether the final answer is visible;
- visible error, login prompt, upload rejection, or model-selection problem.

ChatGPT Pro runs can take 10-20 minutes or longer. Visible progress labels mean progress unless the page shows an error or the user instructs otherwise.

## Save Answer

After the final ChatGPT answer appears, the agent saves the full assistant turn from the page DOM before local verification.

The agent uses the latest assistant conversation turn, not visible viewport text. In Chrome DOM reads, the agent finds the latest conversation turn containing `data-message-author-role="assistant"`. The agent may use scoped extraction from `[data-testid^="conversation-turn-"]`. The agent does not extract `document.body.innerText`.

The agent saves final answer text only. `ANSWER_FILE` must contain all sections and verification commands present in the page. `ANSWER_FILE` must not contain the user prompt or partial activity text.

The agent verifies extraction:

```sh
test -s "$ANSWER_FILE"
wc -c "$ANSWER_FILE"
rg -n "Findings|Not findings|Rejected|Summary|Claims|Sources|Verification|Open questions|Recommendations" "$ANSWER_FILE"
tail -n 40 "$ANSWER_FILE"
```

If DOM extraction fails or returns only visible text, the agent uses ChatGPT's copy control for the final assistant message. If copying is unavailable, the agent scrolls through the final answer and extracts sections in order. The agent marks `ANSWER_FILE` as `partial` unless `tail -n 40 "$ANSWER_FILE"` shows the expected ending.

## Accept Answer

The agent accepts an automated answer only when these facts exist:

- recorded conversation URL;
- newest visible Pro model, highest-capability visible Pro model, or user-approved model;
- non-empty `ANSWER_FILE`;
- visible attachment chip before submission when a package was uploaded;
- final answer uses the evidence required by the consultation type.

Evidence requirements:

- `repo-diff-review`: repository paths, diff evidence, impact, and suggested fix.
- `repo-context-consult`: scoped repo paths, supported claims, impact, and suggested fix or recommendation.
- `artifact-consult`: uploaded filenames, file/page/section references when available, supported claims, and uncertainty.
- `web-consult`: cited web URLs or source names, date-sensitive caveats, and separated inference.
- `prompt-only`: direct answer and stated assumptions.

If the answer asks for missing files, ignores an uploaded package, or returns before the uploaded package appears accepted, processed, or referenced in the answer, the agent marks the answer low-confidence. The agent inspects the conversation state before rerunning. The agent does not start duplicate runs blindly.

## Verify

The agent treats `ANSWER_FILE` or the user-provided outside answer as a draft.

- The agent verifies paths, lines, pages, URLs, and quoted claims locally.
- The agent runs focused tests or static checks when feasible.
- The agent separates outside claims from locally confirmed facts.
- The agent rejects hallucinated or non-reproducible claims.
- The agent states blockers and coverage limits.

Review user output:

```text
Confirmed findings
Rejected / not findings
Local verification
Coverage limits
```

Consult user output:

```text
Answer
Evidence in the saved answer
What I verified locally
Limits / next checks
```
