---
name: oracle
description: "Use when the user asks the agent to get one bounded outside answer from Oracle/神谕 or ChatGPT Pro through the user's logged-in Chrome session."
---

The agent chooses a consultation route, packages only the needed local evidence, submits the prompt to the latest, smartest available Pro model in Chrome, saves the final answer, and verifies claims locally before reporting.

## Rules

- The agent uses the user's logged-in Chrome session.
- The agent uses the latest, smartest available Pro model by default. The agent uses another Pro model only when the user approves it or the latest Pro model is unavailable.
- The agent does not use API mode.
- The agent does not click `Answer now` or any control that shortens Pro thinking.
- The agent treats visible ChatGPT activity as status. The agent does not call that activity a chain of thought.
- The agent builds a package zip when local files affect the answer. The agent does not paste zip contents inline.
- Diff-based repo reviews use a repo package zip that contains `.git`.
- Repo consultations that do not depend on a base ref or diff use an artifact package zip from scoped repo files.
- Papers, archives, PDFs, local files, local folders, datasets, and document packs use an artifact package zip.
- The agent uses `references/cli.md` before submission when direct Chrome control is unavailable, the environment is shell-only, or the user asks for Oracle CLI. The agent does not start a duplicate CLI run after a Chrome run submits.
- The agent reports `chrome_extension_unavailable`, `chrome_upload_permission_missing`, `chatgpt_login_required`, or `model_not_pro` when the blocker prevents the chosen route and any allowed fallback.
- Before submission, the agent resolves the scope, builds the package zip when the route requires one, and writes the prompt text. After the agent saves the final answer, the agent inspects files and runs focused checks.

## Route

The agent chooses one route before opening ChatGPT.

| Route                  | Input                                                                                                            | Package                                             |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `repo-diff-review`     | PR, dirty worktree, code review, or review that depends on a base ref, branch, commit range, or diff             | repo package zip from `scripts/repo_zip.py`         |
| `repo-context-consult` | Repo architecture, implementation, or design consultation that depends on scoped repo files but not Git history  | artifact package zip from `scripts/artifact_zip.py` |
| `artifact-consult`     | Paper files, LaTeX, PDF, downloaded archive, folder, dataset, non-Git files                                      | artifact package zip from `scripts/artifact_zip.py` |
| `web-consult`          | ChatGPT Pro should search or compare cited web sources, including assumption challenges that require web sources | optional artifact package zip                       |
| `prompt-only`          | No local files or URLs improve the answer                                                                        | none                                                |

If the user's request changes the files, refs, or URLs in scope, the agent resolves the scope before building a package zip.

## Work Directory

The agent creates `ORACLE_WORK_DIR` under `${TMPDIR:-/tmp}/oracle-work/<short-slug>`. The agent writes the prompt text to `PROMPT_FILE` and saves the final ChatGPT answer to `ANSWER_FILE` inside `ORACLE_WORK_DIR`.

## Repo Diff Review

The agent chooses `repo-diff-review` for PRs, dirty worktrees, code reviews, and reviews that depend on a base ref, branch, commit range, or diff. The agent resolves the review base. The agent uses the user's PR base when present. Otherwise the agent uses `ORACLE_BASE_REF`, then `origin/main`.

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

If `git rev-parse` or `git merge-base` fails, the agent asks for the base ref. For a dirty worktree, the agent inspects `git diff` and untracked files before building the repo package zip. After the agent saves the final answer, the agent runs `git status --short`; if the dirty scope changed, the agent reports the covered scope.

The agent writes `PROMPT_FILE` with:

- repository name and task;
- base ref, base SHA, head branch, and head SHA;
- exact review command, such as `git diff <base-sha>..HEAD`;
- dirty-worktree scope, when present;
- review focus;
- finding-first output format;
- `Do not invent findings without repository evidence.`

The agent builds the repo package zip:

```sh
ORACLE_SKILL_DIR="<directory containing this SKILL.md>"
ZIP_FILE="$(uv run --script "$ORACLE_SKILL_DIR/scripts/repo_zip.py" \
  --prompt "$PROMPT_FILE" \
  --output "$ORACLE_WORK_DIR")"
```

`scripts/repo_zip.py` writes the package zip path to stdout. Inside the package zip, the package root contains `AGENTS.md`, and the repository checkout below the package root includes `.git`.

## Repo Context Consult

The agent chooses `repo-context-consult` for architecture, implementation, or design consultation when scoped repo files matter but Git history and diffs do not. The agent resolves the repo paths in scope before packaging. The agent does not include `.git` unless the user asks for history or the question depends on history.

The agent writes `PROMPT_FILE` with:

- repository name and question;
- scoped repo paths and what they contain;
- constraints and excluded assumptions;
- requested output;
- `Do not invent claims that are not supported by files inside the uploaded package zip.`

The agent builds the artifact package zip with the scoped repo paths:

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

The agent uses local files or directories as evidence in the artifact package zip.

The agent writes `PROMPT_FILE` with:

- question;
- local file names and what they contain;
- requested output;
- whether web search is allowed or required;
- `Do not invent claims that are not supported by files inside the uploaded package zip or cited web sources.`

The agent builds the artifact package zip:

```sh
ORACLE_SKILL_DIR="<directory containing this SKILL.md>"
ZIP_FILE="$(uv run --script "$ORACLE_SKILL_DIR/scripts/artifact_zip.py" \
  --prompt "$PROMPT_FILE" \
  --output "$ORACLE_WORK_DIR" \
  --name "<short-slug>" \
  --file /path/to/artifact-or-directory)"
```

The agent repeats `--file` for multiple inputs. Inside the package zip, the package root contains `AGENTS.md`, the `sources.md` manifest, and `artifacts/`.

For a remote paper, code archive, or dataset URL, the agent downloads the file first, records the URL in `PROMPT_FILE`, and adds the downloaded file to the artifact package zip.

## Web Consult

The agent chooses `web-consult` when ChatGPT Pro should search or compare external sources.

The agent writes `PROMPT_FILE` with:

- question;
- constraints and excluded assumptions;
- whether web search is required;
- output format;
- `Separate cited web claims from your own inferences.`

If non-Git local notes, screenshots, exports, or local files anchor the question, the agent chooses `artifact-consult`. The agent chooses `repo-context-consult` for repo architecture or implementation consultation. The agent chooses `repo-diff-review` for PRs, code reviews, dirty worktrees, and diff-based reviews.

## Prompt Only

The agent chooses `prompt-only` when no local file, URL, or repository scope improves the answer.

The agent writes `PROMPT_FILE` with:

- question;
- assumptions ChatGPT Pro may use;
- assumptions ChatGPT Pro must not use;
- output format;
- `State assumptions before conclusions.`

## Chrome Run

1. The agent opens a fresh `https://chatgpt.com/` tab.
2. The agent confirms ChatGPT is logged in. If ChatGPT is not logged in, the agent reports `chatgpt_login_required`.
3. The agent confirms the composer model is the latest, smartest available Pro model, or another Pro model approved by the user. If the model is not an approved Pro model, the agent reports `model_not_pro`.
4. If the route built a package zip, the agent opens `Add files and more` -> `Upload photos & files`, uploads `ZIP_FILE`, and confirms the attachment chip shows the zip filename.
5. The agent pastes the contents of `PROMPT_FILE`.
6. The agent submits the prompt.
7. The agent records the conversation URL.
8. The agent waits.

When the agent uploads a package zip, the agent uses the visible upload menu first. If the visible menu cannot open a file chooser, the agent reconnects Chrome once and retries the visible menu.

If Chrome reports `Browser is not available: extension` or `native pipe is closed` before submission, the agent reconnects the extension once. If Chrome still fails and CLI fallback is allowed, the agent uses `references/cli.md`; otherwise the agent reports `chrome_extension_unavailable`.

If upload fails with `Not allowed`, the agent reports `chrome_upload_permission_missing` and tells the user:

```text
Open chrome://extensions, click Details under the browser-control extension, and enable "Allow access to file URLs."
```

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

The agent saves the final answer text to `ANSWER_FILE`. The saved answer must contain:

- final answer text only;
- all sections and verification commands present in the page;
- no user prompt text;
- no partial activity text.

The agent verifies extraction:

```sh
test -s "$ANSWER_FILE"
wc -c "$ANSWER_FILE"
rg -n "Findings|Not findings|Rejected|Summary|Claims|Sources|Verification|Open questions|Recommendations" "$ANSWER_FILE"
tail -n 40 "$ANSWER_FILE"
```

If DOM extraction fails or returns only visible text, the agent uses ChatGPT's copy control for the final assistant message. If copying is unavailable, the agent scrolls through the final ChatGPT answer and extracts sections in order. The agent marks `ANSWER_FILE` as `partial` unless `tail -n 40 "$ANSWER_FILE"` shows the expected ending.

## Accept Answer

The agent requires:

- recorded conversation URL;
- latest, smartest available Pro model, or user-approved visible Pro model;
- non-empty `ANSWER_FILE`;
- visible attachment chip before submission when a package zip was uploaded;
- final answer uses the chosen route's evidence.

Evidence requirements:

- `repo-diff-review`: repository paths, diff evidence, impact, and suggested fix.
- `repo-context-consult`: scoped repo paths, supported claims, impact, and suggested fix or recommendation.
- `artifact-consult`: uploaded filenames, file/page/section references when available, supported claims, and uncertainty.
- `web-consult`: cited web URLs or source names, date-sensitive caveats, and separated inference.
- `prompt-only`: direct answer and stated assumptions.

If the answer asks for missing files, ignores an uploaded package zip, or returns suspiciously fast for a large package zip, the agent marks the answer low-confidence. The agent inspects the visible conversation state before rerunning. The agent does not start duplicate runs blindly.

## Verify

The agent reads `ANSWER_FILE` as a draft:

- The agent verifies paths, lines, pages, URLs, and quoted claims locally.
- The agent runs focused tests or static checks when feasible.
- The agent separates claims in `ANSWER_FILE` from locally confirmed facts.
- The agent rejects hallucinated or non-reproducible claims.
- The agent reports blockers and coverage limits.

Review report:

```text
Confirmed findings
Rejected / not findings
Local verification
Coverage limits
```

Consult report:

```text
Answer
Evidence in the saved answer
What I verified locally
Limits / next checks
```
