---
name: oracle
description: "Use when the user explicitly asks for Oracle/神谕, ChatGPT Pro, a Pro second opinion, or one bounded external consultation through the user's logged-in Chrome session."
---

Choose the consultation route, package only needed evidence, submit it to the latest, smartest available Pro model in Chrome, save the answer, and verify it locally before reporting.

## Rules

- Use the user's logged-in Chrome session.
- Use the latest, smartest available Pro model by default. Use another Pro model only when the user approves it or the latest Pro model is unavailable.
- Do not use API mode.
- Do not click `Answer now` or any control that shortens Pro thinking.
- Treat visible ChatGPT activity as status. Do not call it a chain of thought.
- Build a package zip when local files affect the answer. Do not paste zip contents inline.
- For PR, repo, dirty-worktree, and architecture reviews, build a repo package zip that contains `.git`.
- For papers, archives, PDFs, source folders, datasets, and document packs, build an artifact package zip.
- Use `references/cli.md` only when Chrome control is unavailable, the environment is shell-only, or the user asks for Oracle CLI.
- Report `chrome_extension_unavailable`, `chrome_upload_permission_missing`, `chatgpt_login_required`, or `model_not_pro` when that blocker appears.
- Before submission, collect the scope, build the package zip, and write the prompt text. After the ChatGPT answer is saved, inspect files and run focused checks.

## Route

Choose one route before opening ChatGPT.

| Route              | Input                                                                            | Package                                             |
| ------------------ | -------------------------------------------------------------------------------- | --------------------------------------------------- |
| `repo-review`      | PR, repo, dirty worktree, architecture review, code review                       | repo package zip from `scripts/repo_zip.py`         |
| `artifact-consult` | Paper source files, LaTeX, PDF, downloaded zip, folder, dataset, non-Git files   | artifact package zip from `scripts/artifact_zip.py` |
| `web-consult`      | ChatGPT Pro should search, compare cited web sources, or challenge an assumption | optional artifact package zip                       |
| `prompt-only`      | No local files or URLs improve the answer                                        | none                                                |

If the user's request changes the files, refs, or URLs in scope, resolve the scope before building a package zip.

## Work Directory

```sh
ORACLE_WORK_DIR="${TMPDIR:-/tmp}/oracle-work/<short-slug>"
mkdir -p "$ORACLE_WORK_DIR"
PROMPT_FILE="$ORACLE_WORK_DIR/PROMPT.md"
ANSWER_FILE="$ORACLE_WORK_DIR/answer.md"
```

## Repo Review

Resolve the review base. Use the user's PR base when present. Otherwise use `ORACLE_BASE_REF`, then `origin/main`.

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

If `git rev-parse` or `git merge-base` fails, ask for the base ref. For a dirty worktree, inspect `git diff` and untracked files before building the repo package zip. After the ChatGPT answer is saved, run `git status --short`; if the dirty scope changed, report the covered scope.

Write `PROMPT_FILE` with:

- repository name and task;
- base ref, base SHA, head branch, and head SHA;
- exact review command, such as `git diff <base-sha>..HEAD`;
- dirty-worktree scope, when present;
- review focus;
- finding-first output format;
- `Do not invent findings without repository evidence.`

Build the repo package zip:

```sh
ORACLE_SKILL_DIR="<directory containing this SKILL.md>"
ZIP_FILE="$(uv run --script "$ORACLE_SKILL_DIR/scripts/repo_zip.py" \
  --prompt "$PROMPT_FILE" \
  --output "$ORACLE_WORK_DIR")"
```

`scripts/repo_zip.py` writes the package zip path to stdout. Inside the package zip, the package root contains `AGENTS.md`, and the repository checkout below it includes `.git`.

## Artifact Consult

Use local files or directories as evidence in the artifact package zip.

Write `PROMPT_FILE` with:

- question;
- local file names and what they contain;
- requested output;
- whether web search is allowed or required;
- `Do not invent claims that are not supported by files inside the uploaded package zip or cited web sources.`

Build the artifact package zip:

```sh
ORACLE_SKILL_DIR="<directory containing this SKILL.md>"
ZIP_FILE="$(uv run --script "$ORACLE_SKILL_DIR/scripts/artifact_zip.py" \
  --prompt "$PROMPT_FILE" \
  --output "$ORACLE_WORK_DIR" \
  --name "<short-slug>" \
  --file /path/to/artifact-or-directory)"
```

Repeat `--file` for multiple inputs. Inside the package zip, the package root contains `AGENTS.md`, `sources.md`, and `artifacts/`.

For a remote paper, source zip, or dataset URL, download the file first, record the URL in `PROMPT_FILE`, then add the downloaded file to the artifact package zip.

## Web Consult

Use web search when ChatGPT Pro should search or compare external sources.

Write `PROMPT_FILE` with:

- question;
- constraints and excluded assumptions;
- whether web search is required;
- output format;
- `Separate cited web claims from your own inferences.`

If non-Git local notes, screenshots, exports, or source files anchor the question, use `artifact-consult`. Use `repo-review` for Git repositories, code review, and architecture review.

## Prompt Only

Use this route when no local file, URL, or repository scope improves the answer.

Write `PROMPT_FILE` with:

- question;
- assumptions ChatGPT Pro may use;
- assumptions ChatGPT Pro must not use;
- output format;
- `State assumptions before conclusions.`

## Chrome Run

1. Open a fresh `https://chatgpt.com/` tab.
2. Confirm ChatGPT is logged in. If not, report `chatgpt_login_required`.
3. Confirm the composer model is the latest, smartest available Pro model, or another Pro model approved by the user. If not, report `model_not_pro`.
4. If the route built a package zip, open `Add files and more` -> `Upload photos & files`, upload `ZIP_FILE`, and confirm the attachment chip shows the zip filename.
5. Paste the contents of `PROMPT_FILE`.
6. Submit.
7. Record the conversation URL.
8. Wait.

When uploading a package zip, use the visible upload menu first. Do not start with hidden file inputs such as `#upload-files`; that path can reset the browser control session. If the visible menu cannot open a file chooser, reconnect Chrome once and retry the visible menu.

If Chrome reports `Browser is not available: extension` or `native pipe is closed`, reconnect the extension once. If it still fails, report `chrome_extension_unavailable`.

If upload fails with `Not allowed`, report `chrome_upload_permission_missing` and tell the user:

```text
Open chrome://extensions, click Details under the Codex extension, and enable "Allow access to file URLs."
```

## Wait

After submission, poll every 3-5 minutes. Do not press page controls while the answer is generating.

Record:

- conversation URL;
- generating or complete state;
- visible status, such as `Unzipping files`, `checking git status`, `Finalizing answer`, or `Thought for Xm Ys`;
- whether the final answer is visible;
- visible error, login prompt, upload rejection, or model-selection problem.

ChatGPT Pro runs can take 10-20 minutes or longer. `Finalizing answer` means progress unless the page shows an error or the user instructs otherwise.

## Save Answer

After the final ChatGPT answer appears, save the full assistant turn from the page DOM before local verification.

Use the latest assistant conversation turn, not visible viewport text. In Chrome DOM reads, find the latest conversation turn containing `data-message-author-role="assistant"`. Scoped extraction from `[data-testid^="conversation-turn-"]` is acceptable. Do not extract `document.body.innerText`.

Save the final answer text to `ANSWER_FILE`. The saved answer must contain:

- final answer text only;
- all sections and verification commands present in the page;
- no user prompt text;
- no partial activity text.

Verify extraction:

```sh
test -s "$ANSWER_FILE"
wc -c "$ANSWER_FILE"
rg -n "Findings|Not findings|Rejected|Summary|Claims|Sources|Verification|Open questions|Recommendations" "$ANSWER_FILE"
tail -n 40 "$ANSWER_FILE"
```

If DOM extraction fails or returns only visible text, use ChatGPT's copy control for the final assistant message. If copying is unavailable, scroll through the final ChatGPT answer and extract sections in order. Mark `ANSWER_FILE` as `partial` unless `tail -n 40 "$ANSWER_FILE"` shows the expected ending.

## Accept Answer

Require:

- recorded conversation URL;
- latest, smartest available Pro model, or user-approved visible Pro model;
- non-empty `ANSWER_FILE`;
- visible attachment chip before submission when a package zip was uploaded;
- answer that uses the route's evidence.

Evidence requirements:

- `repo-review`: repository paths, diff evidence, impact, and suggested fix.
- `artifact-consult`: uploaded filenames, file/page/section references when available, supported claims, and uncertainty.
- `web-consult`: cited web URLs or source names, date-sensitive caveats, and separated inference.
- `prompt-only`: direct answer and stated assumptions.

If the answer asks for missing files, ignores an uploaded package zip, or returns suspiciously fast for a large package zip, mark it low-confidence. Inspect the visible conversation state before rerunning. Do not start duplicate runs blindly.

## Verify

Read `ANSWER_FILE` as a draft:

- verify paths, lines, pages, URLs, and quoted claims locally;
- run focused tests or static checks when feasible;
- separate claims in `ANSWER_FILE` from locally confirmed facts;
- reject hallucinated or non-reproducible claims;
- report blockers and coverage limits.

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
